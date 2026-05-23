"""Models for Nautobot DNS Models."""

import base64
import uuid

from constance import config as constance_config
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from nautobot.apps.models import BaseModel, PrimaryModel, extras_features
from nautobot.core.models.fields import ForeignKeyWithAutoRelatedName
from nautobot.extras.models import StatusField
from nautobot.ipam.choices import IPAddressVersionChoices

from nautobot_dns_models.querysets import CatalogZoneMembershipManager

CATALOG_ZONE_SCHEMA_VERSION = "2"
CATALOG_ZONE_VERSION_RECORD_NAME = "version"
CATALOG_ZONE_DEFAULT_NS_TARGET = "invalid."
CATALOG_MEMBER_NODE_LABEL_MAX_GENERATION_ATTEMPTS = 10
CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_ZONE_UNIQUE = "dns_czm_unique_member_zone_per_catalog"
CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_NODE_LABEL_UNIQUE = "dns_czm_unique_member_node_label_per_catalog"


class CatalogMemberNodeLabelGenerationError(Exception):
    """Raised when a unique catalog member node label cannot be generated."""


class CatalogZoneMembershipAlreadyExistsError(Exception):
    """Raised when creating a duplicate member zone entry in the same catalog."""


def generate_catalog_member_node_label():
    """Generate an RFC-safe opaque label from random UUIDv4 bytes."""
    # UUIDv4 keeps labels opaque and stable, decoupled from zone names.
    return base64.b32encode(uuid.uuid4().bytes).decode("ascii").lower().rstrip("=")


def dns_wire_label_length(label):
    """Return the wire-format (IDNA/Punycode) length of a DNS label."""
    if label.isascii():
        return len(label)

    return len("xn--" + label.encode("punycode").decode("ascii"))


