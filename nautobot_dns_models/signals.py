"""Signal handlers for DNS rule processing."""

import logging

from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from django.apps import apps
from nautobot.dcim.models import Device, Interface

from nautobot_dns_models.rule_engine import dns_rule_engine

logger = logging.getLogger(__name__)

# Get our app's label dynamically from the current module
# This should be safe since signals are imported in ready() after Django initialization
APP_LABEL = apps.get_containing_app_config(__name__).label


@receiver(pre_save, sender=Device)
def capture_device_state_before_save(sender, instance, **kwargs):
    """
    Capture Device state before save to detect field changes.

    This allows post_save handler to determine which fields changed
    without making additional database queries. Stores entire pre-save
    state for flexibility in tracking any field changes.

    Args:
        sender: The model class (Device)
        instance: The Device instance about to be saved
        **kwargs: Additional signal arguments
    """
    # Only capture state for existing devices (not new ones)
    if not instance._state.adding:
        try:
            old_device = Device.objects.get(pk=instance.pk)
            # Cache entire pre-save state for comprehensive field change detection
            instance._pre_save_state = old_device
            logger.debug(f"Captured pre-save state for {instance}")
        except Device.DoesNotExist:
            # Device might be new or in an inconsistent state, skip
            instance._pre_save_state = None

#
# NOTE: do we want to explictly list other sender models here and, if so, which?
# NOTE: We're waiting on resolution of https://github.com/nautobot/nautobot/issues/7728 for
# NOTE: full signal handling.
@receiver(post_save, sender=Interface)
def handle_interface_save(sender, instance, created, **kwargs):
    """
    Handle Interface save events to trigger DNS rule processing.

    Args:
        sender: The model class that was saved (Interface)
        instance: The actual Interface instance that was saved
        created: Boolean indicating if this was a new Interface
        **kwargs: Additional signal arguments
    """
    # Don't process our own DNS models to avoid recursion
    if sender._meta.app_label == APP_LABEL:
        logger.debug(f"Skipping DNS rule processing for DNS model {sender.__name__}")
        return

    logger.debug(f"handle_interface_save: {instance} / {created=}")

    try:
        dns_rule_engine.process_object(instance, created=created)
    except Exception as e:
        # Log the error but don't let it break the original object save
        logger.error(f"[handle_interface_save] Failed to process DNS rules for Interface {instance}: {e}")


@receiver(post_save, sender=Device)
def handle_device_save(sender, instance, created, **kwargs):
    """
    Handle Device save events to trigger DNS rule processing with cascade updates.

    This handler processes Device-based DNS rules and also triggers cascade
    processing of Interface DNS rules when device fields referenced in Interface
    templates are changed (e.g., device name).

    PERFORMANCE NOTE: Device name changes trigger processing of all interfaces
    on that device. For devices with many interfaces, this has performance cost
    proportional to the interface count.

    Args:
        sender: The model class that was saved (Device)
        instance: The actual Device instance that was saved
        created: Boolean indicating if this was a new Device
        **kwargs: Additional signal arguments
    """
    # Don't process our own DNS models to avoid recursion
    if sender._meta.app_label == APP_LABEL:
        logger.debug(f"Skipping DNS rule processing for DNS model {sender.__name__}")
        return

    logger.debug(f"handle_device_save: {instance} / {created=}")
    
    try:
        # Process Device-based DNS rules
        dns_rule_engine.process_object(instance, created=created)

        # Enhanced cascade processing for Device name changes
        # Skip cascade processing for newly created devices
        if created:
            return

        # Check if device fields changed using cached pre-save state
        if hasattr(instance, "_pre_save_state") and instance._pre_save_state is not None:
            old_state = instance._pre_save_state

            # Check for name changes (most common Interface template dependency)
            if old_state.name != instance.name:
                logger.debug(f"Device name changed from \"{old_state.name}\" to \"{instance.name}\" - processing interfaces")

                # Process all interfaces belonging to this device
                # This ensures Interface DNS records with {{ obj.device.name }} templates get updated
                for interface in instance.interfaces.all():
                    logger.debug(f"Processing interface {interface} due to device name change")
                    dns_rule_engine.process_object(interface, created=False)

            # Future: Can easily add other field change detection here
            # if old_state.location != instance.location:
            #     # Handle device location changes
            # if old_state.role != instance.role:
            #     # Handle device role changes
    except Exception as e:
        # Log the error but don't let it break the original object save
        logger.error(f"[handle_device_save] Failed to process DNS rules for Device {instance}: {e}")


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
