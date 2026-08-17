"""Models for Nautobot DNS Models."""

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

# Zone apex per RFC 1035 §5.1.
APEX_RECORD_NAME = "@"

# RFC 9432 §4 requires an NS RRset in a catalog zone so that it is a syntactically valid zone, and
# recommends a single RR naming "invalid.". Stored without the trailing dot the RFC writes: a name
# server is an absolute domain name here, and the dot is presentation syntax rather than data.
CATALOG_APEX_NS_SERVER = "invalid"


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
    the 63-octet label limit.
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
    """Hold `zone`'s apex NS and `version` TXT records at what RFC 9432 requires of a catalog.

    §4.1 notes that TTLs in a catalog zone carry no meaning, and the RFC sets them to zero
    throughout.

    Idempotent, so saving the zone repairs those two records rather than only populating a
    brand-new catalog.
    """
    if not zone.is_catalog_zone:
        return

    with system_write():
        _ensure_apex_ns_record(zone)
        _ensure_version_record(zone)


def _ensure_apex_ns_record(zone):
    """Hold the apex NS RRset RFC 9432 §4 requires at the single `invalid.` RR it recommends.

    Without it these records describe a zone with no NS RRset, which is not a valid DNS zone and
    which no authoritative server will load.
    """
    ns_records = NSRecord.objects.filter(zone=zone)
    ns_records.exclude(name=APEX_RECORD_NAME, server=CATALOG_APEX_NS_SERVER).delete()
    if not ns_records.exists():
        NSRecord(name=APEX_RECORD_NAME, server=CATALOG_APEX_NS_SERVER, zone=zone, _ttl=0).validated_save()


def _ensure_version_record(zone):
    """Hold the schema version TXT at the single RR RFC 9432 §4.2.1 requires.

    2 is the only version the RFC defines.
    """
    version_records = TXTRecord.objects.filter(name="version", zone=zone)
    # Per RFC 9432 §4.2.1, a second RR in the version RRset makes the whole catalog broken.
    version_records.exclude(text="2").delete()
    if not version_records.filter(text="2").exists():
        TXTRecord(name="version", text="2", zone=zone, _ttl=0).validated_save()


def member_ptr_name(member_label):
    """Return the owner name a member is published at, relative to the catalog apex (RFC 9432 §4.1)."""
    return f"{member_label}.zones"


def publish_member_ptr_record(membership):
    """Publish the PTR record for the member zone in a catalog membership.

    RFC 9432 §4.1 allows only a single RR at that owner name, so anything else standing there gives way.
    """
    owner_name = member_ptr_name(membership.member_label)
    ptrdname = membership.member_zone.name
    member_ptr_records = PTRRecord.objects.filter(name=owner_name, zone_id=membership.catalog_zone_id)

    with system_write():
        member_ptr_records.exclude(ptrdname=ptrdname).delete()
        if not member_ptr_records.filter(ptrdname=ptrdname).exists():
            PTRRecord(name=owner_name, ptrdname=ptrdname, zone=membership.catalog_zone, _ttl=0).validated_save()


def withdraw_member_ptr_record(catalog_zone_id, member_label):
    """Withdraw the PTR record for a catalog membership, named by the label it was published under.

    Takes a catalog and a label rather than a membership, since the record a move or a reissued
    label leaves behind is the one the membership has stopped carrying.
    """
    with system_write():
        PTRRecord.objects.filter(name=member_ptr_name(member_label), zone_id=catalog_zone_id).delete()


def reenroll_in_catalog(zone):
    """Withdraw `zone` from the catalog holding it and enroll it again.

    RFC 9432 does not define what to do when a member zone is renamed. We delete the
    membership and create another so the catalog withdraws the PTR at the old label and
    publishes the renamed zone at a new one, which a consumer processes as a removal
    and an addition (§5.4).

    Does nothing for a zone that is not enrolled.
    """
    membership = zone.catalog_memberships.first()
    if membership is None:
        return

    catalog_zone = membership.catalog_zone
    membership.delete()
    CatalogZoneMembership(catalog_zone=catalog_zone, member_zone=zone).validated_save()


def purge_system_managed_records(zones):
    """Delete every record belonging to a catalog zone in `zones`, ahead of deleting the zones.

    `DNSRecord.zone` is PROTECT and catalog records refuse user deletes, so a catalog zone would
    otherwise be permanently undeletable. This cannot be a `pre_delete` receiver: Django raises
    ProtectedError while collecting related objects, which happens before any `pre_delete` is sent.
    """
    catalog_zone_pks = [zone.pk for zone in zones if zone.is_catalog_zone]
    if not catalog_zone_pks:
        return

    with system_write():
        for record_model in dns_record_models():
            record_model.objects.filter(zone_id__in=catalog_zone_pks).delete()


