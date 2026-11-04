"""Models for Nautobot DNS Models."""

# pylint: disable=too-many-lines

import base64
import hashlib
import uuid

from constance import config as constance_config
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, validate_email
from django.db import models, transaction
from django.db.models import ProtectedError, Q
from django.db.models.functions import Lower
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

# RFC 9432 §4.1: TTLs in a catalog zone carry no meaning, and the RFC sets them to zero.
CATALOG_RECORD_TTL = 0

# RFC 1035 §3.3 defines <character-string> as a single length octet followed by up to 255 octets.
TXT_CHARACTER_STRING_MAX_OCTETS = 255
# RFC 1035 §3.3.14 defines TXT RDATA as one or more <character-string>; RFC 1035 §4.1.3 bounds the
# whole RDATA by the 16-bit RDLENGTH field, counting the length octet that prefixes each string.
TXT_RDATA_MAX_OCTETS = 2**16 - 1


def dns_wire_label_length(label):
    """Return the wire-format (IDNA/Punycode) length of a DNS label."""
    if label.isascii():
        return len(label)

    return len("xn--" + label.encode("punycode").decode("ascii"))


def _decode_txt_escapes(value, field="text"):
    r"""Decode a quoted <character-string> into the octets it represents on the wire.

    `\DDD` becomes the single octet DDD and `\X` becomes X (RFC 1035 §5.1). Other characters become their UTF-8
    bytes. Building bytes rather than a string keeps an escaped octet above 127 at one octet: as a string it would
    be a Unicode character that encodes to two.
    """
    decoded = bytearray()
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\":
            decoded.extend(character.encode("utf-8"))
            index += 1
            continue

        escape = value[index + 1 : index + 4]
        if len(escape) == 3 and escape.isdigit():
            octet = int(escape)
            if octet > 255:
                raise ValidationError({field: rf"Invalid escape '\{escape}': decimal escapes must be 0-255."})
            decoded.append(octet)
            index += 4
            continue

        if index + 1 >= len(value):
            raise ValidationError({field: "Invalid trailing backslash in quoted character-string."})
        decoded.extend(value[index + 1].encode("utf-8"))
        index += 2

    return bytes(decoded)


def _parse_quoted_txt_character_strings(value, field="text"):
    """Parse whitespace-separated, double-quoted <character-string> values per RFC 1035 §5.1."""
    character_string_list = []
    index = 0
    length = len(value)
    while index < length:
        if value[index].isspace():
            index += 1
            continue
        if value[index] != '"':
            raise ValidationError(
                {field: "Expected a double-quoted character-string; mixing quoted and unquoted text is not supported."}
            )

        index += 1
        start = index
        while index < length:
            if value[index] == "\\":
                index += 2
                continue
            if value[index] == '"':
                break
            index += 1

        if index >= length:
            raise ValidationError({field: "Unterminated quoted character-string."})

        character_string_list.append(_decode_txt_escapes(value[start:index], field=field))
        index += 1

    if not character_string_list:
        raise ValidationError({field: "No character-strings found."})

    return character_string_list


def _chunk_utf8_octets(value, max_octets):
    """Split a string into UTF-8 encoded chunks of at most `max_octets` bytes, never splitting a character."""
    chunk_list = []
    current = []
    current_octets = 0
    for character in value:
        character_octets = len(character.encode("utf-8"))
        if current_octets + character_octets > max_octets:
            chunk_list.append("".join(current))
            current = []
            current_octets = 0
        current.append(character)
        current_octets += character_octets

    if current:
        chunk_list.append("".join(current))

    return [chunk.encode("utf-8") for chunk in chunk_list]


def split_txt_character_strings(value, field="text"):
    r"""Return the TXT RDATA of `value` as a list of <character-string> values per RFC 1035 §3.3.14.

    Each value is `bytes`: the octets of that character-string on the wire, so `len()` is its wire length.

    A value that begins with a double quote is parsed as presentation-format: a whitespace-separated
    sequence of quoted character-strings, with `\DDD` and `\X` escapes decoded (RFC 1035 §5.1).
    This lets the author control where the wire-format boundaries fall, which matters for long DKIM
    keys. Any other value is treated as a single logical string and split into 255-octet chunks.
    """
    if value is None:
        return []

    if value.lstrip().startswith('"'):
        return _parse_quoted_txt_character_strings(value.strip(), field=field)

    if value == "":
        return [b""]

    return _chunk_utf8_octets(value, TXT_CHARACTER_STRING_MAX_OCTETS)


