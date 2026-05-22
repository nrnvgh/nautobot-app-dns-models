"""QuerySets for nautobot_dns_models."""

from django.db import IntegrityError, transaction
from nautobot.core.models import BaseManager
from nautobot.core.models.querysets import RestrictedQuerySet


class CatalogZoneMembershipQuerySet(RestrictedQuerySet):
    """QuerySet preserving per-instance delete side effects."""

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        """
        Persist through-table rows via validated_save() to preserve side effects.

        Django M2M add/set operations bulk_create through-table rows directly,
        bypassing model save hooks. Route these inserts through validated_save()
        so labels and derived PTR records are handled without signals.
        """
        if update_conflicts:
            return super().bulk_create(
                objs,
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
                update_conflicts=update_conflicts,
                update_fields=update_fields,
                unique_fields=unique_fields,
            )

        created = []
        with transaction.atomic():
            for obj in objs:
                try:
                    obj.validated_save()
                    created.append(obj)
                except IntegrityError:
                    if not ignore_conflicts:
                        raise
        return created

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
    """Manager ensuring through-table bulk inserts run validated model saves."""
