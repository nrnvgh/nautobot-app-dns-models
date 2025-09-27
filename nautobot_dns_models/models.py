"""Models for Nautobot DNS Models."""

import logging

from constance import config as constance_config
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from jinja2 import TemplateAssertionError, TemplateError, TemplateSyntaxError
from nautobot.apps.constants import CHARFIELD_MAX_LENGTH
from nautobot.apps.models import BaseModel, PrimaryModel, extras_features
from nautobot.apps.utils import validate_jinja2
from nautobot.core.models.fields import ForeignKeyWithAutoRelatedName

logger = logging.getLogger(__name__)


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
class DNSZone(DNSModel):
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
        """Meta attributes for DNSZone."""

        verbose_name = "DNS Zone"
        verbose_name_plural = "DNS Zones"


class DNSRecord(DNSModel):  # pylint: disable=too-many-ancestors
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
class NSRecord(DNSRecord):  # pylint: disable=too-many-ancestors
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
class ARecord(DNSRecord):  # pylint: disable=too-many-ancestors
    """A Record model."""

    address = models.ForeignKey(
        to="ipam.IPAddress",
        on_delete=models.CASCADE,
        limit_choices_to={"ip_version": 4},
        help_text="IP address for the record.",
    )

    #
    # TODO: This is POC and should be updated to use GenericRelation (or at
    # TODO: least compare SQL queries/performance to make a determination)
    @property
    def dns_rule_records(self):
        """Mock GenericRelation: Get DNSRuleRecord objects that track this A record."""
        return DNSRuleRecord.objects.filter(
            dns_record_content_type=ContentType.objects.get_for_model(self), dns_record_object_id=self.id
        )

    @property
    def source_object(self):
        """Get the source object that created this A record via DNS rules."""
        try:
            tracking_record = self.dns_rule_records.get()
            return tracking_record.source_object
        except DNSRuleRecord.DoesNotExist:
            return None

    @property
    def dns_rule(self):
        """Get the DNS rule that created this A record."""
        try:
            tracking_record = self.dns_rule_records.get()
            return tracking_record.rule
        except DNSRuleRecord.DoesNotExist:
            return None

    class Meta:
        """Meta attributes for ARecord."""

        unique_together = [["name", "address", "zone"]]
        verbose_name = "A Record"
        verbose_name_plural = "A Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class AAAARecord(DNSRecord):  # pylint: disable=too-many-ancestors
    """AAAA Record model."""

    address = models.ForeignKey(
        to="ipam.IPAddress",
        on_delete=models.CASCADE,
        limit_choices_to={"ip_version": 6},
        help_text="IP address for the record.",
    )

    class Meta:
        """Meta attributes for AAAARecord."""

        unique_together = [["name", "address", "zone"]]
        verbose_name = "AAAA Record"
        verbose_name_plural = "AAAA Records"


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "relationships",
    "webhooks",
)
class CNAMERecord(DNSRecord):  # pylint: disable=too-many-ancestors
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
class MXRecord(DNSRecord):  # pylint: disable=too-many-ancestors
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
class TXTRecord(DNSRecord):  # pylint: disable=too-many-ancestors
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
class PTRRecord(DNSRecord):  # pylint: disable=too-many-ancestors
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
class SRVRecord(DNSRecord):  # pylint: disable=too-many-ancestors
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


# DNS Record type choices for DNSRule
RECORD_TYPE_CHOICES = [
    ("A", "A Record"),
    ("AAAA", "AAAA Record"),
    ("CNAME", "CNAME Record"),
    ("MX", "MX Record"),
    ("NS", "NS Record"),
    ("PTR", "PTR Record"),
    ("SRV", "SRV Record"),
    ("TXT", "TXT Record"),
]


