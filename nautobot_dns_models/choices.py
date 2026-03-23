"""Choices for DNS models."""

from nautobot.apps.choices import ChoiceSet


class DNSRuleRecordTypeChoices(ChoiceSet):
    """Choices for DNS record types."""

    A = "A"
    AAAA = "AAAA"

    CHOICES = (
        (A, "A Record"),
        (AAAA, "AAAA Record"),
    )