def txt_wire_rdata_length(character_string_list):
    """Return the wire-format TXT RDATA length: each <character-string> plus its length octet."""
    return sum(1 + len(character_string) for character_string in character_string_list)


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
    """Return every concrete DNSRecord subclass registered with Django."""
    return [model for model in apps.get_models() if issubclass(model, DNSRecord)]


def ensure_catalog_zone_records(zone):
    """Hold `zone`'s apex NS and `version` TXT records at what RFC 9432 requires of a catalog.

    Idempotent, so saving the zone repairs those two records rather than only populating a
    brand-new catalog.
    """
    if not zone.is_catalog_zone:
        return

    with system_write():
        _ensure_apex_ns_record(zone)
        _ensure_version_record(zone)


def _ensure_apex_ns_record(zone):
    """Hold the apex NS RRset RFC 9432 §4 requires at the single `invalid.` RR it recommends."""
    ns_records = NSRecord.objects.filter(zone=zone)
    ns_records.exclude(name=APEX_RECORD_NAME, server=CATALOG_APEX_NS_SERVER).delete()
    if not ns_records.exists():
        NSRecord(
            name=APEX_RECORD_NAME, server=CATALOG_APEX_NS_SERVER, zone=zone, _ttl=CATALOG_RECORD_TTL
        ).validated_save()


def _ensure_version_record(zone):
    """Hold the schema version TXT at the single RR RFC 9432 §4.2.1 requires."""
    version_records = TXTRecord.objects.filter(name="version", zone=zone)
    # "2" is the only version the RFC defines. A second RR in the version RRset makes the whole
    # catalog broken.
    version_records.exclude(text="2").delete()
    if not version_records.filter(text="2").exists():
        TXTRecord(name="version", text="2", zone=zone, _ttl=CATALOG_RECORD_TTL).validated_save()


def member_ptr_name(member_label):
    """Return the owner name a member is published at, relative to the catalog apex (RFC 9432 §4.1)."""
    return f"{member_label}.zones"


def publish_member_ptr_record(membership):
    """Publish the PTR record for the member zone in a catalog membership.

    RFC 9432 §4.1 allows only a single RR at that owner name, so anything else standing there gives way.
    """
    owner_name = membership.ptr_record_name
    ptrdname = membership.member_zone.name
    member_ptr_records = PTRRecord.objects.filter(name=owner_name, zone_id=membership.catalog_zone_id)

    with system_write():
        member_ptr_records.exclude(ptrdname=ptrdname).delete()
        if not member_ptr_records.filter(ptrdname=ptrdname).exists():
            PTRRecord(
                name=owner_name, ptrdname=ptrdname, zone=membership.catalog_zone, _ttl=CATALOG_RECORD_TTL
            ).validated_save()


def withdraw_member_ptr_record(catalog_zone_id, member_label):
    """Withdraw the PTR record for a catalog membership, named by the label it was published under.

    Takes a catalog and a label rather than a membership, so a caller that has already dropped
    the row can still name the record to withdraw.
    """
    with system_write():
        PTRRecord.objects.filter(name=member_ptr_name(member_label), zone_id=catalog_zone_id).delete()


def reenroll_in_catalog(zone):
    """Withdraw `zone` from the catalog holding it and enroll it again under a new member label.

    RFC 9432 does not define what to do when a member zone is renamed. The catalog withdraws the
    PTR at the old label and publishes one at the new label, which a consumer sees as a removal
    and an addition (RFC 9432 §5.4).
    """
    # Not `zone.catalog_memberships`, which answers from any prefetch made when the zone was loaded.
    membership = CatalogZoneMembership.objects.filter(member_zone_id=zone.pk).first()
    if membership is None:
        return

    catalog_zone_id = membership.catalog_zone_id
    _, deleted = membership.delete()
    # Removing a membership does not lock its zones, so another writer may have removed it since
    # the query. Enrolling the zone again would undo that removal.
    if not deleted.get(CatalogZoneMembership._meta.label):
        return

    CatalogZoneMembership(catalog_zone_id=catalog_zone_id, member_zone_id=zone.pk).validated_save()


