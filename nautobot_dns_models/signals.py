"""Signal handlers for DNS rule processing."""

import logging

from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver
from django.apps import apps
from nautobot.dcim.models import Device, Interface

from nautobot_dns_models.rule_engine import dns_rule_engine

logger = logging.getLogger(__name__)

# Get our app's label dynamically from the current module
# This should be safe since signals are imported in ready() after Django initialization
APP_LABEL = apps.get_containing_app_config(__name__).label


@receiver(post_save, sender=Device)
@receiver(post_save, sender=Interface)
def handle_object_save(sender, instance, created, **kwargs):
    """
    Handle object save events to trigger DNS rule processing.

    Args:
        sender: The model class that was saved
        instance: The actual instance that was saved
        created: Boolean indicating if this was a new object
        **kwargs: Additional signal arguments
    """
    # Don't process our own DNS models to avoid recursion
    if sender._meta.app_label == APP_LABEL:
        logger.debug(f"Skipping DNS rule processing for DNS model {sender.__name__}")
        return

    # Skip processing if this is a model we definitely don't care about
    # (This could be optimized later with a whitelist of content types)
    
    try:
        dns_rule_engine.process_object(instance, created=created)
    except Exception as e:
        # Log the error but don't let it break the original object save
        logger.error(f"Failed to process DNS rules for {instance}: {e}")


@receiver(post_delete, sender=Device)
@receiver(post_delete, sender=Interface)
def handle_object_delete(sender, instance, **kwargs):
    """
    Handle object delete events to clean up associated DNS records.

    Args:
        sender: The model class that was deleted
        instance: The actual instance that was deleted
        **kwargs: Additional signal arguments
    """
    # Don't process our own DNS models
    if sender._meta.app_label == APP_LABEL:
        logger.debug(f"Skipping DNS record cleanup for DNS model {sender.__name__}")
        return

    try:
        dns_rule_engine.delete_dns_records_for_object(instance)
    except Exception as e:
        # Log the error but don't let it break the original object deletion
        logger.error(f"Failed to clean up DNS records for {instance}: {e}")


@receiver(m2m_changed, sender=Interface.ip_addresses.through)
def handle_m2m_changed(sender, instance, action, pk_set, **kwargs):
    """
    Handle many-to-many relationship changes to trigger DNS rule processing.
    
    This is specifically needed for Interface.ip_addresses changes where
    the post_save signal fires before the M2M relationship is updated.

    Args:
        sender: The intermediate model (e.g., Interface.ip_addresses.through)
        instance: The instance being modified
        action: The type of update (e.g., 'post_add', 'post_remove', 'post_clear')
        pk_set: Set of primary keys affected
        **kwargs: Additional signal arguments
    """
    # Only process post_* actions (after the change is committed)
    if not action.startswith("post_"):
        return

    logger.debug(f"M2M change detected: {action} on {instance} (sender: {sender.__name__})")
    
    try:
        # Process the instance that had its relationships changed
        dns_rule_engine.process_object(instance, created=False)
    except Exception as e:
        # Log the error but don't let it break the original operation
        logger.error(f"Failed to process DNS rules for M2M change on {instance}: {e}")
