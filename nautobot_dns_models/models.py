"""Models for Nautobot DNS Models."""

# Past pylint's 1000-line default. Splitting this into a package (zones, records, catalog) is the
# real fix, but it has to route the runtime references between zones and records around a circular
# import, so it is deferred rather than folded into the catalog zone work.
# pylint: disable=too-many-lines

import base64
import uuid

from constance import config as constance_config
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, validate_email
from django.db import models, transaction
from django.db.models import ProtectedError, Q
from nautobot.apps.models import BaseManager, BaseModel, PrimaryModel, RestrictedQuerySet, extras_features
from nautobot.core.models.fields import ForeignKeyWithAutoRelatedName
from nautobot.extras.models import StatusField
from nautobot.ipam.choices import IPAddressVersionChoices
from netutils.ip import ipaddress_address

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.system_writes import system_write, system_write_in_progress

# Reverse-DNS roots per RFC 1035 §3.5 and RFC 3596 §2.5
RESERVED_ROOTS = {"in-addr.arpa", "ip6.arpa", "arpa"}

# All DNS integer fields use the full unsigned 32-bit range (0..4294967295).
# RFC 8767 §4 defines TTL as a 32-bit unsigned integer (updating RFC 2181).
# RFC 1035 §3.3.13 defines SOA fields as 32-bit values, explicitly unsigned for SERIAL and MINIMUM;
# RFC 1982 §7 specifies SERIAL's uint32 range and arithmetic.
UINT32_MAX = 2**32 - 1

SYSTEM_MANAGED_DELETE_ERROR = "System-managed records cannot be deleted directly."

# Owner name standing for the zone apex, following the master-file convention of RFC 1035 §5.1.
# Stored rather than left empty because `DNSRecord.name` is not blank.
APEX_RECORD_NAME = "@"

# RFC 9432 §4 requires an NS RRset in a catalog zone so that it is a syntactically valid zone, and
# recommends a single RR naming "invalid.". Consumers never resolve it, so the value is pinned here
# rather than offered as a choice. Stored without the trailing dot the RFC writes: a name server is
# an absolute domain name here, so master-file syntax is the renderer's to add.
CATALOG_APEX_NS_SERVER = "invalid"

# Record models users may create in a zone, keyed by zone type: True for every model, False for
# none, or a frozenset of the specific models permitted. A zone type absent from this map permits
# nothing. A catalog zone (RFC 9432) holds only the records this app maintains; it gains an
# NSRecord-only frozenset once apex records can be stored.
ZONE_TYPE_USER_RECORDS = {
    DNSZoneTypeChoices.TYPE_PRIMARY: True,
    DNSZoneTypeChoices.TYPE_CATALOG: False,
}


def zone_type_allows(zone_type, record_model):
    """Return whether users may manage `record_model` records in a zone of `zone_type`."""
    allowed = ZONE_TYPE_USER_RECORDS.get(zone_type, False)
    if isinstance(allowed, bool):
        return allowed
    return record_model in allowed


def zone_type_allows_user_records(zone_type):
    """Return whether a zone of `zone_type` permits users to manage any record types."""
    allowed = ZONE_TYPE_USER_RECORDS.get(zone_type, False)
    if isinstance(allowed, bool):
        return allowed
    return bool(allowed)


def dns_wire_label_length(label):
    """Return the wire-format (IDNA/Punycode) length of a DNS label."""
    if label.isascii():
        return len(label)

    return len("xn--" + label.encode("punycode").decode("ascii"))


def _find_unescaped_dot(value):
    """Return the position of the first unescaped dot, or None."""
    character_is_escaped = False
    for index, character in enumerate(value):
        if character_is_escaped:
            character_is_escaped = False
            continue

        if character == "\\":
            character_is_escaped = True
        elif character == ".":
            return index

    return None


def normalize_soa_rname(value):
    """Normalize a basic DNS-style SOA RNAME mailbox to email form."""
    if not value or "@" in value:
        return value

    value_without_root = value.removesuffix(".")
    separator = _find_unescaped_dot(value_without_root)
    if separator is None:
        return value_without_root

    local_part = value_without_root[:separator].replace(r"\.", ".")
    domain = value_without_root[separator + 1 :]
    if not local_part or not domain or "\\" in local_part or "\\" in domain or "" in domain.split("."):
        return value

    return f"{local_part}@{domain}"


def catalog_member_label():
    """Return a new opaque DNS label for a catalog zone member.

    RFC 9432 §4.1 lets a producer pick any unique label and treats it as the member's identity
    for consumer state: the label is generated once, stored, and must not change. A fresh UUID
    encoded as unpadded lowercase base32 yields 26 DNS-safe characters (a-z, 2-7), well inside
    the 63-octet label limit. Delete-and-re-add with a blank label therefore mints a new identity
    and resets consumer state, so a recreated membership does not silently resume prior state.
    """
    return base64.b32encode(uuid.uuid4().bytes).decode("ascii").rstrip("=").lower()


def prior_checks_ptr_record_creation(record):
    """Check if there is a matching reverse zone for this A/AAAA record's PTR record before creating it.

    Called from clean() so the failure surfaces before any DB write.
    """
    ptrdname = ipaddress_address(record.ip_address.host, "reverse_pointer")
    if DNSZone.find_reverse_zone_for_ptrdname(ptrdname, dns_view=record.zone.dns_view) is None:
        raise ValidationError(
            {
                "ip_address": (
                    f"Cannot auto-create PTR record: no matching reverse zone found "
                    f"in view '{record.zone.dns_view}' for {record.ip_address}."
                )
            }
        )