def purge_system_managed_records(zones):
    """Delete the system-managed records of the zones in `zones`, ahead of deleting the zones.

    Every record in a zone whose type is not in `USER_RECORD_ZONE_TYPES` is system-managed.
    `DNSRecord.zone` is PROTECT and those records refuse user deletes, so such a zone would
    otherwise be permanently undeletable.
    """
    managed_zone_pks = [zone.pk for zone in zones if zone.type not in DNSZoneTypeChoices.USER_RECORD_ZONE_TYPES]
    if not managed_zone_pks:
        return

    with system_write():
        for record_model in dns_record_models():
            record_model.objects.filter(zone_id__in=managed_zone_pks).delete()


class DNSZoneQuerySet(RestrictedQuerySet):
    """QuerySet for DNSZone."""

    def delete(self):
        """Clear system-managed records, then the zones.

        If the delete fails, the records are kept.
        """
        with transaction.atomic():
            # Nothing protects the records in the purge, but if the delete fails (e.g. due to
            # PROTECT from a membership), the records are restored.
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
    portal_url = models.URLField(
        max_length=500, blank=True, help_text="Registrar portal URL.", verbose_name="Portal URL"
    )
    account_number = models.CharField(max_length=100, blank=True, help_text="Registrar account number.")

    class Meta:
        """Meta attributes for DNSRegistrar."""

        verbose_name = "DNS Registrar"
        verbose_name_plural = "DNS Registrars"

    def __str__(self):
        """Stringify instance."""
        return self.name


def get_default_view():
    """Return the default DNSView instance, creating it if necessary."""
    default_view, _ = DNSView.objects.get_or_create(
        name="Default", defaults={"description": "Default DNS view. Created by Nautobot DNS Models app."}
    )
    return default_view


def get_default_view_pk():
    """Return the default DNSView ID, creating it if necessary."""
    return get_default_view().pk


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
    # Nothing calls this manager, but core's change logging for M2M through models depends on this
    # declaration, and the membership has no `to_objectchange`, so without it nothing would record an
    # enrollment in either zone's change log. It also backs GraphQL `members`, and the plural shape
    # leaves room for `coo` (RFC 9432 §4.3.1), which holds a member in its old and new catalog at once.
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
                self._validate_type_unchanged(stored["type"])
                if stored["dns_view_id"] != self.dns_view_id:
                    self._validate_view_change()

        if self.is_catalog_zone and self.auto_create_ptr:
            raise ValidationError({"auto_create_ptr": "Catalog zones cannot enable automatic PTR creation."})

    def delete(self, *args, **kwargs):
        """Clear system-managed records, then the zone.

        If the delete fails, the records are kept.
        """
        with transaction.atomic():
            # Nothing protects the records in the purge, but if the zone delete fails (e.g. due to
            # PROTECT from a membership), the records are restored.
            purge_system_managed_records([self])
            return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        """Normalize the RNAME, then write the records this zone's type requires, repairing them if lost.

        If those records cannot be written, the zone is not saved either.

        Renaming a zone withdraws it from its catalog and enrolls it again under a new member label,
        so consumers see a removal and an addition rather than a rename.
        """
        self.soa_rname = normalize_soa_rname(self.soa_rname)
        update_fields = kwargs.get("update_fields")
        renaming = update_fields is None or "name" in update_fields
        moving = update_fields is None or not {"dns_view", "dns_view_id"}.isdisjoint(update_fields)

        with transaction.atomic():
            stored = self._lock_stored_row() if self.present_in_database else None
            if stored is not None:
                self._validate_type_unchanged(stored["type"])
                if moving and stored["dns_view_id"] != self.dns_view_id:
                    self._validate_view_change()

            super().save(*args, **kwargs)
            ensure_catalog_zone_records(self)
            # After the save, so that re-enrolling publishes the new name.
            if renaming and stored is not None and stored["name"] != self.name:
                reenroll_in_catalog(self)

    @property
    def catalog(self):
        """Return the catalog zone this zone is enrolled in, or None if it is not enrolled.

        Answers from any `prefetch_related("catalog_memberships__catalog_zone")` rather than querying.
        """
        if self.is_catalog_zone:
            return None

        # `first()` reads the prefetch only because `CatalogZoneMembership` is ordered.
        membership = self.catalog_memberships.first()  # pylint: disable=no-member
        return membership.catalog_zone if membership else None

    @property
    def has_members(self):
        """Return whether any zone belongs to this catalog zone, which is False for other zone types.

        Answers from any `prefetch_related("member_memberships")` rather than querying.
        """
        return self.member_memberships.exists()  # pylint: disable=no-member

    @property
    def is_catalog_zone(self):
        """Return whether this zone is an RFC 9432 catalog zone."""
        return self.type == DNSZoneTypeChoices.TYPE_CATALOG

    @classmethod
    def find_reverse_zone_for_ptrdname(cls, ptrdname, dns_view=None):
        """Return the most-specific reverse DNSZone whose name matches a tail of `ptrdname`, otherwise None."""
        labels = ptrdname.split(".")
        for i in range(1, len(labels)):
            zone_name = ".".join(labels[i:])
            # We shouldn't match those cause are reserved to IANA
            if zone_name in RESERVED_ROOTS:
                break

            zones = cls.objects.filter(name=zone_name, type__in=DNSZoneTypeChoices.USER_RECORD_ZONE_TYPES)
            if dns_view is not None:
                zones = zones.filter(dns_view=dns_view)
            zone = zones.first()
            if zone:
                return zone
        return None

    def _lock_stored_row(self):
        """Return the stored values `save()` compares, holding the row until the transaction ends."""
        # Locked so that a membership being created, which locks this row to read its view, waits for
        # this save instead of slipping past the view check.
        return DNSZone.objects.select_for_update().filter(pk=self.pk).values("name", "type", "dns_view_id").first()

    def _validate_type_unchanged(self, stored_type):
        """Refuse a type that differs from the one already stored."""
        if stored_type != self.type:
            raise ValidationError({"type": "Zone type cannot be changed after creation."})

    def _validate_view_change(self):
        """Refuse a view change that would leave a catalog zone and a member of it in different views.

        A membership checks that its two zones share a view only when it is written, so a later
        move of either zone has to be refused here.
        """
        # Queried, not read from `catalog` or `has_members`, which answer from any prefetch.
        if self.is_catalog_zone:
            if CatalogZoneMembership.objects.filter(catalog_zone_id=self.pk).exists():
                raise ValidationError({"dns_view": "A catalog zone with members cannot be moved to another view."})
            return

        if CatalogZoneMembership.objects.filter(member_zone_id=self.pk).exists():
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


