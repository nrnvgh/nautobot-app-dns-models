"""Signal receivers for Nautobot DNS Models."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from nautobot_dns_models.models import (
    CatalogZoneMembership,
    withdraw_member_ptr_record,
)


@receiver(post_delete, sender=CatalogZoneMembership)
def remove_catalog_member_ptr(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Withdraw the PTR that published a membership once the membership is gone.

    A receiver rather than a `delete()` override, because a membership also goes when its member
    zone is deleted and through `QuerySet.delete()`, including `DNSZone.catalogs.remove()` and
    `.clear()`, none of which call `Model.delete()`. Having a listener turns off the collector's
    fast-delete path, so every ORM delete sends this signal.
    """
    # Raise nothing here. The collector deletes inside an atomic block without a savepoint, so an
    # exception leaves any enclosing transaction able only to roll back.
    withdraw_member_ptr_record(instance.catalog_zone_id, instance.member_label)
