"""Plugin declaration for nautobot_dns_models."""

from importlib import metadata

from django.conf import settings
from nautobot.apps import ConstanceConfigItem, NautobotAppConfig
from nautobot.core.signals import nautobot_database_ready

__version__ = metadata.version(__name__)

constance_additional_fields = {
    "show_dns_panel": [
        "django.forms.fields.ChoiceField",
        {
            "widget": "django.forms.Select",
            "choices": [
                ("always", "Always"),
                ("if_present", "If records are present"),
                ("never", "Never"),
            ],
        },
    ],
    "dns_validation_level": [
        "django.forms.fields.ChoiceField",
        {
            "widget": "django.forms.Select",
            "choices": [
                ("none", "Disabled"),
                ("wire-format", "Wire format"),
            ],
        },
    ],
    "normalize_dns_records": [
        "django.forms.fields.BooleanField",
        {
            "widget": "django.forms.CheckboxInput",
        },
    ],
}

# pylint:disable=no-member
settings.CONSTANCE_ADDITIONAL_FIELDS |= constance_additional_fields


class NautobotDnsModelsConfig(NautobotAppConfig):
    """Plugin configuration for the nautobot_dns_models plugin."""

    name = "nautobot_dns_models"
    verbose_name = "Nautobot DNS Models"
    version = __version__
    author = "Network to Code, LLC"
    description = "Nautobot DNS Models."
    base_url = "dns"
    required_settings = []
    min_version = "2.4.0"
    max_version = "2.9999"
    default_settings = {}
    caching_config = {}
    docs_view_name = "plugins:nautobot_dns_models:docs"

    constance_config = {
        "SHOW_FORWARD_PANEL": ConstanceConfigItem(
            default="Always",
            help_text="Show A/AAAA Records panel in IP Address detailed view.",
            field_type="show_dns_panel",
        ),
        "SHOW_REVERSE_PANEL": ConstanceConfigItem(
            default="Always",
            help_text="Show PTR Records panel in IP Address detailed view.",
            field_type="show_dns_panel",
        ),
        "DNS_VALIDATION_LEVEL": ConstanceConfigItem(
            default="wire-format",
            help_text="DNS validation level for zones and records.",
            field_type="dns_validation_level",
        ),
        "NORMALIZE_DNS_RECORDS": ConstanceConfigItem(
            default=False,
            help_text="Normalize DNS records on save.",
            field_type="normalize_dns_records",
        ),
    }

    searchable_models = [
        "DNSZone",
        "ARecord",
        "AAAARecord",
        "PTRRecord",
        "CNAMERecord",
        "NSRecord",
        "MXRecord",
        "SRVRecord",
        "TXTRecord",
        "DNSRule",
    ]

    def ready(self):
        """Import signal handlers when the app is ready."""
        super().ready()
        # Import signals to ensure they are connected
        import nautobot_dns_models.signals  # noqa: F401   pylint: disable=unused-import
        from nautobot_dns_models.signals import post_migrate_create_data_validation_rules

        nautobot_database_ready.connect(post_migrate_create_data_validation_rules, sender=self)


config = NautobotDnsModelsConfig  # pylint:disable=invalid-name