class CatalogZoneMembershipQuerySet(RestrictedQuerySet):
    """QuerySet for CatalogZoneMembership, validating the writes that would otherwise skip `save()`."""

    def bulk_create(self, objs, *args, **kwargs):
        """Validate and publish each row, unlike Django's `bulk_create`, which skips `save()`.

        `DNSZone.catalogs.add()` writes through this method, inside
        `transaction.atomic(savepoint=False)`, so an exception also stops the caller's own transaction.
        """
        objs = list(objs)
        with transaction.atomic():
            # Done here rather than in an m2m_changed handler because the signal handler
            # doesn't receive through_defaults and therefore doesn't get the member label.
            for obj in objs:
                obj.full_clean()

            created = super().bulk_create(objs, *args, **kwargs)
            for membership in created:
                publish_member_ptr_record(membership)

            return created

    def bulk_update(self, objs, fields, *args, **kwargs):
        """Refuse the immutable fields, which this would otherwise write without reaching `clean()`."""
        # Refused rather than repaired: republishing the PTR to match would imply the change was supported.
        if refused := sorted(set(fields) & {"catalog_zone", "member_zone", "member_label"}):
            raise ValidationError(f"These fields cannot be changed on an existing membership: {', '.join(refused)}.")

        return super().bulk_update(objs, fields, *args, **kwargs)