def create_auto_ptr_record(record):
    """Create a PTR record for the given A/AAAA record's IP address.

    Raises ValidationError if no matching reverse zone is found in the same DNS view.
    Skips creation silently if a PTR with the same owner name already exists in that reverse zone.
    """
    ptr_name = ipaddress_address(record.ip_address.host, "reverse_pointer")
    reverse_zone = DNSZone.find_reverse_zone_for_ptrdname(ptr_name, dns_view=record.zone.dns_view)
    if reverse_zone is None:
        raise ValidationError(
            {
                "ip_address": (
                    f"Cannot auto-create PTR record: no matching reverse zone found "
                    f"in view '{record.zone.dns_view}' for {record.ip_address}."
                )
            }
        )
    # RFC 1035 §3.5: PTR owner name is the reverse pointer, which is relative to the reverse zone.
    # As an example name is 20 and the whole fqdn `20.1.168.192.in-addr.arpa`
    relative_name = ptr_name.removesuffix(f".{reverse_zone.name}")
    # RFC 1035 §3.3.12: PTR RDATA (PTRDNAME) is the FQDN of the forward name.
    # Creating a PTR record for A record www in example.com, this should be `www.example.com`
    forward_fqdn = f"{record.name}.{record.zone.name}"
    if PTRRecord.objects.filter(name=relative_name, zone=reverse_zone).exists():
        return

    PTRRecord(name=relative_name, ptrdname=forward_fqdn, zone=reverse_zone).validated_save()


def dns_record_models():
    """Return every concrete DNSRecord subclass registered with Django.

    Discovered rather than hand-listed so that adding a record model cannot silently leave gaps,
    such as a catalog zone that stays undeletable because its records were never purged.
    """
    return [model for model in apps.get_models() if issubclass(model, DNSRecord)]


def ensure_catalog_zone_records(zone):
    """Write the records RFC 9432 requires in `zone`, and drop any that no longer belong.

    §4.1 notes that TTLs in a catalog zone carry no meaning, and the RFC sets them to zero
    throughout.

    Idempotent, so running it on every save of a zone or a membership repairs a catalog whose
    records drifted, rather than only populating a brand-new one. Does nothing for other zone types.
    """
    if zone.zone_type != DNSZoneTypeChoices.TYPE_CATALOG:
        return

    with system_write():
        _ensure_apex_ns_record(zone)
        _ensure_version_record(zone)
        _ensure_member_records(zone)


def _ensure_apex_ns_record(zone):
    """Hold the apex NS RRset RFC 9432 §4 requires at the single `invalid.` RR it recommends.

    Without it the zone a renderer builds from these records has no NS RRset, which is not a valid
    DNS zone and which an authoritative server will refuse to load.
    """
    ns_records = NSRecord.objects.filter(zone=zone)
    ns_records.exclude(name=APEX_RECORD_NAME, server=CATALOG_APEX_NS_SERVER).delete()
    if not ns_records.exists():
        NSRecord(name=APEX_RECORD_NAME, server=CATALOG_APEX_NS_SERVER, zone=zone, _ttl=0).validated_save()


def _ensure_version_record(zone):
    """Hold the schema version TXT at the single RR RFC 9432 §4.2.1 requires.

    2 is the only version the RFC defines, 1 having come from an earlier draft.
    """
    version_records = TXTRecord.objects.filter(name="version", zone=zone)
    # Per RFC 9432 §4.2.1, a second RR in the version RRset makes the whole catalog broken.
    version_records.exclude(text="2").delete()
    if not version_records.filter(text="2").exists():
        TXTRecord(name="version", text="2", zone=zone, _ttl=0).validated_save()


def _ensure_member_records(zone):
    """Rebuild the member PTR records from the catalog's memberships.

    RFC 9432 §4.1 publishes each member at `<label>.zones.$CATZ` as a PTR to the member zone name,
    and §4.1 again requires that RRset to hold exactly one RR. Reconciling the whole set is what
    lets a membership move or re-target without the caller having to know its previous owner name.
    """
    expected = {
        f"{membership.member_label}.zones": membership.member_zone.name
        for membership in zone.catalog_memberships.select_related("member_zone")
    }

    published = set()
    for record in PTRRecord.objects.filter(zone=zone):
        # Every PTR in a catalog zone is a member record, so one that matches no current membership
        # belongs to a membership that changed or went away. A repeated owner name is a second RR in
        # the RRset, which breaks the catalog outright.
        if record.name in published or expected.get(record.name) != record.ptrdname:
            record.delete()
        else:
            published.add(record.name)

    for name, ptrdname in expected.items():
        if name not in published:
            PTRRecord(name=name, ptrdname=ptrdname, zone=zone, _ttl=0).validated_save()


def reenroll_in_catalog(zone):
    """Withdraw `zone` from the catalog holding it and enroll it again.

    RFC 9432 does not define what to do when a member zone is renamed. We delete the
    membership and create another so the catalog withdraws the PTR at the old label and
    publishes the renamed zone at a new one, which a consumer processes as a removal
    and an addition (§5.4).

    Does nothing for a zone that is not enrolled. The new row is validated the same way
    any other enrollment is.
    """
    membership = zone.catalog_membership.first()
    if membership is None:
        return

    catalog_zone = membership.catalog_zone
    membership.delete()
    CatalogZoneMember(catalog_zone=catalog_zone, member_zone=zone).validated_save()