class DNSModel(PrimaryModel):
    """Abstract Model for Nautobot DNS Models."""

    #
    # name is effectively a NOOP here; it's overridden in both subclasses but
    # is here so that linters don't complain about it being used in clean().
    name = models.CharField(max_length=200)
    ttl = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)], default=3600, help_text="Time To Live."
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
    dns_view = ForeignKeyWithAutoRelatedName(
        DNSView,
        on_delete=models.PROTECT,
        help_text="The DNS View this Zone belongs to.",
        verbose_name="View",
        default=get_default_view_pk,
    )
    ttl = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
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
    soa_rname = models.EmailField(help_text="Admin Email for the Zone in the form", verbose_name="SOA RNAME")
    soa_refresh = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=86400,
        help_text="Number of seconds after which secondary name servers should query the master for the SOA record, to detect zone changes.",
        verbose_name="SOA Refresh",
    )
    soa_retry = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=7200,
        help_text="Number of seconds after which secondary name servers should retry to request the serial number from the master if the master does not respond.",
        verbose_name="SOA Retry",
    )
    soa_expire = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=3600000,
        help_text="Number of seconds after which secondary name servers should stop answering request for this zone if the master does not respond. This value must be bigger than the sum of Refresh and Retry.",
        verbose_name="SOA Expire",
    )
    soa_serial = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(2147483647)],
        default=0,
        help_text="Serial number of the zone. This value must be incremented each time the zone is changed, and secondary DNS servers must be able to retrieve this value to check if the zone has been updated.",
        verbose_name="SOA Serial",
    )
    soa_minimum = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
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

    class Meta:
        """Meta attributes for DNSZone."""

        unique_together = [["name", "dns_view"]]
        verbose_name = "DNS Zone"
        verbose_name_plural = "DNS Zones"

    @property
    def backing_catalog_zone(self):
        """Return the catalog zone wrapper backed by this DNS zone, if any."""
        try:
            return self.catalog_zone
        except CatalogZone.DoesNotExist:
            return None

    @property
    def member_catalog_zone(self):
        """Return the catalog zone this DNS zone is a member of, if any."""
        membership = self.catalog_zone_memberships.select_related("catalog_zone").first()
        return membership.catalog_zone if membership else None


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class CatalogZone(PrimaryModel):
    """Wrapper model identifying a DNSZone as a catalog zone."""

    dns_zone = models.OneToOneField(
        to=DNSZone,
        on_delete=models.PROTECT,
        related_name="catalog_zone",
        help_text="Backing DNS Zone for this catalog zone wrapper.",
        verbose_name="DNS Zone",
    )
    description = models.TextField(help_text="Description of this catalog zone.", blank=True)
    members = models.ManyToManyField(
        to=DNSZone,
        through="CatalogZoneMembership",
        related_name="member_of_catalog_zones",
        through_fields=("catalog_zone", "member_zone"),
        blank=True,
        help_text="Member DNS Zones included in this catalog zone.",
    )

    class Meta:
        """Meta attributes for CatalogZone."""

        verbose_name = "Catalog Zone"
        verbose_name_plural = "Catalog Zones"

    def __str__(self):
        """Stringify instance."""
        return str(self.dns_zone)

    def save(self, *args, **kwargs):
        """Persist wrapper and reconcile required catalog control records."""
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            self._ensure_apex_ns_record()
            self._ensure_version_control_record()
            return result

    def delete(self, *args, **kwargs):
        """Delete wrapper and its backing DNSZone in one transaction."""
        with transaction.atomic():
            zone = self.dns_zone
            self._delete_version_control_record()
            self._delete_apex_ns_record()
            super().delete(*args, **kwargs)
            zone.delete()

    @property
    def schema_version(self):
        """Read-only RFC 9432 schema version for catalog serialization."""
        return CATALOG_ZONE_SCHEMA_VERSION

    def _ensure_version_control_record(self):
        """Ensure the catalog's version TXT RRset is present and canonical."""
        # RFC 9432 §4.2.1 requires exactly one TXT RR at version.$CATZ with value "2".
        # Per §5.1, catalogs violating this are broken and MUST NOT be processed.
        version_rrset = TXTRecord.objects.filter(zone=self.dns_zone, name=CATALOG_ZONE_VERSION_RECORD_NAME)
        if version_rrset.count() == 1 and version_rrset.first().text == self.schema_version:
            return

        version_rrset.delete()
        TXTRecord(
            zone=self.dns_zone,
            name=CATALOG_ZONE_VERSION_RECORD_NAME,
            text=self.schema_version,
        ).validated_save()

    def _delete_version_control_record(self):
        """Delete the system-managed catalog version control record."""
        TXTRecord.objects.filter(
            zone_id=self.dns_zone_id,
            name=CATALOG_ZONE_VERSION_RECORD_NAME,
        ).delete()

    def _ensure_apex_ns_record(self):
        """Ensure apex NS RRset is present and canonical for this catalog zone."""
        apex_ns_rrset = NSRecord.objects.filter(zone=self.dns_zone, name="@")
        if apex_ns_rrset.count() == 1 and apex_ns_rrset.first().server == CATALOG_ZONE_DEFAULT_NS_TARGET:
            return

        apex_ns_rrset.delete()
        NSRecord(
            zone=self.dns_zone,
            name="@",
            server=CATALOG_ZONE_DEFAULT_NS_TARGET,
        ).validated_save()

    def _delete_apex_ns_record(self):
        """Delete the system-managed apex NS record from the backing zone."""
        NSRecord.objects.filter(
            zone_id=self.dns_zone_id,
            name="@",
        ).delete()


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class CatalogZoneMembership(PrimaryModel):
    """Through model representing a member zone within a catalog zone."""

    catalog_zone = models.ForeignKey(
        to=CatalogZone,
        on_delete=models.PROTECT,
        related_name="memberships",
        help_text="Catalog Zone wrapper that owns this membership.",
    )
    member_zone = models.ForeignKey(
        to=DNSZone,
        on_delete=models.PROTECT,
        related_name="catalog_zone_memberships",
        help_text="DNS Zone that is a member of the catalog.",
    )
    member_node_label = models.CharField(
        max_length=63,
        blank=True,
        help_text="Opaque immutable label for the member node in the catalog zone.",
    )
    objects = CatalogZoneMembershipManager()

    class Meta:
        """Meta attributes for CatalogZoneMembership."""

        constraints = [
            models.UniqueConstraint(
                fields=["catalog_zone", "member_zone"],
                name=CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_ZONE_UNIQUE,
            ),
            models.UniqueConstraint(
                fields=["catalog_zone", "member_node_label"],
                name=CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_NODE_LABEL_UNIQUE,
            ),
        ]
        verbose_name = "Catalog Zone Membership"
        verbose_name_plural = "Catalog Zone Memberships"

    def __str__(self):
        """Stringify instance."""
        return f"{self.member_zone} in {self.catalog_zone}"

    def clean(self):
        """Validate invariants and member label format."""
        super().clean()

        self._validate_member_zone()
        self._validate_member_node_label()

    def save(self, *args, **kwargs):
        """Persist membership while generating collision-safe random labels."""
        existing_membership = CatalogZoneMembership.objects.filter(member_zone_id=self.member_zone_id).exclude(
            pk=self.pk
        )
        if existing_membership.exists():
            raise CatalogZoneMembershipAlreadyExistsError(
                "Membership already exists for this member zone in another catalog zone."
            )

        #
        # TODO: Probably remove this. we shouldn't allow users to define their own member node labels.
        if self.member_node_label:
            return self._save_and_create_ptr_if_new(*args, **kwargs)

        # RFC 9432 §4.1 requires each member entry to use a unique member-node label,
        # and catalogs with duplicate label usage/semantics are treated as broken per §5.1.
        # Retry generation to avoid label collisions under concurrent create operations.
        for _ in range(CATALOG_MEMBER_NODE_LABEL_MAX_GENERATION_ATTEMPTS):
            self.member_node_label = generate_catalog_member_node_label()
            try:
                # Keep each retry attempt in its own savepoint so an IntegrityError on one attempt
                # does not poison an outer transaction and block subsequent retries.
                return self._save_and_create_ptr_if_new(*args, **kwargs)
            except IntegrityError as exc:
                constraint_name = self._get_integrity_error_constraint_name(exc)
                if constraint_name == CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_NODE_LABEL_UNIQUE:
                    continue

                if constraint_name == CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_ZONE_UNIQUE:
                    raise CatalogZoneMembershipAlreadyExistsError(
                        "Membership already exists for this catalog zone and member zone."
                    ) from exc

                # If the backend does not expose a constraint name (or this is a different IntegrityError),
                # do not guess and do not retry; fail fast so callers see the original database error.
                raise

        raise CatalogMemberNodeLabelGenerationError("Unable to generate a unique member node label.")

    def delete(self, *args, **kwargs):
        """Delete membership and remove derived PTR record."""
        with transaction.atomic():
            self._delete_member_ptr_record()
            return super().delete(*args, **kwargs)

    def _get_integrity_error_constraint_name(self, exc):
        """Return a database constraint name when available."""
        cause = getattr(exc, "__cause__", None)
        diag = getattr(cause, "diag", None)
        return getattr(diag, "constraint_name", None)

    def _save_and_create_ptr_if_new(self, *args, **kwargs):
        """Save membership atomically and create derived PTR record on create."""
        is_create = self._state.adding
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            if is_create:
                self._create_member_ptr_record()

            return result

    def _create_member_ptr_record(self):
        """Create RFC 9432 member PTR record in the catalog backing DNS zone."""
        ptr_name = f"{self.member_node_label}.zones"
        # RFC 9432 §4.1 states that if different member-node labels point to the same PTR target
        # (same member zone), the catalog is broken; per §5.1 broken catalogs MUST NOT be processed.
        conflicting_ptr_exists = (
            PTRRecord.objects.filter(
                zone=self.catalog_zone.dns_zone,
                ptrdname=self.member_zone.name,
            )
            .exclude(name=ptr_name)
            .exists()
        )
        if conflicting_ptr_exists:
            raise ValidationError(
                {
                    "member_zone": (
                        "Catalog backing zone already has a PTR record pointing to this member zone; "
                        "membership would create a duplicate target reference."
                    )
                }
            )

        ptr_record = PTRRecord(
            name=ptr_name,
            ptrdname=self.member_zone.name,
            zone=self.catalog_zone.dns_zone,
        )
        ptr_record.validated_save()

    def _delete_member_ptr_record(self):
        """Delete derived RFC 9432 member PTR record from the catalog backing zone."""
        PTRRecord.objects.filter(
            zone=self.catalog_zone.dns_zone,
            name=f"{self.member_node_label}.zones",
        ).delete()

    def _validate_member_node_label(self):
        """Validate member node label immutability and format."""
        if self.pk:
            current = CatalogZoneMembership.objects.only("member_node_label").filter(pk=self.pk).first()
            if current and self.member_node_label != current.member_node_label:
                raise ValidationError({"member_node_label": "Member node label is immutable after creation."})

        if not self.member_node_label:
            return

        if "." in self.member_node_label:
            raise ValidationError({"member_node_label": "Member node label must be a single DNS label."})

        if not self.member_node_label.isalnum():
            raise ValidationError({"member_node_label": "Member node label must contain only letters and digits."})

        DNSModel._validate_dns_label(self.member_node_label, field="member_node_label")

    def _validate_member_zone(self):
        """Validate that member zone is not a catalog zone backing zone."""
        catalog_with_member_zone_id = (
            CatalogZone.objects.filter(dns_zone_id=self.member_zone_id).values_list("id", flat=True).first()
        )
        if catalog_with_member_zone_id is not None:
            if catalog_with_member_zone_id == self.catalog_zone_id:
                raise ValidationError({"member_zone": "A catalog zone cannot contain itself as a member."})
            raise ValidationError({"member_zone": "A catalog zone cannot be added as a member zone."})


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


