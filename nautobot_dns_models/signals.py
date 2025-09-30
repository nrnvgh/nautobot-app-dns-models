"""Signal handlers for DNS rule processing."""

import logging

from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from nautobot.dcim.models import Device, Interface
from nautobot.virtualization.models import VirtualMachine, VMInterface
from nautobot.ipam.models import Service

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

    if not instance._state.adding:  # Only for existing objects
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
@receiver(pre_save, sender=Service)
@receiver(pre_save, sender=VirtualMachine)
@receiver(pre_save, sender=VMInterface)
# TODO: Add signal handlers for future models:
# - Cluster (location changes affect VMs and their VMInterfaces)
def capture_object_change_state(sender, instance, **kwargs):
    """
    Capture object field changes to determine if DNS processing is needed.

    This consolidated handler works for any model type by using the model name
    as the debug context and detecting changes via the shared helper function.

    Location-aware processing: Device location changes trigger cascade updates
    for all interfaces on that device to handle location-scoped DNS rules.

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
@receiver(post_save, sender=Service)
@receiver(post_save, sender=VMInterface)
# TODO: Add post_save handlers for future models:
# TODO: Test module-based interfaces to ensure location/tenant extraction works correctly:
# - Interface in Module: interface.parent should walk up to device via module hierarchy
# - Interface in nested Module: interface.parent should handle multi-level module nesting
def handle_object_save(sender, instance, created, **kwargs):
    """
    Handle save events for objects that only need direct DNS rule processing.
    
    This is for objects that don't have dependent child objects that need cascade processing.
    Currently handles: Interface, Service, VMInterface.

    Args:
        sender: The model class that was saved
        instance: The actual object instance that was saved
        created: Boolean indicating if this was a new object
        **kwargs: Additional signal arguments
    """
    _process_dns_rules_if_needed(instance, created, context="object_save")


# TODO: Add post_save handlers for future models:
# - Cluster (location changes affect VMs and VMInterfaces)
@receiver(post_save, sender=Device)
@receiver(post_save, sender=VirtualMachine)
def handle_object_with_interfaces_save(sender, instance, created, **kwargs):
    """
    Handle Device and VirtualMachine save events to trigger DNS rule processing with cascade updates.

    This handler processes parent object DNS rules and also triggers cascade processing 
    of interface DNS rules when parent fields referenced in interface templates are changed.

    Supported relationships:
    - Device → Interface: Templates like {{ obj.device.* }} in Interface DNS rules
    - VirtualMachine → VMInterface: Templates like {{ obj.virtual_machine.* }} in VMInterface DNS rules

    Location-aware processing: Parent location changes trigger cascade updates for all 
    interfaces on that parent to handle location-scoped DNS rules.

    PERFORMANCE NOTE: Any parent field changes trigger processing of all interfaces
    on that parent. For parents with many interfaces, this has performance cost
    proportional to the interface count.

    Args:
        sender: The model class that was saved (Device or VirtualMachine)
        instance: The parent object instance that was saved
        created: Boolean indicating if this was a new object
        **kwargs: Additional signal arguments
    """
    model_name = sender._meta.model_name
    logger.debug(f"[SIGNAL] [handle_object_with_interfaces_save] {model_name} {instance} / {created=}")

    try:
        # Process parent object's DNS rules only if needed
        _process_dns_rules_if_needed(instance, created, context="object_with_interfaces_save")

        # Enhanced cascade processing for parent field changes
        # Skip cascade processing for newly created parents
        if created:
            return

        # If any parent object fields changed, process all interfaces belonging to this parent
        # This ensures interface DNS records with {{ obj.parent.* }} (or similar) templates get updated
        if getattr(instance, "_dns_needs_processing", False):
            # Process all interfaces belonging to this parent
            interfaces = instance.interfaces.all()
            if interfaces:
                # Get interface type name from first interface for logging
                interface_type_name = interfaces[0]._meta.model_name
                logger.debug(f"{model_name.title()} {instance} fields changed - processing all {interface_type_name}s for cascade updates")

                for interface in interfaces:
                    logger.debug(f"Processing {interface_type_name} {interface} due to {model_name} field changes")
                    dns_rule_engine.process_object(interface, created=False)
    except Exception as exc:
        # Log the error but don't let it break the original object save
        logger.error(f"[handle_object_with_interfaces_save] Failed to process DNS rules for {model_name.title()} {instance}: {exc}")


def _process_dns_rules_if_needed(instance, created, context="save"):
    """
    Helper function to process DNS rules for an object if needed.
    
    Args:
        instance: The object instance
        created: Boolean indicating if this was a new object
        context: String context for logging
    """
    # Check if DNS processing is needed (set by pre_save handler)
    should_process = created or getattr(instance, "_dns_needs_processing", False)

    logger.debug(f"[SIGNAL] [{context}] {instance} / {created=} / should_process={should_process}")

    if should_process:
        try:
            dns_rule_engine.process_object(instance, created=created)
        except Exception as exc:
            # Log the error but don't let it break the original object save
            logger.error(f"[SIGNAL] [{context}] Failed to process DNS rules for {instance}: {exc}")
    else:
        logger.debug(
            f"[SIGNAL] [{context}] Skipping DNS processing for {instance} - no relevant field changes"
        )




@receiver(post_delete, sender=Device)
@receiver(post_delete, sender=Interface)
@receiver(post_delete, sender=Service)
@receiver(post_delete, sender=VirtualMachine)
@receiver(post_delete, sender=VMInterface)
# TODO: Add post_delete handlers for future models:
# - Cluster (affects VMs and their VMInterfaces)
def handle_object_delete(sender, instance, **kwargs):
    """
    Handle object delete events to clean up associated DNS records.

    Location-aware cleanup: Removes DNS records created by location-scoped
    rules when objects are deleted.

    Args:
        sender: The model class that was deleted
        instance: The actual instance that was deleted
        **kwargs: Additional signal arguments
    """
    logger.debug(f"[SIGNAL] [handle_object_delete] {sender} / {instance}")

    try:
        dns_rule_engine.delete_dns_records_for_object(instance)
    except Exception as exc:
        # Log the error but don't let it break the original object deletion
        logger.error(f"Failed to clean up DNS records for {instance}: {exc}")


@receiver(m2m_changed, sender=Interface.ip_addresses.through)
@receiver(m2m_changed, sender=Service.ip_addresses.through)
@receiver(m2m_changed, sender=VMInterface.ip_addresses.through)
def handle_m2m_changed(sender, instance, action, pk_set, **kwargs):
    """
    Handle many-to-many relationship changes to trigger DNS rule processing.

    Location-aware processing: IP assignments trigger DNS rule evaluation
    using location-scoped rules based on the object's location:
      * interface.device.location,
      * service.device.location,
      * service.virtual_machine.cluster.location,
      * vminterface.virtual_machine.cluster.location
      * vminterface.virtual_machine.cluster.location

    This is specifically needed for through table changes where the post_save signal
    fires before the M2M relationship is updated.

    Args:
        sender: The intermediate model
        instance: The instance being modified (Interface, Service, or VMInterface)
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
    except Exception as exc:
        # Log the error but don't let it break the original operation
        logger.error(f"[SIGNAL] [handle_m2m_changed] Failed to process DNS rules for M2M change on {instance}: {exc}")
        # Don't re-raise - protect core IP assignment operations