def purge_system_managed_records(zones):
    """Delete every record belonging to a catalog zone in `zones`, ahead of deleting the zones.

    `DNSRecord.zone` is PROTECT and catalog records refuse user deletes, so a catalog zone would
    otherwise be permanently undeletable. This cannot be a `pre_delete` receiver: Django raises
    ProtectedError while collecting related objects, which happens before any `pre_delete` is sent.
    """
    catalog_zone_pks = [zone.pk for zone in zones if zone.zone_type == DNSZoneTypeChoices.TYPE_CATALOG]
    if not catalog_zone_pks:
        return

    with system_write():
        for record_model in dns_record_models():
            record_model.objects.filter(zone_id__in=catalog_zone_pks).delete()


class DNSZoneQuerySet(RestrictedQuerySet):
    """QuerySet for DNSZone."""

    def delete(self):
        """Clear system-managed records first, so bulk zone deletion is not blocked by PROTECT."""
        purge_system_managed_records(self)
        return super().delete()


class DNSModel(PrimaryModel):
    """Abstract Model for Nautobot DNS Models."""

    #
    # name is effectively a NOOP here; it's overridden in both subclasses but
    # is here so that linters don't complain about it being used in clean().
    name = models.CharField(max_length=200)
    ttl = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)], default=3600, help_text="Time To Live."
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Whether this object is eligible for publication by external integrations.",
    )

    class Meta:
        """Meta class."""

        abstract = True

    def __str__(self):
        """Stringify instance."""
        return self.name  # pylint: disable=no-member

    @staticmethod
    def _validate_dns_label(label, field="name"):
        """
        Validate a DNS label for wire-format length using punycode encoding.

        Only checks for non-empty and length.
        """
        if not label:
            raise ValidationError({field: "Empty labels are not allowed"})
        length = dns_wire_label_length(label)
        if length > 63:
            raise ValidationError(
                {field: f"Label '{label}' exceeds the maximum length of 63 bytes (octets) in wire format."}
            )
        return length

    def clean(self):
        """
        Validate DNS label length and format per RFC 1035 §3.1 using punycode for wire-format length.

        Ensures each label in the name is ≤ 63 bytes (octets) in wire format and not empty.
        """
        super().clean()

        validation_level = getattr(constance_config, "nautobot_dns_models__DNS_VALIDATION_LEVEL")
        if validation_level == "wire-format":
            # Allow apex (empty) names; otherwise validate each non-empty label.
            if self.name != "":
                label_list = self.name.split(".")
                for label in label_list:
                    self._validate_dns_label(label, field="name")


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class DNSView(PrimaryModel):
    """Model for DNS Views."""

    name = models.CharField(max_length=200, help_text="Name of the View.", unique=True)
    description = models.TextField(help_text="Description of the View.", blank=True)
    prefixes = models.ManyToManyField(
        to="ipam.Prefix",
        related_name="dns_views",
        through="DNSViewPrefixAssignment",
        through_fields=("dns_view", "prefix"),
        blank=True,
        help_text="IP Prefixes that define the View.",
    )

    class Meta:
        """Meta attributes for DNSView."""

        verbose_name = "DNS View"
        verbose_name_plural = "DNS Views"

    def __str__(self):
        """Stringify instance."""
        return self.name


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class DNSRegistrar(PrimaryModel):
    """Model for DNS Registrars."""

    name = models.CharField(max_length=200, help_text="Name of the Registrar.", unique=True)
    url = models.URLField(max_length=500, blank=True, help_text="Registrar URL.")
    account_number = models.CharField(max_length=100, blank=True, help_text="Registrar account number.")

    class Meta:
        """Meta attributes for DNSRegistrar."""

        verbose_name = "DNS Registrar"
        verbose_name_plural = "DNS Registrars"

    def __str__(self):
        """Stringify instance."""
        return self.name