class DNSRecord(DNSModel):
    """Primary Dns Record model for plugin."""

    name = models.CharField(max_length=200, help_text="FQDN of the Record, w/o TLD.")
    zone = ForeignKeyWithAutoRelatedName(DNSZone, on_delete=models.PROTECT)
    _ttl = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        help_text="Time To Live (if no value is given, the Zone TTL will be used).",
        blank=True,
        null=True,
        verbose_name="TTL",
    )
    description = models.TextField(help_text="Description of the Record.", blank=True)
    comment = models.CharField(max_length=200, help_text="Comment for the Record.", blank=True)

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

    def _validate_total_wire_length_if_enabled(self) -> None:
        """Validate full DNS name (record + zone) total wire-format length if wire-format validation is enabled."""
        validation_level = getattr(constance_config, "nautobot_dns_models__DNS_VALIDATION_LEVEL")
        if validation_level != "wire-format":
            return

        record_label_list = [] if self.name == "" else self.name.split(".")
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

    class Meta:
        """Meta attributes for DnsRecord."""

        abstract = True

    @property
    def ttl(self):
        """Return the TTL value for the record."""
        if not self._ttl:
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

    def save(self, *args, **kwargs):
        """Ensure model validation runs on direct ORM writes."""
        self.clean()
        return super().save(*args, **kwargs)


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

    def save(self, *args, **kwargs):
        """Ensure model validation runs on direct ORM writes."""
        self.clean()
        return super().save(*args, **kwargs)


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
