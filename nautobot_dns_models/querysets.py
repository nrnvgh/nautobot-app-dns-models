"""QuerySets for nautobot_dns_models."""

from nautobot.core.models import BaseManager
from nautobot.core.models.querysets import RestrictedQuerySet


class CatalogZoneMembershipQuerySet(RestrictedQuerySet):
    """QuerySet preserving per-instance delete side effects."""

    def delete(self, *args, **kwargs):
        """Delete each membership row to ensure PTR cleanup occurs."""
        deleted_count = 0
        deleted_per_model = {}

        for membership in self:
            count, by_model = membership.delete(*args, **kwargs)
            deleted_count += count
            for model_label, model_count in by_model.items():
                deleted_per_model[model_label] = deleted_per_model.get(model_label, 0) + model_count

        return deleted_count, deleted_per_model


class CatalogZoneMembershipManager(BaseManager.from_queryset(CatalogZoneMembershipQuerySet)):
    """Manager preserving queryset-level delete side effects."""
