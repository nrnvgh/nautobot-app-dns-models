"""Shared query helpers for DNS models."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q


class DNSRuleContentTypeQuery:
    """Shared query helper for object types supported by DNS rules."""

    @staticmethod
    def get_query():
        """Return a Q object for supported DNS rule source models."""
        return (
            Q(app_label="dcim", model__in=["device", "interface"])
            | Q(app_label="virtualization", model__in=["virtualmachine", "vminterface"])
            | Q(app_label="ipam", model="service")
        )

    @classmethod
    def as_queryset(cls):
        """Return ordered ContentType queryset for supported DNS rule models."""
        return ContentType.objects.filter(cls.get_query()).order_by("app_label", "model")
