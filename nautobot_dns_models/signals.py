"""Signal receivers for Nautobot DNS Models."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from nautobot_dns_models.models import CatalogZoneMember, ensure_catalog_zone_records


@receiver(post_delete, sender=CatalogZoneMember)
def remove_catalog_member_record(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Withdraw the PTR that published a membership once the membership is gone.

    A receiver rather than a `CatalogZoneMember.delete()` override because `member_zone` cascades:
    deleting a member zone destroys its membership through Django's collector, which never calls
    `Model.delete()`. The write side stays in `save()`, where it can share the transaction that
    stores the membership.

    Stage 2 ruled out `pre_delete` for the immutability guards because raising inside the
    collector's atomic block poisons the request transaction. That finding does not apply here:
    this receiver only rewrites records, and `catalog_zone` being PROTECT means the catalog it
    dereferences is always still there.
    """
    ensure_catalog_zone_records(instance.catalog_zone)
