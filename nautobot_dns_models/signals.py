"""Signals for nautobot_dns_models."""

from django.db.models.signals import m2m_changed, pre_delete
from django.dispatch import receiver

from nautobot_dns_models.models import CatalogZoneMembership


@receiver(m2m_changed, sender=CatalogZoneMembership)
def assign_member_node_labels_on_members_add(sender, instance, action, reverse, model, pk_set, **kwargs):  # pylint: disable=unused-argument,too-many-arguments
    """
    Ensure through-table rows get labels when created via M2M add/set operations.

    The  m2m workflow can bulk-create through rows with blank labels, which can
    fail uniqueness checks before post_add runs. Pre-create memberships with
    validated_save() in pre_add, then clear pk_set to skip default bulk insert.
    """
    if not pk_set:
        return

    if action != "pre_add":
        return

    if reverse:
        # Reverse M2M operations (e.g. member_zone.member_of_catalog_zones.add/set()):
        # `instance` is a DNSZone (member zone), and `pk_set` contains CatalogZone IDs.
        existing_catalog_zone_ids = set(
            CatalogZoneMembership.objects.filter(
                member_zone=instance,
                catalog_zone_id__in=pk_set,
            ).values_list("catalog_zone_id", flat=True)
        )
        for catalog_zone_id in pk_set - existing_catalog_zone_ids:
            membership = CatalogZoneMembership(
                catalog_zone_id=catalog_zone_id,
                member_zone=instance,
            )
            membership.validated_save()
    else:
        # Forward M2M operations (e.g. catalog_zone.members.add/set()):
        # `instance` is a CatalogZone, and `pk_set` contains member DNSZone IDs.
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

    # Skip Django's default bulk through-table insert because we've already
    # created all required through rows with validated_save().
    pk_set.clear()


@receiver(pre_delete, sender=CatalogZoneMembership)
def delete_member_ptr_record_on_membership_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Ensure derived catalog PTR records are removed with membership rows."""
    instance._delete_member_ptr_record()