@extras_features("graphql")
class CatalogZoneMembership(BaseModel):
    """Through model for the `DNSZone.catalogs` relation, enrolling a zone in an RFC 9432 catalog.

    Saving a membership publishes the member's PTR record in the catalog, and deleting it withdraws
    the record.

    Give `member_zone_id`, not `member_zone`, when the zone was fetched with its memberships
    prefetched, or the zone's change log records the catalog it had before this row.
    """

    catalog_zone = ForeignKeyWithAutoRelatedName(
        DNSZone,
        on_delete=models.PROTECT,
        related_name="member_memberships",
        help_text="The catalog zone containing this member.",
        verbose_name="Catalog Zone",
    )
    member_zone = ForeignKeyWithAutoRelatedName(
        DNSZone,
        on_delete=models.CASCADE,
        related_name="catalog_memberships",
        help_text="The zone contained in the catalog zone.",
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

    objects = BaseManager.from_queryset(CatalogZoneMembershipQuerySet)()

    class Meta:
        """Meta attributes for CatalogZoneMembership."""

        constraints = [
            # Since `coo` (RFC 9432 §4.3.1) is not currently implemented, a member zone belongs to one catalog
            # at most, which makes the (catalog_zone, member_zone) pair unique without a second constraint.
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
            # RFC 4343 §3 compares labels without regard to case, but the constraint above may not,
            # which would publish two PTR records at one owner name where RFC 9432 §4.1 allows only one.
            models.UniqueConstraint(
                "catalog_zone",
                Lower("member_label"),
                name="catalog_zone_membership_unique_label_case_insensitive",
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
        self._validate_static_rules()

        if self.catalog_zone_id and self.member_zone_id:
            self._validate_same_view(self.catalog_zone.dns_view_id, self.member_zone.dns_view_id)

        self._validate_immutable_fields()

    def save(self, *args, **kwargs):
        """Fill in the member label, then write this membership's PTR record into the catalog."""
        self._ensure_member_label()
        self._validate_static_rules()

        with transaction.atomic():
            self._lock_and_validate_zones()
            self._validate_immutable_fields(lock=True)
            super().save(*args, **kwargs)
            publish_member_ptr_record(self)

    @property
    def ptr_record_name(self):
        """Return the owner name this member is published at, relative to the catalog apex (RFC 9432 §4.1)."""
        return member_ptr_name(self.member_label)

    def _ensure_member_label(self):
        """Fill in the generated label, leaving one the caller supplied alone."""
        if not self.member_label:
            self.member_label = catalog_member_label()

    def _validate_static_rules(self):
        """Refuse a membership the data model cannot represent, whatever else is committed."""
        if self.catalog_zone_id and self.catalog_zone_id == self.member_zone_id:
            raise ValidationError({"member_zone": "A zone cannot be a member of itself."})

        if self.catalog_zone_id and not self.catalog_zone.is_catalog_zone:  # pylint: disable=no-member
            raise ValidationError({"catalog_zone": "Members can only be added to a catalog zone."})

        # While RFC 9432 says nothing about nesting, consumer support for it is the exception. Not supported
        # at this time.
        if self.member_zone_id and self.member_zone.is_catalog_zone:  # pylint: disable=no-member
            raise ValidationError({"member_zone": "A catalog zone cannot be a member of another catalog zone."})

        self._validate_member_label()

    def _validate_member_label(self):
        """Require the label to be exactly one DNS label, since it names a single node in the catalog."""
        if "." in self.member_label:
            raise ValidationError({"member_label": "The member label must be a single DNS label, without dots."})

        if dns_wire_label_length(self.member_label) > 63:
            raise ValidationError(
                {"member_label": "The member label exceeds the maximum length of 63 bytes (octets) in wire format."}
            )

    @staticmethod
    def _validate_same_view(catalog_view_id, member_view_id):
        """Refuse a catalog and a member in different views, whichever read supplied the views."""
        if catalog_view_id != member_view_id:
            raise ValidationError({"member_zone": "The member zone must be in the same view as the catalog zone."})

    def _lock_and_validate_zones(self):
        """Lock both zone rows, then refuse a pair that no longer exists or no longer shares a view.

        A zone deleted since `clean()` is refused here with a `ValidationError`, rather than as an
        `IntegrityError` at commit.
        """
        if not self.catalog_zone_id or not self.member_zone_id:
            return

        # Lock the member zone before the catalog zone, the order a zone rename takes
        # them in; the reverse order can deadlock with a concurrent rename. One query
        # per zone, since MySQL does not guarantee that rows are locked in ORDER BY order.
        views = {}
        for zone_pk in (self.member_zone_id, self.catalog_zone_id):
            views.update(DNSZone.objects.select_for_update().filter(pk=zone_pk).values_list("pk", "dns_view_id"))

        errors = {}
        if self.catalog_zone_id not in views:
            errors["catalog_zone"] = "The catalog zone no longer exists."
        if self.member_zone_id not in views:
            errors["member_zone"] = "The member zone no longer exists."
        if errors:
            raise ValidationError(errors)

        self._validate_same_view(views[self.catalog_zone_id], views[self.member_zone_id])

    def _validate_immutable_fields(self, *, lock=False):
        """Refuse a changed catalog, member, or label, or a row another writer has deleted.

        Keyword Args:
            lock (bool): Lock the stored row for the comparison. Defaults to False.
        """
        if not self.present_in_database:
            return

        queryset = CatalogZoneMembership.objects
        if lock:
            queryset = queryset.select_for_update()

        stored = queryset.filter(pk=self.pk).values("catalog_zone_id", "member_zone_id", "member_label").first()
        if stored is None:
            raise ValidationError("This membership no longer exists.")

        errors = {}
        if self.catalog_zone_id != stored["catalog_zone_id"]:
            errors["catalog_zone"] = "The catalog zone cannot be changed on an existing membership."
        if self.member_zone_id != stored["member_zone_id"]:
            errors["member_zone"] = "The member zone cannot be changed on an existing membership."
        if self.member_label != stored["member_label"]:
            errors["member_label"] = "The member label cannot be changed on an existing membership."

        if errors:
            raise ValidationError(errors)


class DNSRecordQuerySet(RestrictedQuerySet):
    """QuerySet shared by every concrete DNSRecord subclass."""

    def delete(self):
        """Refuse to delete system-managed records, as `DNSRecord.delete()` does for one record."""
        # Nautobot's bulk delete job calls `QuerySet.delete()` directly, bypassing `DNSRecord.delete()`.
        if not system_write_in_progress():
            protected = self.exclude(zone__type__in=DNSZoneTypeChoices.USER_RECORD_ZONE_TYPES)
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
        if not system_write_in_progress() and self.zone.type not in DNSZoneTypeChoices.USER_RECORD_ZONE_TYPES:
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
        if system_write_in_progress() or self.zone.type in DNSZoneTypeChoices.USER_RECORD_ZONE_TYPES:  # pylint: disable=no-member
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
    mail_server = models.CharField(max_length=200, help_text="FQDN of the Mail server.")

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

    text = models.TextField(help_text="Text for the TXT Record.")
    # `text` cannot participate in a unique index directly: MySQL cannot index a TEXT column without a
    # prefix length (error 1170). The digest gives an equivalent, backend-portable uniqueness guarantee.
    # Named with a leading underscore so Nautobot's serializers omit it from the REST API, as with `_ttl`.
    _text_hash = models.CharField(
        max_length=64, editable=False, help_text="SHA-256 digest of `text`, used to enforce uniqueness."
    )

    # Reproduces the key Nautobot would otherwise derive from `unique_together[0]`, so that CSV
    # import/export and API natural-key lookups are unaffected by the digest column.
    natural_key_field_names = ["name", "text", "zone"]

    class Meta:
        """Meta attributes for TXTRecord."""

        unique_together = [["name", "zone", "_text_hash"]]
        verbose_name = "TXT Record"
        verbose_name_plural = "TXT Records"

    @staticmethod
    def hash_text(value):
        """Return the SHA-256 digest used to enforce `text` uniqueness."""
        return hashlib.sha256((value or "").encode("utf-8")).hexdigest()

    @property
    def character_strings(self):
        """Return `text` as the list of <character-string> values it represents on the wire, each as `bytes`."""
        return split_txt_character_strings(self.text)

    def clean(self):
        """Refresh the uniqueness digest.

        RFC 1035 §3.3.14 length rules are enforced by `TXTRecordRFC1035LengthRule` in `custom_validators.py`,
        which Nautobot's Data Validation Engine runs after this method.

        The digest must be set here rather than only in `save()`: `Model.full_clean()` runs `clean()`
        before `validate_unique()`, so a stale digest would make uniqueness checks compare empty
        values -- reporting duplicates that don't exist and missing the ones that do.
        """
        super().clean()

        self._text_hash = self.hash_text(self.text)

    def unique_error_message(self, model_class, unique_check):
        """Report the digest-based uniqueness violation in terms of `text` rather than `_text_hash`.

        Without this the default message names the internal field `_text_hash`.
        """
        if set(unique_check) == {"name", "zone", "_text_hash"}:
            return ValidationError(
                message="TXT Record with this Name, Zone and Text already exists.",
                code="unique_together",
            )
        return super().unique_error_message(model_class, unique_check)

    def save(self, *args, **kwargs):
        """Refresh the uniqueness digest before saving, for callers that bypass `clean()`."""
        self._text_hash = self.hash_text(self.text)
        # A caller updating only `text` would otherwise leave the digest behind in the database.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "text" in update_fields:
            kwargs["update_fields"] = list(update_fields) + ["_text_hash"]
        super().save(*args, **kwargs)


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
