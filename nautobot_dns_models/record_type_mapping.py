"""Helpers for mapping DNS rule record types to record model classes."""

from nautobot_dns_models.choices import DNSRuleRecordTypeChoices


def get_dns_record_model_class(record_type):
    """Return the DNS record model class for a DNSRule record type."""
    supported_values = {value for value, _label in DNSRuleRecordTypeChoices.CHOICES}
    if record_type not in supported_values:
        raise ValueError(f'Unsupported DNS rule record_type "{record_type}"')

    # Local imports avoid circular imports during Django app/model initialization.
    # pylint: disable=import-outside-toplevel
    from nautobot_dns_models import models as dns_models
    from nautobot_dns_models.models import DNSRecord
    # pylint: enable=import-outside-toplevel

    model_name = f"{record_type}Record"
    model_class = getattr(dns_models, model_name, None)
    if model_class is None:
        raise ValueError(f'DNS record model "{model_name}" is not available')

    if not issubclass(model_class, DNSRecord):
        raise ValueError(f'Resolved model "{model_name}" is not a DNSRecord subclass')

    return model_class