@extras_features(
    "custom_fields",
    "custom_links",
    "custom_validators",
    "export_templates",
    "graphql",
    "locations",
    "relationships",
    "webhooks",
)
class DNSRule(PrimaryModel):
    """Model for DNS record auto-creation rules."""

    name = models.CharField(max_length=100, unique=True, help_text="Name of the DNS rule")
    description = models.CharField(max_length=CHARFIELD_MAX_LENGTH, blank=True, help_text="Description of the DNS rule")
    enabled = models.BooleanField(default=True, help_text="Whether this rule is enabled")
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, help_text="Content type that triggers this rule"
    )
    location = models.ForeignKey(
        "dcim.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_index=True,
        help_text="Scope rule to specific location. Leave blank for global rule.",
    )

    # Templates
    zone_template = models.TextField(help_text="Jinja2 template for DNS zone name")
    record_type = models.CharField(max_length=10, choices=RECORD_TYPE_CHOICES, help_text="Type of DNS record")
    name_template = models.TextField(help_text="Jinja2 template for record name")

    value_template = models.TextField(help_text="Jinja2 template for the primary record value")

    # Additional fields for complex record types

    # MX Record templates
    preference_template = models.TextField(blank=True, help_text="MX preference value")

    # SRV Record templates
    priority_template = models.TextField(blank=True, help_text="SRV priority value")
    weight_template = models.TextField(blank=True, help_text="SRV weight value")
    port_template = models.TextField(blank=True, help_text="SRV port number")

    class Meta:
        """Meta attributes for DNSRule."""

        ordering = ["name"]
        verbose_name = "DNS Rule"
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "record_type", "location"],
                condition=models.Q(enabled=True),
                name="unique_enabled_rule_per_content_record_location",
            ),
        ]

    def __str__(self):
        """String representation of DNSRule."""
        return self.name

    def validate_unique(self, exclude=None):
        """
        Handle uniqueness for global rules (location=None).

        UniqueConstraint handles location-scoped rules automatically,
        but we need manual validation for global rules due to NULL behavior.
        """
        # Missing required fields is a larger issue that will be handled automatically, but since we
        # use them in the if block, we need to return before the if block if they're in the exclude list.
        exclude = exclude or []
        if "content_type" in exclude or "record_type" in exclude:
            super().validate_unique(exclude)
            return

        # Only handle the global rules case (location=None) and only for enabled rules
        # Location-scoped rules are handled by the database UniqueConstraint with condition
        if (
            self.location is None
            and self.enabled
            and DNSRule.objects.exclude(pk=self.pk)
            .filter(content_type=self.content_type, record_type=self.record_type, location__isnull=True, enabled=True)
            .exists()
        ):
            raise ValidationError(
                {
                    "location": f"An enabled global {self.record_type} record rule for '{self.content_type}' already exists."
                }
            )

        super().validate_unique(exclude)

    def clean(self):
        """Validate DNS rule templates and configuration."""
        super().clean()

        errors = {}

        # Validate template syntax using Nautobot's render_jinja2
        template_fields = [
            ("zone_template", self.zone_template),
            ("name_template", self.name_template),
            ("value_template", self.value_template),
        ]

        # Add record-type-specific templates
        if self.record_type == "MX" and self.preference_template:
            template_fields.append(("preference_template", self.preference_template))
        elif self.record_type == "SRV":
            if self.priority_template:
                template_fields.append(("priority_template", self.priority_template))
            if self.weight_template:
                template_fields.append(("weight_template", self.weight_template))
            if self.port_template:
                template_fields.append(("port_template", self.port_template))

        # Validate each template with full compilation and runtime testing
        for field_name, template_content in template_fields:
            if template_content:
                try:
                    # Step 1: Basic syntax validation (fast check)
                    validate_jinja2(template_content)

                    # Step 2: Full compilation and runtime testing via helper
                    error_message = self._validate_template_compilation_and_runtime(template_content, field_name)
                    if error_message:
                        errors[field_name] = error_message

                except TemplateSyntaxError as exc:
                    # Basic syntax errors (unclosed tags, invalid operators, etc.)
                    errors[field_name] = f"Template syntax error on line {exc.lineno}: {exc.message}"
                except TemplateError as exc:
                    # Other Jinja2 template errors.
                    # XXX Is this needed?
                    errors[field_name] = f"Template error: {exc}"
                except Exception as exc:
                    # System-level exceptions (very rare) - memory, recursion, encoding issues
                    errors[field_name] = f"Template validation failed: {exc}"

        # Validate record-type-specific requirements
        if self.record_type == "MX" and not self.preference_template:
            errors["preference_template"] = "MX records require a preference template"
        elif self.record_type == "SRV":
            required_srv_fields = ["priority_template", "weight_template", "port_template"]
            for field in required_srv_fields:
                if not getattr(self, field):
                    errors[field] = f"SRV records require a {field.replace('_template', '')} template"

        # Validate content type exists
        # NOTE: In a perfect world, there would be a mixin of some sort which would
        # NOTE: handle this. For example, Tag, LocationType, Role, etc.
        if self.content_type_id:
            try:
                content_type = self.content_type
                model_class = content_type.model_class()
                if not model_class:
                    errors["content_type"] = "Selected content type does not exist"
            except Exception:
                errors["content_type"] = "Invalid content type"

        if errors:
            raise ValidationError(errors)

    #
    # In principle, this logic could be added to the Nautobot core. May not work for every case
    # where jinja2 is rendered, but certainly will for any where the jinja is tied to a content type.
    # OTOH, this does assume that the first object in the queryset is guarenteed to have any field
    # that any template is using, which may be...optimistic.
    def _validate_template_compilation_and_runtime(self, template_content: str, field_name: str) -> str | None:
        """
        Validate template compilation and runtime execution.

        Args:
            template_content: The template string to validate
            field_name: The field name (for error context)

        Returns:
            Error message if validation fails, None if successful
        """
        # TODO move this to the top of the file /if/ we keep this method.
        from nautobot.core.utils.data import render_jinja2

        try:
            # Get sample object for realistic testing
            sample_obj = None

            model_class = self.content_type.model_class()
            if model_class:
                sample_obj = model_class.objects.first()

            # Test render with sample object or empty context
            context = {"obj": sample_obj} if sample_obj else {}
            result = render_jinja2(template_content, context)

            if sample_obj:
                logger.debug(f"Template {field_name} rendered successfully with {model_class.__name__}: '{result}'")
            else:
                logger.debug(f"Template {field_name} compiled successfully (no sample object available)")

            return None  # Success

        except TemplateAssertionError as exc:
            # Filter errors (non-existent filters, invalid filter usage)
            return f"Template filter error: {exc}"
        except TemplateError as exc:
            # Other Jinja2 template errors
            return f"Template error: {exc}"


class DNSRuleRecord(BaseModel):
    """Links source objects to DNS records created by rules."""

    rule = models.ForeignKey(DNSRule, on_delete=models.CASCADE, help_text="DNS rule that created this record")
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, help_text="Content type of the source object"
    )
    object_id = models.UUIDField(db_index=True, help_text="ID of the source object")
    source_object = GenericForeignKey("content_type", "object_id")

    dns_record_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="rule_records", help_text="Content type of the DNS record"
    )
    dns_record_object_id = models.UUIDField(db_index=True, help_text="ID of the DNS record")
    dns_record = GenericForeignKey("dns_record_content_type", "dns_record_object_id")

    class Meta:
        """Meta attributes for DNSRuleRecord."""

        unique_together = [["rule", "content_type", "object_id", "dns_record_content_type", "dns_record_object_id"]]
        verbose_name = "DNS Rule Record"
        verbose_name_plural = "DNS Rule Records"

    def __str__(self):
        """String representation of DNSRuleRecord."""
        return f"{self.rule.name} -> {self.dns_record}"