class DNSZoneQuerySet(RestrictedQuerySet):
    """QuerySet for DNSZone."""

    def delete(self):
        """Clear system-managed records first, so bulk zone deletion is not blocked by PROTECT.

        Atomic for the reason `DNSZone.delete()` is.
        """
        with transaction.atomic():
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
    "relationships",
    "webhooks",
)
class DNSZone(DNSModel):
    """Model for DNS SOA Records. An SOA Record defines a DNS Zone."""

    name = models.CharField(max_length=200, help_text="FQDN of the Zone, w/ TLD. e.g example.com")
    type = models.CharField(
        max_length=50,
        choices=DNSZoneTypeChoices,
        default=DNSZoneTypeChoices.TYPE_PRIMARY,
        help_text="Type of the Zone, determining which records it may contain. Cannot be changed after creation.",
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
        through="CatalogZoneMembership",
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
                condition=~Q(type=DNSZoneTypeChoices.TYPE_CATALOG) | Q(auto_create_ptr=False),
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
        """Normalize the SOA RNAME, keep type immutable, hold memberships to one view, and bar catalog PTR."""
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

        self.soa_rname = normalized_soa_rname

        if self.present_in_database:
            stored = DNSZone.objects.filter(pk=self.pk).values("type", "dns_view_id").first()
            if stored is not None:
                if stored["type"] != self.type:
                    raise ValidationError({"type": "Zone type cannot be changed after creation."})
                if stored["dns_view_id"] != self.dns_view_id:
                    self._validate_view_change()

        if self.is_catalog_zone and self.auto_create_ptr:
            raise ValidationError({"auto_create_ptr": "Catalog zones cannot enable automatic PTR creation."})

    def delete(self, *args, **kwargs):
        """Clear system-managed records first, so a catalog zone is not held open by its own records.

        Atomic because another relation can still refuse the delete, and a catalog stripped of the
        records it was cleared of is no longer a catalog (RFC 9432 §4.2.1). Not every caller opens a
        transaction of its own: the REST API deletes a single object in autocommit.
        """
        with transaction.atomic():
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
            # After the save, so that re-enrolling publishes the new name.
            if stored_name is not None and stored_name != self.name:
                reenroll_in_catalog(self)

    @classmethod
    def zone_type_allows_records(cls, zone_type):
        """Return whether users may manage records in a zone of `zone_type`."""
        return zone_type == DNSZoneTypeChoices.TYPE_PRIMARY

    @property
    def catalog(self):
        """Return the catalog zone this zone is enrolled in, or None if it is not enrolled.

        A unique constraint holds a zone to one membership, but the reverse accessor is still a
        manager. `first()` answers from any `prefetch_related("catalog_memberships__catalog_zone")`
        rather than querying, because `CatalogZoneMembership` is ordered.
        """
        if self.is_catalog_zone:
            return None

        membership = self.catalog_memberships.first()  # pylint: disable=no-member
        return membership.catalog_zone if membership else None

    @property
    def has_members(self):
        """Return whether any zone belongs to this catalog zone, which is False for other zone types.

        Unlike `catalog`, this queries on every read: `exists()` builds a fresh queryset, so a
        prefetch cache goes unused.
        """
        return self.member_memberships.exists()  # pylint: disable=no-member

    @property
    def is_catalog_zone(self):
        """Return whether this zone is an RFC 9432 catalog zone."""
        return self.type == DNSZoneTypeChoices.TYPE_CATALOG

    @classmethod
    def find_reverse_zone_for_ptrdname(cls, ptrdname, dns_view=None):
        """Return the most-specific reverse DNSZone whose name matches a tail of `ptrdname`, otherwise None."""
        permitted_zone_types = [
            zone_type for zone_type, _ in DNSZoneTypeChoices.CHOICES if cls.zone_type_allows_records(zone_type)
        ]
        labels = ptrdname.split(".")
        for i in range(1, len(labels)):
            zone_name = ".".join(labels[i:])
            # We shouldn't match those cause are reserved to IANA
            if zone_name in RESERVED_ROOTS:
                break

            zones = cls.objects.filter(name=zone_name, type__in=permitted_zone_types)
            if dns_view is not None:
                zones = zones.filter(dns_view=dns_view)
            zone = zones.first()
            if zone:
                return zone
        return None

    def _validate_view_change(self):
        """Refuse a view change that would leave a catalog zone and a member of it in different views.

        A membership checks that its two zones share a view only when it is written, so a later
        move of either zone has to be refused here. The zone's type decides which check applies,
        and it cannot change.
        """
        if self.is_catalog_zone:
            if self.has_members:
                raise ValidationError({"dns_view": "A catalog zone with members cannot be moved to another view."})
            return

        if self.catalog is not None:
            raise ValidationError(
                {"dns_view": "A zone that is a member of a catalog zone cannot be moved to another view."}
            )


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
class CatalogZoneMembership(BaseModel):
    """Through model for the `DNSZone.catalogs` relation, enrolling a zone in an RFC 9432 catalog.

    The PTR record that publishes the membership to consumers is derived from this row rather than
    managed directly.
    """

    catalog_zone = ForeignKeyWithAutoRelatedName(
        DNSZone,
        on_delete=models.PROTECT,
        related_name="member_memberships",
        help_text="The catalog zone publishing this membership.",
        verbose_name="Catalog Zone",
    )
    member_zone = ForeignKeyWithAutoRelatedName(
        DNSZone,
        on_delete=models.CASCADE,
        related_name="catalog_memberships",
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
        """Meta attributes for CatalogZoneMembership."""

        constraints = [
            # A member zone belongs to at most one catalog, which also makes the
            # (catalog_zone, member_zone) pair unique without a second constraint.
            models.UniqueConstraint(
                fields=["member_zone"],
                name="catalog_zone_membership_unique_member_zone",
                violation_error_message="This zone already belongs to a catalog zone.",
            ),
            models.UniqueConstraint(
                fields=["catalog_zone", "member_label"],
                name="catalog_zone_membership_unique_label",
                violation_error_message="This label is already used by another member of the catalog zone.",
            ),
        ]
        ordering = ["catalog_zone", "member_label"]
        verbose_name = "Catalog Zone Membership"
        verbose_name_plural = "Catalog Zone Memberships"

    def __str__(self):
        """Stringify instance."""
        return f"{self.member_zone.name} in {self.catalog_zone.name}"

    def clean(self):
        """Reject memberships the RFC or this app's data model cannot represent."""
        super().clean()

        self._ensure_member_label()

        if self.catalog_zone_id and self.catalog_zone_id == self.member_zone_id:
            raise ValidationError({"member_zone": "A zone cannot be a member of itself."})

        if self.catalog_zone_id and not self.catalog_zone.is_catalog_zone:
            raise ValidationError({"catalog_zone": "Members can only be added to a catalog zone."})

        # While RFC 9432 says nothing about nesting, consumer support for it is the exception. Not supported
        # at this time.
        if self.member_zone_id and self.member_zone.is_catalog_zone:
            raise ValidationError({"member_zone": "A catalog zone cannot be a member of another catalog zone."})

        if (
            self.catalog_zone_id
            and self.member_zone_id
            and self.catalog_zone.dns_view_id != self.member_zone.dns_view_id
        ):
            raise ValidationError({"member_zone": "The member zone must be in the same view as the catalog zone."})

        self._validate_member_label()

    def save(self, *args, **kwargs):
        """Fill in or reissue the member label, then publish this membership as a PTR record.

        Atomic: if writing a PTR fails, the membership must not be stored.

        `clean()` rejects any label that differs from the stored one, so a new label cannot be
        issued there and is generated here instead.
        """
        stored = (
            CatalogZoneMembership.objects.filter(pk=self.pk)
            .values("catalog_zone_id", "member_zone_id", "member_label")
            .first()
            if self.present_in_database
            else None
        )
        previous_catalog_zone_id = stored["catalog_zone_id"] if stored else None
        previous_member_zone_id = stored["member_zone_id"] if stored else None
        previous_label = stored["member_label"] if stored else None

        # Pointing the membership at another zone hands it the identity the previous one was
        # published under, which a consumer would read as that zone carrying on under a new name.
        if stored and previous_member_zone_id != self.member_zone_id:
            self.member_label = catalog_member_label()
        self._ensure_member_label()

        with transaction.atomic():
            super().save(*args, **kwargs)
            publish_member_ptr_record(self)
            # A move leaves a record behind in the catalog it came from, and a reissued label leaves
            # one at the label it was published under.
            if stored and (previous_catalog_zone_id, previous_label) != (self.catalog_zone_id, self.member_label):
                withdraw_member_ptr_record(previous_catalog_zone_id, previous_label)

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
            stored_label = (
                CatalogZoneMembership.objects.filter(pk=self.pk).values_list("member_label", flat=True).first()
            )
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
        `QuerySet.delete()` directly, bypassing `Model.delete()`. Neither guard can be a
        `pre_delete` receiver: that signal fires inside the collector's atomic block, where raising
        breaks the request transaction and the caller gets a 500 instead of the error.
        """
        if not system_write_in_progress():
            permitted_zone_types = [
                zone_type for zone_type, _ in DNSZoneTypeChoices.CHOICES if DNSZone.zone_type_allows_records(zone_type)
            ]
            protected = self.exclude(zone__type__in=permitted_zone_types)
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
        if not system_write_in_progress() and not DNSZone.zone_type_allows_records(self.zone.type):
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
        if system_write_in_progress() or DNSZone.zone_type_allows_records(self.zone.type):  # pylint: disable=no-member
            return

        zone_type_label = self.zone.get_type_display().lower()  # pylint: disable=no-member
        raise ValidationError(
            {
                "zone": (
                    f"Records in a {zone_type_label} zone are system-managed and cannot be created or edited directly."
                )
            }
        )

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