def get_default_view_pk():
    """Return the default DNSView ID, creating it if necessary."""
    default_view, _ = DNSView.objects.get_or_create(
        name="Default", defaults={"description": "Default DNS view. Created by Nautobot DNS Models app."}
    )
    return default_view.pk


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class DNSZone(DNSModel):
    """Model for DNS SOA Records. An SOA Record defines a DNS Zone."""

    name = models.CharField(max_length=200, help_text="FQDN of the Zone, w/ TLD. e.g example.com")
    zone_type = models.CharField(
        max_length=50,
        choices=DNSZoneTypeChoices,
        default=DNSZoneTypeChoices.TYPE_PRIMARY,
        help_text="Type of the Zone, determining which records it may contain. Cannot be changed after creation.",
        verbose_name="Zone Type",
    )
    dns_view = ForeignKeyWithAutoRelatedName(
        DNSView,
        on_delete=models.PROTECT,
        help_text="The DNS View this Zone belongs to.",
        verbose_name="View",
        default=get_default_view_pk,
    )
    ttl = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)],
        default=3600,
        help_text="Time To Live.",
        verbose_name="TTL",
    )
    filename = models.CharField(max_length=200, help_text="Filename of the Zone File.")
    description = models.TextField(help_text="Description of the Zone.", blank=True)
    soa_mname = models.CharField(
        max_length=200,
        help_text="FQDN of the Authoritative Name Server for Zone.",
        null=False,
        verbose_name="SOA MNAME",
    )
    soa_rname = models.CharField(
        max_length=254,
        help_text="Mailbox of the person responsible for the zone or a single-label placeholder.",
        verbose_name="SOA RNAME",
    )
    soa_refresh = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)],
        default=86400,
        help_text="Number of seconds after which secondary name servers should query the master for the SOA record, to detect zone changes.",
        verbose_name="SOA Refresh",
    )
    soa_retry = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)],
        default=7200,
        help_text="Number of seconds after which secondary name servers should retry to request the serial number from the master if the master does not respond.",
        verbose_name="SOA Retry",
    )
    soa_expire = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)],
        default=3600000,
        help_text="Number of seconds after which secondary name servers should stop answering request for this zone if the master does not respond. This value must be bigger than the sum of Refresh and Retry.",
        verbose_name="SOA Expire",
    )
    soa_serial = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)],
        default=0,
        help_text="Serial number of the zone. This value must be incremented each time the zone is changed, and secondary DNS servers must be able to retrieve this value to check if the zone has been updated.",
        verbose_name="SOA Serial",
    )
    soa_minimum = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)],
        default=3600,
        help_text="Minimum TTL for records in this zone.",
        verbose_name="SOA Minimum",
    )

    tenant = models.ForeignKey(
        to="tenancy.Tenant",
        on_delete=models.PROTECT,
        related_name="dns_zones",
        blank=True,
        null=True,
    )
    auto_create_ptr = models.BooleanField(
        default=False,
        help_text="Automatically create PTR records when A/AAAA records are created in this zone.",
        verbose_name="Auto-create PTR Records",
    )
    catalogs = models.ManyToManyField(
        to="self",
        through="CatalogZoneMember",
        through_fields=("member_zone", "catalog_zone"),
        symmetrical=False,
        related_name="members",
        blank=True,
    )

    objects = BaseManager.from_queryset(DNSZoneQuerySet)()

    class Meta:
        """Meta attributes for DNSZone."""

        constraints = [
            models.CheckConstraint(
                condition=~Q(zone_type=DNSZoneTypeChoices.TYPE_CATALOG) | Q(auto_create_ptr=False),
                name="catalog_zone_no_auto_create_ptr",
                violation_error_message="Catalog zones cannot enable automatic PTR creation.",
                violation_error_code="catalog_zone_auto_create_ptr",
            ),
        ]
        unique_together = [["name", "dns_view"]]
        verbose_name = "DNS Zone"
        verbose_name_plural = "DNS Zones"

    def __str__(self):
        """Stringify instance."""
        return f"{self.name} ({self.dns_view})"

    def clean(self):
        """Normalize the SOA RNAME, keep zone_type immutable, and bar catalog zones from auto-creating PTRs."""
        super().clean()

        invalid_rname_message = (
            "SOA RNAME must be a valid email address, a basic DNS-style mailbox with a fully qualified domain, "
            "or a single-label placeholder."
        )
        normalized_soa_rname = normalize_soa_rname(self.soa_rname)
        if "@" in normalized_soa_rname:
            try:
                validate_email(normalized_soa_rname)
            except ValidationError as exc:
                raise ValidationError({"soa_rname": invalid_rname_message}) from exc
        else:
            if not normalized_soa_rname or "." in normalized_soa_rname or "\\" in normalized_soa_rname:
                raise ValidationError({"soa_rname": invalid_rname_message})
            self._validate_dns_label(normalized_soa_rname, field="soa_rname")

        # Keep the in-memory instance canonical for callers of clean() or full_clean()
        # that do not immediately save it.
        self.soa_rname = normalized_soa_rname

        if self.present_in_database:
            stored_zone_type = DNSZone.objects.filter(pk=self.pk).values_list("zone_type", flat=True).first()
            if stored_zone_type is not None and stored_zone_type != self.zone_type:
                raise ValidationError(
                    {
                        "zone_type": (
                            "Zone type cannot be changed after creation. "
                            "Delete this zone and recreate it with the desired type."
                        )
                    }
                )

        # A catalog zone permits no A/AAAA records, so the flag could never fire; reject it rather than
        # silently coercing, so API callers learn the value was refused.
        if self.zone_type == DNSZoneTypeChoices.TYPE_CATALOG and self.auto_create_ptr:
            raise ValidationError({"auto_create_ptr": "Catalog zones cannot enable automatic PTR creation."})

    def delete(self, *args, **kwargs):
        """Clear system-managed records first, so a catalog zone is not held open by its own records."""
        purge_system_managed_records([self])
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        """Normalize the RNAME, then write the records this zone's type requires, repairing them if lost.

        Atomic because a catalog zone missing its version record is broken (RFC 9432 §4.2.1) and
        loses its catalog meaning altogether (§5.1), so a zone whose required records cannot be
        written should not be left behind at all.

        Renaming a zone withdraws it from the catalog holding it and publishes it afresh, rather
        than carrying its catalog identity across, which is why the stored name is read first.
        """
        self.soa_rname = normalize_soa_rname(self.soa_rname)
        stored_name = (
            DNSZone.objects.filter(pk=self.pk).values_list("name", flat=True).first()
            if self.present_in_database
            else None
        )

        with transaction.atomic():
            super().save(*args, **kwargs)
            ensure_catalog_zone_records(self)
            # After the save, so that re-enrollment publishes the new name.
            if stored_name is not None and stored_name != self.name:
                reenroll_in_catalog(self)

    def supports_record_type(self, record_model):
        """Return whether a user may create `record_model` records in this zone."""
        return zone_type_allows(self.zone_type, record_model)

    def supports_user_records(self):
        """Return whether this zone permits users to manage any record types."""
        return zone_type_allows_user_records(self.zone_type)

    @property
    def catalog(self):
        """Return the catalog zone this zone is enrolled in, or None if it is not enrolled.

        A unique constraint holds a zone to one membership, but `member_zone` is a ForeignKey rather
        than a OneToOneField, so the reverse accessor is still a manager. Reading it with a bare
        `all()` is what lets a caller serializing many zones pay for this once: narrowing the manager
        builds a fresh queryset, which ignores any `prefetch_related("catalog_membership__catalog_zone")`
        and goes back to the database per zone.
        """
        if self.is_catalog_zone:
            return None

        membership = next(iter(self.catalog_membership.all()), None)  # pylint: disable=no-member
        return membership.catalog_zone if membership else None

    @property
    def is_catalog_zone(self):
        """Return whether this zone is an RFC 9432 catalog zone."""
        return self.zone_type == DNSZoneTypeChoices.TYPE_CATALOG

    @classmethod
    def find_reverse_zone_for_ptrdname(cls, ptrdname, dns_view=None):
        """Return the most-specific reverse DNSZone whose name matches a tail of `ptrdname`, otherwise None."""
        permitted_zone_types = [
            zone_type for zone_type in ZONE_TYPE_USER_RECORDS if zone_type_allows(zone_type, PTRRecord)
        ]
        labels = ptrdname.split(".")
        for i in range(1, len(labels)):
            zone_name = ".".join(labels[i:])
            # We shouldn't match those cause are reserved to IANA
            if zone_name in RESERVED_ROOTS:
                break

            zones = cls.objects.filter(name=zone_name, zone_type__in=permitted_zone_types)
            if dns_view is not None:
                zones = zones.filter(dns_view=dns_view)
            zone = zones.first()
            if zone:
                return zone
        return None


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "statuses",
    "webhooks",
)
class DNSRegistration(PrimaryModel):
    """Model representing the registration of a DNS zone with a registrar."""

    dns_registrar = ForeignKeyWithAutoRelatedName(
        DNSRegistrar,
        on_delete=models.PROTECT,
        help_text="Registrar used for this zone registration.",
        verbose_name="Registrar",
    )
    dns_zone = ForeignKeyWithAutoRelatedName(
        DNSZone,
        on_delete=models.PROTECT,
        help_text="Zone that is registered.",
        verbose_name="Zone",
    )
    status = StatusField(
        null=False,
        on_delete=models.PROTECT,
        help_text="Status of the DNS registration.",
        to="extras.status",
    )
    expiration_date = models.DateField(null=True, blank=True, help_text="Domain expiration date.")
    auto_renewal = models.BooleanField(default=False, help_text="Whether auto renewal is enabled.")
    registry_locked = models.BooleanField(default=False, help_text="Whether registry lock is enabled.")
    transfer_locked = models.BooleanField(default=False, help_text="Whether transfer lock is enabled.")
    privacy_enabled = models.BooleanField(default=False, help_text="Whether privacy protection is enabled.")
    website_forwarding_enabled = models.BooleanField(default=False, help_text="Whether website forwarding is enabled.")
    renewal_term_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1200)],
        help_text="Renewal term in months.",
    )
    dnssec_enabled = models.BooleanField(
        default=False, help_text="Whether DNSSEC is enabled.", verbose_name="DNSSEC Enabled"
    )

    class Meta:
        """Meta attributes for DNSRegistration."""

        unique_together = [["dns_registrar", "dns_zone"]]
        verbose_name = "DNS Registration"
        verbose_name_plural = "DNS Registrations"

    def __str__(self):
        """Stringify instance."""
        return f"{self.dns_zone} @ {self.dns_registrar}"

    def clean(self):
        """Ensure registration is not against a catalog zone."""
        super().clean()

        if self.dns_zone_id and self.dns_zone.is_catalog_zone:
            raise ValidationError({"dns_zone": "Catalog zones cannot be registered."})


