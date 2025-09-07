"""Models for Nautobot DNS Models."""

from constance import config as constance_config
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from nautobot.apps.models import PrimaryModel, extras_features
from nautobot.core.models.fields import ForeignKeyWithAutoRelatedName


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
class DNSZoneModel(DNSModel):
    """Model for DNS SOA Records. An SOA Record defines a DNS Zone."""

    name = models.CharField(max_length=200, help_text="FQDN of the Zone, w/ TLD. e.g example.com", unique=True)
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

    class Meta:
        """Meta attributes for DNSZoneModel."""

        verbose_name = "DNS Zone"
        verbose_name_plural = "DNS Zones"


class DNSRecordModel(DNSModel):  # pylint: disable=too-many-ancestors
    """Primary Dns Record model for plugin."""

    name = models.CharField(max_length=200, help_text="FQDN of the Record, w/o TLD.")
    zone = ForeignKeyWithAutoRelatedName(DNSZoneModel, on_delete=models.PROTECT)
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
        super().clean()

        if not hasattr(self, "zone"):
            raise ValidationError({"zone": "Zone is required"})

        validation_level = getattr(constance_config, "nautobot_dns_models__DNS_VALIDATION_LEVEL")
        if validation_level == "wire-format":
            record_label_list = self.name.split(".")
            zone_label_list = self.zone.name.split(".")

            wire_length = 0
            # Record labels
            for label in record_label_list:
                wire_length += 1 + dns_wire_label_length(label)
            # Zone labels
            for label in zone_label_list:
                wire_length += 1 + dns_wire_label_length(label)
            wire_length += 1  # Add the final zero byte for root

            if wire_length > 255:
                raise ValidationError(
                    {"name": "Total length of DNS name cannot exceed 255 bytes (octets) in wire format."}
                )

    class Meta:
        """Meta attributes for DnsRecordModel."""

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
    "graphql",
    "relationships",
    "webhooks",
)
class NSRecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
    """NS Record model."""

    server = models.CharField(max_length=200, help_text="FQDN of an authoritative Name Server.")

    class Meta:
        """Meta attributes for NSRecordModel."""

        unique_together = [["name", "server", "zone"]]
        verbose_name = "NS Record"
        verbose_name_plural = "NS Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class ARecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
    """A Record model."""

    address = models.ForeignKey(
        to="ipam.IPAddress",
        on_delete=models.CASCADE,
        limit_choices_to={"ip_version": 4},
        help_text="IP address for the record.",
    )

    class Meta:
        """Meta attributes for ARecordModel."""

        unique_together = [["name", "address", "zone"]]
        verbose_name = "A Record"
        verbose_name_plural = "A Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class AAAARecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
    """AAAA Record model."""

    address = models.ForeignKey(
        to="ipam.IPAddress",
        on_delete=models.CASCADE,
        limit_choices_to={"ip_version": 6},
        help_text="IP address for the record.",
    )

    class Meta:
        """Meta attributes for AAAARecordModel."""

        unique_together = [["name", "address", "zone"]]
        verbose_name = "AAAA Record"
        verbose_name_plural = "AAAA Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class CNAMERecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
    """CNAME Record model."""

    alias = models.CharField(max_length=200, help_text="FQDN of the Alias.")

    class Meta:
        """Meta attributes for CNAMERecordModel."""

        unique_together = [["name", "alias", "zone"]]
        verbose_name = "CNAME Record"
        verbose_name_plural = "CNAME Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class MXRecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
    """MX Record model."""

    preference = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(65535)],
        default=10,
        help_text="Preference for the MX Record.",
    )
    mail_server = models.CharField(max_length=200, help_text="FQDN of the Mail Server.")

    class Meta:
        """Meta attributes for MXRecordModel."""

        unique_together = [["name", "mail_server", "zone"]]
        verbose_name = "MX Record"
        verbose_name_plural = "MX Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class TXTRecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
    """TXT Record model."""

    text = models.CharField(max_length=256, help_text="Text for the TXT Record.")

    class Meta:
        """Meta attributes for TXTRecordModel."""

        unique_together = [["name", "text", "zone"]]
        verbose_name = "TXT Record"
        verbose_name_plural = "TXT Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class PTRRecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
    """PTR Record model."""

    ptrdname = models.CharField(
        max_length=200, help_text="A domain name that points to some location in the domain name space."
    )

    class Meta:
        """Meta attributes for PTRRecordModel."""

        unique_together = [["name", "ptrdname", "zone"]]
        verbose_name = "PTR Record"
        verbose_name_plural = "PTR Records"

    def __str__(self):
        """String representation of PTRRecordModel."""
        return self.ptrdname


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class SRVRecordModel(DNSRecordModel):  # pylint: disable=too-many-ancestors
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
        """Meta attributes for SRVRecordModel."""

        unique_together = [["name", "target", "port", "zone"]]
        verbose_name = "SRV Record"
        verbose_name_plural = "SRV Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class DNSRule(PrimaryModel):
    """
    GUI-based DNS Rule for generating DNS records from network objects.

    Unlike Jinja-based rules, this uses a component-based approach where
    users build rules through a visual interface using drag-and-drop components.
    """

    name = models.CharField(max_length=100, unique=True, help_text="Unique name for this DNS rule")
    description = models.CharField(max_length=200, blank=True, help_text="Optional description of what this rule does")
    enabled = models.BooleanField(default=True, help_text="Whether this rule is active")

    content_type = models.ForeignKey(
        to="contenttypes.ContentType",
        on_delete=models.CASCADE,
        help_text="Type of object this rule applies to (e.g., Device, Interface)",
    )

    record_type = models.ForeignKey(
        to="contenttypes.ContentType",
        on_delete=models.CASCADE,
        related_name="dns_rules_for_record_type",
        limit_choices_to=models.Q(app_label="nautobot_dns_models")
        & models.Q(model__endswith="recordmodel")
        & ~models.Q(model="dnsrecordmodel"),  # Exclude abstract base
        help_text="Type of DNS record this rule creates",
    )

    # Zone selection approach - no Jinja templates!
    zone_source = models.CharField(
        max_length=20,
        choices=[
            ("fixed", "Fixed Zone"),
            ("field_reference", "Model Field Path"),
            ("custom_field", "Custom Field"),
        ],
        default="fixed",
        help_text="How to determine the DNS zone for generated records",
    )

    zone_fixed = models.ForeignKey(
        to="DNSZoneModel",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Fixed DNS zone (when zone_source='fixed')",
    )

    zone_field_path = models.CharField(
        max_length=200,
        blank=True,
        help_text="Model field path like 'device.location.zone' (when zone_source='field_reference')",
    )

    zone_custom_field = models.CharField(
        max_length=100, blank=True, help_text="Custom field name like 'dns_zone' (when zone_source='custom_field')"
    )

    class Meta:
        """Meta attributes for DNSRule."""

        ordering = ["name"]
        verbose_name = "DNS Rule"
        verbose_name_plural = "DNS Rules"

    def clean(self):
        """Validate zone configuration based on zone_source."""
        super().clean()

        if self.zone_source == "fixed" and not self.zone_fixed:
            raise ValidationError({"zone_fixed": "Fixed zone is required when zone_source is 'fixed'"})

        if self.zone_source == "field_reference" and not self.zone_field_path:
            raise ValidationError({"zone_field_path": "Field path is required when zone_source is 'field_reference'"})

        if self.zone_source == "custom_field" and not self.zone_custom_field:
            raise ValidationError(
                {"zone_custom_field": "Custom field name is required when zone_source is 'custom_field'"}
            )

    def get_zone_for_object(self, source_obj):
        """
        Resolve the DNS zone for a given source object based on zone_source configuration.

        Args:
            source_obj: The object being processed (Device, Interface, etc.)

        Returns:
            DNSZoneModel instance or None if not found
        """
        if self.zone_source == "fixed":
            return self.zone_fixed

        elif self.zone_source == "field_reference":
            # Navigate field path like "device.location.zone"
            try:
                current_obj = source_obj
                for field_name in self.zone_field_path.split("."):
                    current_obj = getattr(current_obj, field_name)

                # Ensure we got a DNSZoneModel
                if isinstance(current_obj, DNSZoneModel):
                    return current_obj
                elif hasattr(current_obj, "name"):  # Zone name string
                    return DNSZoneModel.objects.get(name=str(current_obj))

            except (AttributeError, DNSZoneModel.DoesNotExist):
                return None

        elif self.zone_source == "custom_field":
            # Get custom field value
            try:
                cf_value = source_obj.cf.get(self.zone_custom_field)
                if cf_value:
                    if isinstance(cf_value, DNSZoneModel):
                        return cf_value
                    else:  # Assume zone name string
                        return DNSZoneModel.objects.get(name=str(cf_value))
            except (AttributeError, DNSZoneModel.DoesNotExist):
                return None

        return None

    def __str__(self):
        """String representation of DNS rule."""
        record_name = self.record_type.model_class()._meta.verbose_name if self.record_type else "Unknown Record"

        # Include zone info
        if self.zone_source == "fixed" and self.zone_fixed:
            zone_info = f"→ {self.zone_fixed.name}"
        elif self.zone_source == "field_reference" and self.zone_field_path:
            zone_info = f"→ {self.zone_field_path}"
        elif self.zone_source == "custom_field" and self.zone_custom_field:
            zone_info = f"→ cf[{self.zone_custom_field}]"
        else:
            zone_info = ""

        return f"{self.name} ({record_name} for {self.content_type.model} {zone_info})"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class DNSRuleComponent(PrimaryModel):
    """
    Individual component within a DNS rule for GUI-based rule building.

    Components represent the building blocks that users drag and drop
    to construct DNS record names and values. Each component can be:
    - A field reference (e.g., "device.name", "interface.ip_addresses.first")
    - A literal text value (e.g., ".", "-", "example.com")
    - Optionally transformed by functions (e.g., normalize, replace slashes)
    """

    rule = models.ForeignKey(
        to="DNSRule",
        on_delete=models.CASCADE,
        related_name="components",
        help_text="DNS rule this component belongs to",
    )

    order = models.PositiveIntegerField(
        help_text="Position of this component within the rule (for building the final value)"
    )

    target_field = models.CharField(
        max_length=20,
        choices=[
            ("name", "Record Name"),
            ("value", "Record Value"),
            ("preference", "MX Preference"),
            ("priority", "SRV Priority"),
            ("weight", "SRV Weight"),
            ("port", "SRV Port"),
            ("text", "TXT Text"),
        ],
        help_text="Which DNS record field this component contributes to",
    )

    component_type = models.CharField(
        max_length=20,
        choices=[
            ("field_reference", "Field Reference"),
            ("literal", "Literal Text"),
        ],
        help_text="Type of component - field reference or static text",
    )

    # For field_reference components
    field_path = models.CharField(
        max_length=200,
        blank=True,
        help_text="Model field path like 'device.name' or 'ip_addresses.first' (when component_type='field_reference')",
    )

    # For literal components
    literal_value = models.CharField(
        max_length=200, blank=True, help_text="Static text value (when component_type='literal')"
    )

    # Optional transform function - choices populated dynamically from jinja_filters
    transform_function = models.CharField(
        max_length=50, blank=True, help_text="Optional transform to apply to the component value"
    )

    class Meta:
        """Meta attributes for DNSRuleComponent."""

        ordering = ["rule", "order"]
        verbose_name = "DNS Rule Component"
        verbose_name_plural = "DNS Rule Components"
        unique_together = [["rule", "order"]]

    @classmethod
    def get_transform_choices(cls):
        """Get available transform function choices dynamically from the transform registry."""
        from .transform_registry import get_transform_choices

        return get_transform_choices()

    def clean(self):
        """Validate component configuration based on component_type."""
        super().clean()

        if self.component_type == "field_reference" and not self.field_path:
            raise ValidationError({"field_path": "Field path is required when component_type is 'field_reference'"})

        if self.component_type == "literal" and not self.literal_value:
            raise ValidationError({"literal_value": "Literal value is required when component_type is 'literal'"})

    def get_value_for_object(self, source_obj):
        """
        Get the resolved value of this component for a given source object.

        Args:
            source_obj: The object being processed (Device, Interface, etc.)

        Returns:
            String value for this component
        """
        if self.component_type == "literal":
            value = self.literal_value

        elif self.component_type == "field_reference":
            try:
                # Navigate field path like "device.name" or "ip_addresses.first"
                current_obj = source_obj
                for field_name in self.field_path.split("."):
                    if field_name == "first":
                        # Handle .first() for querysets/managers
                        if hasattr(current_obj, "first"):
                            current_obj = current_obj.first()
                        else:
                            current_obj = None
                            break
                    else:
                        current_obj = getattr(current_obj, field_name)

                value = str(current_obj) if current_obj is not None else ""

            except AttributeError:
                value = ""
        else:
            value = ""

        # Apply transform function if specified
        if self.transform_function and value:
            value = self._apply_transform(value)

        return value

    def _apply_transform(self, value):
        """Apply the specified transform function to a value using the dynamic transform system."""
        from .transform_registry import apply_transform

        return apply_transform(self.transform_function, value)

    def get_transform_display_name(self):
        """Get the display name for the current transform function."""
        if not self.transform_function:
            return None

        from .transform_registry import get_transform_info

        transform_info = get_transform_info(self.transform_function)
        return transform_info["display_name"] if transform_info else self.transform_function

    def __str__(self):
        """String representation of DNS rule component."""
        if self.component_type == "field_reference":
            base = f"{self.field_path}"
        else:
            base = f"'{self.literal_value}'"

        if self.transform_function:
            display_name = self.get_transform_display_name()
            base += f" | {display_name}"

        return f"{self.rule.name}[{self.order}]: {base} → {self.get_target_field_display()}"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "relationships",
    "webhooks",
)
class DNSRuleRecord(PrimaryModel):
    """
    Tracking record linking DNS rules to the DNS records they generated.

    This model tracks which GUI-based rules generated which DNS records
    from which source objects, enabling:
    - Cleanup when rules change
    - Cascade deletion when source objects are removed
    - Audit trail of rule-generated records
    - Bulk operations on rule-generated records
    """

    rule = models.ForeignKey(
        to="DNSRule",
        on_delete=models.CASCADE,
        related_name="generated_records",
        help_text="DNS rule that generated this record",
    )

    # Generic foreign key to source object (Device, Interface, etc.)
    source_content_type = models.ForeignKey(
        to="contenttypes.ContentType",
        on_delete=models.CASCADE,
        related_name="dns_rule_records_as_source",
        help_text="Content type of the source object that triggered rule processing",
    )

    source_object_id = models.UUIDField(
        db_index=True, help_text="ID of the source object that triggered rule processing"
    )

    source_object = GenericForeignKey("source_content_type", "source_object_id")

    # Generic foreign key to generated DNS record (ARecordModel, CNAMERecordModel, etc.)
    # Note: ContentType comes from rule.record_type - no duplication needed
    dns_record_object_id = models.UUIDField(db_index=True, help_text="ID of the generated DNS record")

    @property
    def dns_record_content_type(self):
        """Get DNS record content type from the associated rule."""
        return self.rule.record_type if self.rule else None

    @property
    def dns_record_object(self):
        """Get the actual DNS record object using the rule's record type."""
        if self.rule and self.rule.record_type and self.dns_record_object_id:
            try:
                model_class = self.rule.record_type.model_class()
                if model_class:
                    return model_class.objects.get(id=self.dns_record_object_id)
            except Exception:
                pass
        return None

    class Meta:
        """Meta attributes for DNSRuleRecord."""

        ordering = ["rule", "source_content_type", "source_object_id"]
        verbose_name = "DNS Rule Record"
        verbose_name_plural = "DNS Rule Records"
        unique_together = [["rule", "source_content_type", "source_object_id", "dns_record_object_id"]]

    @property
    def source_object_name(self):
        """Get display name of the source object."""
        try:
            return (
                str(self.source_object)
                if self.source_object
                else f"{self.source_content_type.model}:{self.source_object_id}"
            )
        except Exception:
            return f"{self.source_content_type.model}:{self.source_object_id}"

    @property
    def dns_record_name(self):
        """Get display name of the DNS record."""
        dns_record = self.dns_record_object
        if dns_record:
            return str(dns_record)
        elif self.dns_record_content_type:
            return f"{self.dns_record_content_type.model}:{self.dns_record_object_id}"
        else:
            return f"record:{self.dns_record_object_id}"

    def __str__(self):
        """String representation of DNS rule record."""
        return f"{self.rule.name}: {self.source_object_name} → {self.dns_record_name}"
