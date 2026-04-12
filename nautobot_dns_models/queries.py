"""Shared query helpers for DNS models."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from nautobot_dns_models.source_model_support import get_supported_source_model_pairs


class DNSRuleContentTypeQuery:
    """Shared query helper for object types supported by DNS rules."""

    @staticmethod
    def get_query():
        """Return a Q object for supported DNS rule source models."""
        model_pairs = get_supported_source_model_pairs()
        if not model_pairs:
            return Q(pk__in=[])

        q = Q()
        for app_label, model_name in model_pairs:
            q |= Q(app_label=app_label, model=model_name)

        return q

    @classmethod
    def as_queryset(cls):
        """Return ordered ContentType queryset for supported DNS rule models."""
        return ContentType.objects.filter(cls.get_query()).order_by("app_label", "model")

    @classmethod
    def get_choices(cls):
        """Return choices as `(content_type_pk, model_label)` tuples."""
        return tuple((ct.pk, f"{ct.app_label}.{ct.model}") for ct in cls.as_queryset())