@extras_features("graphql")
class DNSViewPrefixAssignment(BaseModel):
    """Through model for DNSView and Prefix many-to-many relationship."""

    dns_view = ForeignKeyWithAutoRelatedName(
        DNSView,
        on_delete=models.CASCADE,
    )
    prefix = ForeignKeyWithAutoRelatedName(to="ipam.Prefix", on_delete=models.CASCADE)

    class Meta:
        """Meta attributes for DNSViewPrefixAssignment."""

        unique_together = [["dns_view", "prefix"]]
        verbose_name = "DNS View Prefix Assignment"
        verbose_name_plural = "DNS View Prefix Assignments"

    def __str__(self):
        """Stringify instance."""
        return f"{self.dns_view}: {self.prefix}"


@extras_features("graphql")
class CatalogZoneMember(BaseModel):
    """Through model for the `DNSZone.catalogs` relation, enrolling a zone in an RFC 9432 catalog.

    Not an object in its own right: enrollment is a property of the zone, and the change records
    for it are written against the two zones by core's M2M side-object logging. The PTR record that
    publishes the membership to consumers is derived from this row rather than managed directly.
    """

    catalog_zone = ForeignKeyWithAutoRelatedName(
        DNSZone,
        on_delete=models.PROTECT,
        related_name="catalog_memberships",
        help_text="The catalog zone publishing this membership.",
        verbose_name="Catalog Zone",
    )
    member_zone = ForeignKeyWithAutoRelatedName(
        DNSZone,
        on_delete=models.CASCADE,
        related_name="catalog_membership",
        help_text="The zone published by the catalog zone.",
        verbose_name="Member Zone",
    )
    member_label = models.CharField(
        max_length=63,
        blank=True,
        # A default as well as the fill-in in `save()`: rows written by `DNSZone.catalogs.add()` are
        # bulk-created, so they never reach `save()`, and two blank labels in one catalog collide.
        default=catalog_member_label,
        help_text=(
            "Opaque DNS label identifying this member within the catalog zone. "
            "Generated automatically if left blank, and not editable afterwards. "
        ),
        verbose_name="Member Label",
    )

    class Meta:
        """Meta attributes for CatalogZoneMember."""

        constraints = [
            # A member zone belongs to at most one catalog, which also makes the
            # (catalog_zone, member_zone) pair unique without a second constraint.
            models.UniqueConstraint(
                fields=["member_zone"],
                name="catalog_zone_member_unique_member_zone",
                violation_error_message="This zone already belongs to a catalog zone.",
            ),
            models.UniqueConstraint(
                fields=["catalog_zone", "member_label"],
                name="catalog_zone_member_unique_label",
                violation_error_message="This label is already used by another member of the catalog zone.",
            ),
        ]
        ordering = ["catalog_zone", "member_label"]
        verbose_name = "Catalog Zone Member"
        verbose_name_plural = "Catalog Zone Members"

    def __str__(self):
        """Stringify instance."""
        return f"{self.member_zone.name} in {self.catalog_zone.name}"

    def clean(self):
        """Reject memberships the RFC or this app's data model cannot represent."""
        super().clean()

        self._ensure_member_label()

        if self.catalog_zone_id and self.catalog_zone_id == self.member_zone_id:
            raise ValidationError({"member_zone": "A zone cannot be a member of itself."})

        if self.catalog_zone_id and self.catalog_zone.zone_type != DNSZoneTypeChoices.TYPE_CATALOG:  # pylint: disable=no-member
            raise ValidationError({"catalog_zone": "Members can only be added to a catalog zone."})

        # While RFC 9432 says nothing about nesting, consumer support for it is the exception. Not supported
        # at this time.
        if self.member_zone_id and self.member_zone.zone_type == DNSZoneTypeChoices.TYPE_CATALOG:  # pylint: disable=no-member
            raise ValidationError({"member_zone": "A catalog zone cannot be a member of another catalog zone."})

        if (
            self.catalog_zone_id
            and self.member_zone_id
            and self.catalog_zone.dns_view_id != self.member_zone.dns_view_id
        ):
            raise ValidationError({"member_zone": "The member zone must be in the same view as the catalog zone."})

        self._validate_member_label()

    def save(self, *args, **kwargs):
        """Generate the label if needed, then bring the catalog's member records back into line.

        Atomic for the reason `DNSZone.save()` is: a membership whose PTR cannot be written would
        leave the catalog claiming something other than what Nautobot holds.

        The label is reminted here rather than in `clean()`, which refuses a label that differs from
        the stored one and would reject this change as though a user had made it.
        """
        stored = (
            CatalogZoneMember.objects.filter(pk=self.pk).values("catalog_zone_id", "member_zone_id").first()
            if self.present_in_database
            else None
        )
        previous_catalog_zone_id = stored["catalog_zone_id"] if stored else None
        previous_member_zone_id = stored["member_zone_id"] if stored else None

        # Pointing the membership at another zone hands it the identity the previous one was
        # published under, which a consumer would read as that zone carrying on under a new name.
        if previous_member_zone_id is not None and previous_member_zone_id != self.member_zone_id:
            self.member_label = catalog_member_label()
        self._ensure_member_label()

        with transaction.atomic():
            super().save(*args, **kwargs)
            ensure_catalog_zone_records(self.catalog_zone)
            # Moving a membership to another catalog leaves a PTR behind in the one it came from.
            if previous_catalog_zone_id and previous_catalog_zone_id != self.catalog_zone_id:
                ensure_catalog_zone_records(DNSZone.objects.get(pk=previous_catalog_zone_id))

    def _ensure_member_label(self):
        """Fill in the generated label, leaving one the caller supplied alone."""
        if not self.member_label and self.member_zone_id:
            self.member_label = catalog_member_label()

    def _validate_member_label(self):
        """Require the label to be exactly one DNS label, since it names a single node in the catalog."""
        if not self.member_label:
            # Only reachable when member_zone is unset, which reports its own error; adding a second
            # complaint about a field the user deliberately left blank would only mislead.
            return

        if "." in self.member_label:
            raise ValidationError({"member_label": "The member label must be a single DNS label, without dots."})

        if dns_wire_label_length(self.member_label) > 63:
            raise ValidationError(
                {"member_label": "The member label exceeds the maximum length of 63 bytes (octets) in wire format."}
            )

        if self.present_in_database:
            stored_label = CatalogZoneMember.objects.filter(pk=self.pk).values_list("member_label", flat=True).first()
            if stored_label is not None and stored_label != self.member_label:
                raise ValidationError(
                    {
                        "member_label": (
                            "The member label cannot be changed. A consumer treats a new label as a "
                            "removal and re-addition of the member zone, discarding its state."
                        )
                    }
                )


