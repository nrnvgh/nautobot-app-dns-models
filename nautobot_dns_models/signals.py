"""Signal handlers for DNS rule processing."""

import logging

from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from jinja2 import TemplateError
from nautobot.dcim.models import Device, Interface

from nautobot_dns_models.rule_engine import dns_rule_engine

logger = logging.getLogger(__name__)


def has_model_field_changes(instance, debug_context="object"):
    """
    Determine if any model fields have changed for an existing object.

    Compares all model fields between current instance and database state,
    treating None and empty string as equivalent to avoid false positives
    from Django form processing.

    Args:
        instance: The model instance being saved (must have pk for existing objects)
        debug_context: Context string for debug logging (e.g., "interface", "device")

    Returns:
        bool: True if any fields have changed, False otherwise
    """

    # Normalize None and empty string as equivalent (common Django form behavior)
    def normalize_value(value):
        return value if value not in (None, "") else None

    if instance.pk:  # Only for existing objects
        try:
            model_class = type(instance)
            old_instance = model_class.objects.get(pk=instance.pk)

            changed_fields = []
            unchanged_fields = []

            # Check all model fields for changes
            for field in instance._meta.fields:
                old_value = getattr(old_instance, field.name, None)
                new_value = getattr(instance, field.name, None)

                old_normalized = normalize_value(old_value)
                new_normalized = normalize_value(new_value)

                if old_normalized != new_normalized:
                    changed_fields.append(f"{field.name}: '{old_value}' → '{new_value}'")
                else:
                    unchanged_fields.append(field.name)

            # Debug logging showing field change analysis
            has_changes = len(changed_fields) > 0
            if has_changes:
                logger.debug(f"{debug_context.title()} {instance} fields changed: {changed_fields}")
                logger.debug(f"{debug_context.title()} {instance} fields unchanged: {unchanged_fields}")
            else:
                logger.debug(f"{debug_context.title()} {instance} - no relevant field changes detected")
                logger.debug(f"{debug_context.title()} {instance} all fields unchanged: {unchanged_fields}")

            return has_changes

        except model_class.DoesNotExist:
            # Shouldn't happen for existing objects, but handle gracefully
            logger.warning(f"{debug_context.title()} {instance} - could not find existing object for change detection")
            return False
    else:
        # New objects always need processing
        logger.debug(f"{debug_context.title()} {instance} - new object, will process DNS rules")
        return True


#
# NOTE: do we want to explictly list other sender models here and, if so, which?
# NOTE: We're waiting on resolution of https://github.com/nautobot/nautobot/issues/7728 for
# NOTE: full signal handling.


@receiver(pre_save, sender=Device)
@receiver(pre_save, sender=Interface)
def capture_object_change_state(sender, instance, **kwargs):
    """
    Capture object field changes to determine if DNS processing is needed.

    This consolidated handler works for any model type by using the model name
    as the debug context and detecting changes via the shared helper function.

    Args:
        sender: The model class being saved (Device, Interface, etc.)
        instance: The model instance being saved
        **kwargs: Additional signal arguments
    """
    model_name = sender._meta.model_name
    logger.debug(f"[SIGNAL] [capture_object_change_state] {model_name}: {instance}")
    # Use helper to detect changes and set flag for post_save handler
    instance._dns_needs_processing = has_model_field_changes(instance, debug_context=model_name)


@receiver(post_save, sender=Interface)
def handle_interface_save(sender, instance, created, **kwargs):
    """
    Handle Interface save events to trigger DNS rule processing.

    Only processes DNS rules if interface fields changed (determined by pre_save handler)
    or if this is a newly created interface.

    Args:
        sender: The model class that was saved (Interface)
        instance: The actual Interface instance that was saved
        created: Boolean indicating if this was a new Interface
        **kwargs: Additional signal arguments
    """
    # Check if DNS processing is needed (set by pre_save handler)
    should_process = created or getattr(instance, "_dns_needs_processing", False)

    logger.debug(f"[SIGNAL] [handle_interface_save] {instance} / {created=} / should_process={should_process}")

    if should_process:
        try:
            dns_rule_engine.process_object(instance, created=created)
        except Exception as e:
            # Log the error but don't let it break the original object save
            logger.error(f"[SIGNAL] [handle_interface_save] Failed to process DNS rules for Interface {instance}: {e}")
    else:
        logger.debug(
            f"[SIGNAL] [handle_interface_save] Skipping DNS processing for {instance} - no relevant field changes"
        )


@receiver(post_save, sender=Device)
def handle_device_save(sender, instance, created, **kwargs):
    """
    Handle Device save events to trigger DNS rule processing with cascade updates.

    This handler processes Device-based DNS rules and also triggers cascade
    processing of Interface DNS rules when any device fields referenced in Interface
    templates are changed (e.g., device name, location, role, etc.).

    PERFORMANCE NOTE: Any device field changes trigger processing of all interfaces
    on that device. For devices with many interfaces, this has performance cost
    proportional to the interface count.

    Args:
        sender: The model class that was saved (Device)
        instance: The actual Device instance that was saved
        created: Boolean indicating if this was a new Device
        **kwargs: Additional signal arguments
    """
    logger.debug(f"[SIGNAL] [handle_device_save] {instance} / {created=}")

    try:
        # Process Device-based DNS rules only if needed
        if created or getattr(instance, "_dns_needs_processing", False):
            dns_rule_engine.process_object(instance, created=created)
        else:
            logger.debug(f"Device {instance} - no DNS processing needed, no field changes detected")

        # Enhanced cascade processing for Device field changes
        # Skip cascade processing for newly created devices
        if created:
            return

        # If any device fields changed, process all interfaces belonging to this device
        # This ensures Interface DNS records with {{ obj.device.* }} templates get updated
        if getattr(instance, "_dns_needs_processing", False):
            logger.debug(f"Device {instance} fields changed - processing all interfaces for cascade updates")

            # Process all interfaces belonging to this device
            for interface in instance.interfaces.all():
                logger.debug(f"Processing interface {interface} due to device field changes")
                dns_rule_engine.process_object(interface, created=False)
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
    logger.debug(f"[SIGNAL] [handle_object_delete] {sender} / {instance}")

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

    logger.debug(f"[SIGNAL] [handle_m2m_changed] {action} on {instance} (sender: {sender.__name__})")

    try:
        # Process the instance that had its relationships changed
        logger.debug(f"[SIGNAL] [handle_m2m_changed] Processing M2M change on {instance}")
        dns_rule_engine.process_object(instance, created=False)
    except Exception as e:
        # Log the error but don't let it break the original operation
        logger.error(f"Failed to process DNS rules for M2M change on {instance}: {e}")
