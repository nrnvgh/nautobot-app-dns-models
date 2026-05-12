"""Signals for nautobot_dns_models."""

from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from nautobot_dns_models.models import CatalogZoneMembership


@receiver(m2m_changed, sender=CatalogZoneMembership)
def assign_member_node_labels_on_members_add(sender, instance, action, reverse, model, pk_set, **kwargs):  # pylint: disable=unused-argument
    """
    Ensure through-table rows get labels when created via M2M add/set operations.

    The  m2m workflow can bulk-create through rows with blank labels, which can
    fail uniqueness checks before post_add runs. Pre-create memberships with
    validated_save() in pre_add, then clear pk_set to skip default bulk insert.
    """
    if reverse or not pk_set:
        return

    if action != "pre_add":
        return

    existing_member_zone_ids = set(
        CatalogZoneMembership.objects.filter(
            catalog_zone=instance,
            member_zone_id__in=pk_set,
        ).values_list("member_zone_id", flat=True)
    )
    for member_zone_id in pk_set - existing_member_zone_ids:
        membership = CatalogZoneMembership(
            catalog_zone=instance,
            member_zone_id=member_zone_id,
        )
        membership.validated_save()

    pk_set.clear()
