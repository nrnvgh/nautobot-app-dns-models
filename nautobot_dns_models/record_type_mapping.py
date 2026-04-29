"""Helpers for mapping DNS rule record types to record model classes."""

from django.apps import apps

from nautobot_dns_models.choices import DNSRuleRecordTypeChoices


def get_dns_record_model_class(record_type):
    """Return the DNS record model class for a DNSRule record type."""
    supported_values = {value for value, _label in DNSRuleRecordTypeChoices.CHOICES}
    if record_type not in supported_values:
        raise ValueError(f'Unsupported DNS rule record_type "{record_type}"')

    model_name = f"{record_type}Record"
    model_class = apps.get_model("nautobot_dns_models", model_name)
    if model_class is None:
        raise ValueError(f'DNS record model "{model_name}" is not available')

    from nautobot_dns_models.models import DNSRecord  # pylint: disable=import-outside-toplevel

    if not issubclass(model_class, DNSRecord):
        raise ValueError(f'Resolved model "{model_name}" is not a DNSRecord subclass')

    return model_class