class DNSRecordQuerySet(RestrictedQuerySet):
    """QuerySet shared by every concrete DNSRecord subclass."""

    def delete(self):
        """Refuse to delete system-managed records.

        Overridden here as well as on the model because Nautobot's bulk delete job calls
        `QuerySet.delete()` directly and never reaches `Model.delete()`. Neither guard can be a
        `pre_delete` receiver: that signal fires inside the collector's atomic block, so raising
        from it leaves the request transaction unusable and the caller sees a 500 instead of the
        error.
        """
        if not system_write_in_progress():
            # A zone type absent from the registry allows nothing, so leaving it out of this list
            # correctly protects its records.
            permitted_zone_types = [
                zone_type for zone_type in ZONE_TYPE_USER_RECORDS if zone_type_allows(zone_type, self.model)
            ]
            protected = self.exclude(zone__zone_type__in=permitted_zone_types)
            if protected.exists():
                raise ProtectedError(SYSTEM_MANAGED_DELETE_ERROR, list(protected[:50]))

        return super().delete()


class DNSRecord(DNSModel):
    """Primary Dns Record model for plugin."""

    name = models.CharField(max_length=200, help_text="FQDN of the Record, w/o TLD.")
    zone = ForeignKeyWithAutoRelatedName(DNSZone, on_delete=models.PROTECT)
    _ttl = models.PositiveBigIntegerField(
        validators=[MaxValueValidator(UINT32_MAX)],
        help_text="Time To Live (if no value is given, the Zone TTL will be used).",
        blank=True,
        null=True,
        verbose_name="TTL",
    )
    description = models.TextField(help_text="Description of the Record.", blank=True)
    comment = models.CharField(max_length=200, help_text="Comment for the Record.", blank=True)

    objects = BaseManager.from_queryset(DNSRecordQuerySet)()

    def clean(self):
        """
        Extend base validation to check total DNS name wire format length per RFC 1035 §3.1 using punycode for wire-format length.

        In addition to label checks, ensures the full DNS name (record + zone) does not exceed 255 bytes (octets) in wire format.
        """
        # Normalize trailing-dot only when the record name is zone-qualified (e.g., "host.example.com.")
        if (
            isinstance(self.name, str)
            and self.name.endswith(".")
            and getattr(self, "zone", None)
            and getattr(self.zone, "name", None)
            and self.name.endswith(f"{self.zone.name}.")
        ):
            self.name = self.name[:-1]

        super().clean()

        if not hasattr(self, "zone"):
            raise ValidationError({"zone": "Zone is required"})

        self._validate_total_wire_length_if_enabled()
        self._enforce_cname_exclusivity_if_enabled()
        self._enforce_zone_type_allows_record()

    def delete(self, *args, **kwargs):
        """Refuse to delete a system-managed record."""
        if not system_write_in_progress() and not self.zone.supports_record_type(type(self)):
            raise ProtectedError(SYSTEM_MANAGED_DELETE_ERROR, [self])
        return super().delete(*args, **kwargs)

    def _validate_total_wire_length_if_enabled(self) -> None:
        """Validate full DNS name (record + zone) total wire-format length if wire-format validation is enabled."""
        validation_level = getattr(constance_config, "nautobot_dns_models__DNS_VALIDATION_LEVEL")
        if validation_level != "wire-format":
            return

        # An apex record contributes no labels of its own; the name is the zone's.
        record_label_list = [] if self.name in ("", APEX_RECORD_NAME) else self.name.split(".")
        zone_label_list = self.zone.name.split(".")

        wire_length = 0
        for label in record_label_list:
            wire_length += 1 + dns_wire_label_length(label)
        for label in zone_label_list:
            wire_length += 1 + dns_wire_label_length(label)
        wire_length += 1  # Final zero-length root label

        if wire_length > 255:
            raise ValidationError({"name": "Total length of DNS name cannot exceed 255 bytes (octets) in wire format."})

    def _enforce_cname_exclusivity_if_enabled(self) -> None:
        """Enforce mutual exclusivity between CNAME and other record types for exact (name, zone) matches."""
        enforce = getattr(constance_config, "nautobot_dns_models__CNAME_RESTRICTION_ENABLED", True)
        if not enforce or getattr(self, "name", None) is None or getattr(self, "zone_id", None) is None:
            return

        if isinstance(self, CNAMERecord):
            conflicting_models = (NSRecord, ARecord, AAAARecord, MXRecord, TXTRecord, PTRRecord, SRVRecord)
            for model in conflicting_models:
                if model.objects.filter(name=self.name, zone_id=self.zone_id).exists():
                    raise ValidationError(
                        {"name": "CNAME cannot co-exist with other records of the same name in this zone."}
                    )
        else:
            if CNAMERecord.objects.filter(name=self.name, zone_id=self.zone_id).exists():
                raise ValidationError({"name": "Record cannot co-exist with a CNAME of the same name in this zone."})

    def _enforce_zone_type_allows_record(self) -> None:
        """Reject a user write of a record type the zone's type does not make available to users."""
        if system_write_in_progress() or self.zone.supports_record_type(type(self)):  # pylint: disable=no-member
            return

        zone_type_label = self.zone.get_zone_type_display().lower()  # pylint: disable=no-member
        if ZONE_TYPE_USER_RECORDS.get(self.zone.zone_type, False) is False:  # pylint: disable=no-member
            message = (
                f"Records in a {zone_type_label} zone are system-managed and cannot be created or edited directly."
            )
        else:
            message = f"{self._meta.verbose_name_plural} are not permitted in a {zone_type_label} zone."
        raise ValidationError({"zone": message})

    class Meta:
        """Meta attributes for DnsRecord."""

        abstract = True

    @property
    def ttl(self):
        """Return the TTL value for the record."""
        if self._ttl is None:
            return self.zone.ttl  # pylint: disable=no-member
        return self._ttl

    @ttl.setter
    def ttl(self, value):
        """Set the TTL value for the record."""
        self._ttl = value


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class NSRecord(DNSRecord):
    """NS Record model."""

    server = models.CharField(max_length=200, help_text="FQDN of an authoritative Name Server.")

    class Meta:
        """Meta attributes for NSRecord."""

        unique_together = [["name", "server", "zone"]]
        verbose_name = "NS Record"
        verbose_name_plural = "NS Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class ARecord(DNSRecord):
    """A Record model."""

    ip_address = models.ForeignKey(
        to="ipam.IPAddress",
        on_delete=models.CASCADE,
        limit_choices_to={"ip_version": IPAddressVersionChoices.VERSION_4},
        help_text="IP address for the record.",
        verbose_name="IP Address",
    )

    class Meta:
        """Meta attributes for ARecord."""

        unique_together = [["name", "ip_address", "zone"]]
        verbose_name = "A Record"
        verbose_name_plural = "A Records"

    def clean(self):
        """Validate that the referenced IP address is IPv4.

        Guard against dereferencing the relation when it's unset to avoid
        RelatedObjectDoesNotExist during form/model validation.
        """
        super().clean()
        if self.ip_address_id is None:
            return
        if self.ip_address.ip_version != IPAddressVersionChoices.VERSION_4:
            raise ValidationError({"ip_address": "ARecord must reference an IPv4 address."})
        if self._state.adding and self.zone.auto_create_ptr:  # pylint: disable=no-member
            prior_checks_ptr_record_creation(self)

    def save(self, *args, **kwargs):
        """Validate, save, and auto-create a PTR if the forward zone has auto_create_ptr enabled."""
        is_new = self._state.adding
        self.clean()
        super().save(*args, **kwargs)
        if is_new and self.zone.auto_create_ptr:  # pylint: disable=no-member
            create_auto_ptr_record(self)


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class AAAARecord(DNSRecord):
    """AAAA Record model."""

    ip_address = models.ForeignKey(
        to="ipam.IPAddress",
        on_delete=models.CASCADE,
        limit_choices_to={"ip_version": IPAddressVersionChoices.VERSION_6},
        help_text="IP address for the record.",
        verbose_name="IP Address",
    )

    class Meta:
        """Meta attributes for AAAARecord."""

        unique_together = [["name", "ip_address", "zone"]]
        verbose_name = "AAAA Record"
        verbose_name_plural = "AAAA Records"

    def clean(self):
        """Validate that the referenced IP address is IPv6.

        Guard against dereferencing the relation when it's unset to avoid
        RelatedObjectDoesNotExist during form/model validation.
        """
        super().clean()
        if self.ip_address_id is None:
            return
        if self.ip_address.ip_version != IPAddressVersionChoices.VERSION_6:
            raise ValidationError({"ip_address": "AAAARecord must reference an IPv6 address."})
        if self._state.adding and self.zone.auto_create_ptr:  # pylint: disable=no-member
            prior_checks_ptr_record_creation(self)

    def save(self, *args, **kwargs):
        """Validate, save, and auto-create a PTR if the forward zone has auto_create_ptr enabled."""
        is_new = self._state.adding
        self.clean()
        super().save(*args, **kwargs)
        if is_new and self.zone.auto_create_ptr:  # pylint: disable=no-member
            create_auto_ptr_record(self)


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class CNAMERecord(DNSRecord):
    """CNAME Record model."""

    alias = models.CharField(max_length=200, help_text="FQDN of the Alias.")

    class Meta:
        """Meta attributes for CNAMERecord."""

        unique_together = [["name", "alias", "zone"]]
        verbose_name = "CNAME Record"
        verbose_name_plural = "CNAME Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class MXRecord(DNSRecord):
    """MX Record model."""

    preference = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(65535)],
        default=10,
        help_text="Preference for the MX Record.",
    )
    mail_server = models.CharField(max_length=200, help_text="FQDN of the Mail Server.")

    class Meta:
        """Meta attributes for MXRecord."""

        unique_together = [["name", "mail_server", "zone"]]
        verbose_name = "MX Record"
        verbose_name_plural = "MX Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class TXTRecord(DNSRecord):
    """TXT Record model."""

    text = models.CharField(max_length=256, help_text="Text for the TXT Record.")

    class Meta:
        """Meta attributes for TXTRecord."""

        unique_together = [["name", "text", "zone"]]
        verbose_name = "TXT Record"
        verbose_name_plural = "TXT Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class PTRRecord(DNSRecord):
    """PTR Record model."""

    ptrdname = models.CharField(
        max_length=200, help_text="A domain name that points to some location in the domain name space."
    )

    class Meta:
        """Meta attributes for PTRRecord."""

        unique_together = [["name", "ptrdname", "zone"]]
        verbose_name = "PTR Record"
        verbose_name_plural = "PTR Records"

    def __str__(self):
        """String representation of PTRRecord."""
        return self.ptrdname


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class SRVRecord(DNSRecord):
    """SRV Record model."""

    priority = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(65535)],
        default=0,
        help_text="Priority of the SRV record.",
    )
    weight = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(65535)],
        default=0,
        help_text="Weight of the SRV record.",
    )
    port = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(65535)],
        help_text="Port number of the service.",
    )
    target = models.CharField(
        max_length=200,
        help_text="FQDN of the target host providing the service.",
    )

    class Meta:
        """Meta attributes for SRVRecord."""

        unique_together = [["name", "target", "port", "zone"]]
        verbose_name = "SRV Record"
        verbose_name_plural = "SRV Records"
