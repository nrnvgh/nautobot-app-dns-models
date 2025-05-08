"""Models for Nautobot DNS Models."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from jinja2 import Environment, TemplateSyntaxError
from nautobot.apps.models import PrimaryModel, extras_features
from nautobot.core.models.fields import ForeignKeyWithAutoRelatedName

# from nautobot.extras.utils import extras_features
# If you want to use the extras_features decorator please reference the following documentation
# https://nautobot.readthedocs.io/en/latest/plugins/development/#using-the-extras_features-decorator-for-graphql
# Then based on your reading you may decide to put the following decorator before the declaration of your class
# @extras_features("custom_fields", "custom_validators", "relationships", "graphql")

# If you want to choose a specific model to overload in your class declaration, please reference the following documentation:
# how to chose a database model: https://nautobot.readthedocs.io/en/stable/plugins/development/#database-models


class DNSModel(PrimaryModel):
    """Abstract Model for Nautobot DNS Models."""

    class Meta:
        """Meta class."""

        abstract = True

        # Option for fixing capitalization (i.e. "Snmp" vs "SNMP")
        # verbose_name = "Nautobot DNS Models"

        # Option for fixing plural name (i.e. "Chicken Tenders" vs "Chicken Tendies")
        # verbose_name_plural = "Nautobot DNS Modelss"

    def __str__(self):
        """Stringify instance."""
        return self.name  # pylint: disable=no-member


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
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)], default=3600, help_text="Time To Live."
    )
    filename = models.CharField(max_length=200, help_text="Filename of the Zone File.")
    description = models.TextField(help_text="Description of the Zone.", blank=True)
    soa_mname = models.CharField(
        max_length=200,
        help_text="FQDN of the Authoritative Name Server for Zone.",
        null=False,
    )
    soa_rname = models.EmailField(help_text="Admin Email for the Zone in the form")
    soa_refresh = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=86400,
        help_text="Number of seconds after which secondary name servers should query the master for the SOA record, to detect zone changes.",
    )
    soa_retry = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=7200,
        help_text="Number of seconds after which secondary name servers should retry to request the serial number from the master if the master does not respond.",
    )
    soa_expire = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=3600000,
        help_text="Number of seconds after which secondary name servers should stop answering request for this zone if the master does not respond. This value must be bigger than the sum of Refresh and Retry.",
    )
    soa_serial = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(2147483647)],
        default=0,
        help_text="Serial number of the zone. This value must be incremented each time the zone is changed, and secondary DNS servers must be able to retrieve this value to check if the zone has been updated.",
    )
    soa_minimum = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=3600,
        help_text="Minimum TTL for records in this zone.",
    )

    class Meta:
        """Meta attributes for DNSZoneModel."""

        verbose_name = "DNS Zone"
        verbose_name_plural = "DNS Zones"


class DNSRecordModel(DNSModel):  # pylint: disable=too-many-ancestors
    """Primary Dns Record model for plugin."""

    name = models.CharField(max_length=200, help_text="FQDN of the Record, w/o TLD.")
    zone = ForeignKeyWithAutoRelatedName(DNSZoneModel, on_delete=models.PROTECT)
    ttl = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)], default=3600, help_text="Time To Live."
    )
    description = models.TextField(help_text="Description of the Record.", blank=True)
    comment = models.CharField(max_length=200, help_text="Comment for the Record.", blank=True)

    class Meta:
        """Meta attributes for DnsRecordModel."""

        abstract = True


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

    address = models.ForeignKey(to="ipam.IPAddress", on_delete=models.CASCADE, help_text="IP address for the record.")

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

    address = models.ForeignKey(to="ipam.IPAddress", on_delete=models.CASCADE, help_text="IP address for the record.")

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
class DNSRule(DNSModel):
    """Model for automatic DNS record creation rules."""

    class Meta:
        """Meta attributes for DNSRule."""
        ordering = ("name", "priority")
        verbose_name = "DNS Rule"
        verbose_name_plural = "DNS Rules"
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "record_type"],
                name="unique_content_type_record_type"
            )
        ]

    # Basic fields
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Name of the rule"
    )
    description = models.TextField(
        blank=True,
        help_text="Description of the rule's purpose"
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Whether this rule is active"
    )

    # Rule configuration
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE,
        help_text="The type of object this rule applies to (e.g. dcim.interface)"
    )
    priority = models.PositiveIntegerField(
        default=1000,
        help_text="Priority of this rule (lower numbers run first)"
    )

    # DNS Record configuration
    zone_template = models.TextField(
        help_text="Jinja2 template for determining the DNS zone (must resolve to a valid zone name)"
    )
    record_type = models.CharField(
        max_length=10,
        choices=[
            ('A', 'A Record'),
            ('AAAA', 'AAAA Record'),
            ('CNAME', 'CNAME Record'),
            ('MX', 'MX Record'),
            ('NS', 'NS Record'),
            ('PTR', 'PTR Record'),
            ('TXT', 'TXT Record'),
        ],
        help_text="Type of DNS record to create"
    )
    name_template = models.TextField(
        help_text="Jinja2 template for generating the DNS record name"
    )
    value_template = models.TextField(
        help_text="Jinja2 template for generating the record value (IP Addresses must be represented as UUIDs)."
    )
    ttl = models.IntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(2147483647)],
        default=3600,
        help_text="Time To Live for created records"
    )

    # MX Record specific
    mx_preference = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(65535)],
        default=10,
        help_text="Preference for MX records (ignored for other record types)",
        null=True,
        blank=True
    )

    def clean(self):
        """Validate the rule configuration."""
        super().clean()

        # Validate the Jinja templates syntax
        try:
            env = Environment()
            for template_field in ['zone_template', 'name_template', 'value_template']:
                template = getattr(self, template_field)
                env.parse(template)
        except Exception as e:
            raise ValidationError({
                'template': f"Invalid Jinja2 template syntax in {template_field}: {str(e)}"
            })

        # Validate MX preference is set if record type is MX
        if self.record_type == 'MX' and self.mx_preference is None:
            raise ValidationError({
                'mx_preference': "Preference is required for MX records"
            })

    def __str__(self):
        """String representation of the rule."""
        return f"{self.name} ({self.get_record_type_display()})"

    def render_template(self, template_field, obj):
        """
        Render a template field with the given object as context.
        """
        template = getattr(self, template_field)
        context = {'object': obj}
        try:
            from nautobot.core.utils.data import render_jinja2
            return render_jinja2(template, context)
        except Exception as e:
            raise ValueError(f"Failed to render {template_field}: {str(e)}")

    def render_zone_template(self, obj):
        """Render the zone template for a given object."""
        return self.render_template('zone_template', obj)

    def render_name_template(self, obj):
        """Render the name template for a given object."""
        return self.render_template('name_template', obj)

    def render_value_template(self, obj):
        """Render the value template for a given object."""
        return self.render_template('value_template', obj)
