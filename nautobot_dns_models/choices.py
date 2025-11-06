"""Choices for DNS models."""

from nautobot.apps.choices import ChoiceSet


class DNSRecordTypeChoices(ChoiceSet):
    """Choices for DNS record types."""

    A = "A"
    AAAA = "AAAA"
    CNAME = "CNAME"
    PTR = "PTR"

    CHOICES = (
        (A, "A Record"),
        (AAAA, "AAAA Record"),
        (CNAME, "CNAME Record"),
        (PTR, "PTR Record"),
    )
