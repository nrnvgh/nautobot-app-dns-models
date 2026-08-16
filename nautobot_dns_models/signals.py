"""Signal receivers for Nautobot DNS Models."""

from django.db.models.signals import m2m_changed, post_delete
from django.dispatch import receiver

from nautobot_dns_models.models import CatalogZoneMembership, DNSZone, ensure_catalog_zone_records


@receiver(post_delete, sender=CatalogZoneMembership)
def remove_catalog_member_ptr(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Withdraw the PTR that published a membership once the membership is gone.

    A receiver rather than a `CatalogZoneMembership.delete()` override because `member_zone` cascades:
    deleting a member zone destroys its membership through Django's collector, which never calls
    `Model.delete()`. The write side stays in `save()`, where it can share the transaction that
    stores the membership.

    Stage 2 ruled out `pre_delete` for the immutability guards because raising inside the
    collector's atomic block poisons the request transaction. That finding does not apply here:
    this receiver only rewrites records, and `catalog_zone` being PROTECT means the catalog it
    dereferences is always still there.

    This covers `DNSZone.catalogs.remove()` and `.clear()` as well, since both delete the through
    rows through a queryset, which sends this signal for each one.
    """
    ensure_catalog_zone_records(instance.catalog_zone)


@receiver(m2m_changed, sender=CatalogZoneMembership)
def validate_catalog_membership(sender, instance, action, reverse, pk_set, **kwargs):  # pylint: disable=unused-argument
    """Hold `DNSZone.catalogs.add()` to the same rules as the membership it writes.

    The manager bulk-creates its rows, so neither `clean()` nor `save()` runs and every rule
    membership has would otherwise be reachable around. Core validates its own intermediate models
    from `pre_add` the same way (`nautobot.ipam.signals.vrf_prefix_associated`).

    Django sends `pre_add` inside an atomic block it opened without a savepoint, so a refusal
    raised here leaves an enclosing transaction unusable: a caller cannot catch it and carry on
    querying. Enrolling through `CatalogZoneMembership` reports the same faults as ordinary field
    errors, which is why that, rather than this manager, is the path the app itself uses.
    """
    if action != "pre_add" or not pk_set:
        return

    for membership in _build_pending_memberships(instance, reverse, pk_set):
        membership.full_clean()


@receiver(m2m_changed, sender=CatalogZoneMembership)
def publish_added_catalog_members(sender, instance, action, reverse, pk_set, **kwargs):  # pylint: disable=unused-argument
    """Publish member PTR records for memberships the manager wrote, as `save()` does for its own."""
    if action != "post_add" or not pk_set:
        return

    for catalog_zone in _affected_catalog_zones(instance, reverse, pk_set):
        ensure_catalog_zone_records(catalog_zone)


def _build_pending_memberships(instance, reverse, pk_set):
    """Build the unsaved memberships an `add()` is about to write, whichever end it was called on."""
    zones = DNSZone.objects.filter(pk__in=pk_set)
    if reverse:
        return [CatalogZoneMembership(catalog_zone=instance, member_zone=zone) for zone in zones]
    return [CatalogZoneMembership(catalog_zone=zone, member_zone=instance) for zone in zones]


def _affected_catalog_zones(instance, reverse, pk_set):
    """Return the catalogs whose published records an `add()` changed."""
    if reverse:
        return [instance]
    return DNSZone.objects.filter(pk__in=pk_set)
