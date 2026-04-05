"""Signal handlers for DNS rule processing."""

import logging

from django.apps import apps as global_apps
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import IPAddressToInterface, Service
from nautobot.virtualization.models import VirtualMachine, VMInterface

from nautobot_dns_models.models import DNSRecord
from nautobot_dns_models.rules.engine import DNSRuleEngine

# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def _get_regexp_rule_model(apps):
    #
    # Check for the version 2 and 3 app labels, in that order.
    # NOTE: This plugin is currently untested with Nautobot 3.0.0.
    for app_label in ("nautobot_data_validation_engine", "data_validation"):
        try:
            return apps.get_model(app_label, "RegularExpressionValidationRule")
        except LookupError:
            continue
    return None


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

    if not instance._state.adding:  # pylint: disable=protected-access
        # Only for existing objects
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
                pass
            else:
                logger.debug(f"{debug_context.title()} {instance} - no relevant field changes detected")
                logger.debug(f"{debug_context.title()} {instance} all fields unchanged: {unchanged_fields}")
                pass

            return has_changes

        except model_class.DoesNotExist:
            # Shouldn't happen for existing objects, but handle gracefully
            logger.warning(
                "%s %s - could not find existing object for change detection", debug_context.title(), instance
            )
            return False
    else:
        # New objects always need processing
        # logger.debug(f"{debug_context.title()} {instance} - new object, will process DNS rules")
        return True


#
# XXX: We may not want to do this at all. Or, we may want to install simpler rules, like:
# XXX: A/AAAA: ^[0-9a-z-.]
def post_migrate_create_data_validation_rules(sender, apps=global_apps, **kwargs):
    """Create data validation rules for DNS models after database migration."""
    regexp_rule_model = _get_regexp_rule_model(apps)
    if not regexp_rule_model:
        logger.debug(
            "[SIGNAL] [post_migrate_create_data_validation_rules] [%s] Data validation rules engine is not installed, skipping rules",
            sender,
        )
        return

    logger.debug(
        "[SIGNAL] [post_migrate_create_data_validation_rules] [%s] Creating data validation rules for DNS models",
        sender,
    )

    regexes = {
        "Other": r"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9])$",
    }

    #
    # TODO: when we twiddle the class map code elsewhere, update this to use some of that.
    for record_class in DNSRecord.__subclasses__():
        record_type = record_class.__name__.replace("Record", "")
        regex = regexes.get(record_type, regexes["Other"])

        rule, created = regexp_rule_model.objects.get_or_create(
            name=f"RFC Compliance: DNS {record_type} Record Name",
            field="name",
            content_type_id=ContentType.objects.get_for_model(record_class).pk,
            regular_expression=regex,
            error_message=f"The name of the {record_type} record must be a valid DNS name.",
            enabled=False,
        )
        if created:
            logger.debug("Created data validation rule '%s'", rule.name)


#
# NOTE: do we want to explictly list other sender models here and, if so, which?
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
    instance._dns_needs_processing = has_model_field_changes(instance, debug_context=model_name)  # pylint: disable=protected-access


@receiver(post_save, sender=Interface)
@receiver(post_save, sender=Service)
@receiver(post_save, sender=VMInterface)
# TODO: Add post_save handlers for future models:
# TODO: Test module-based interfaces to ensure location/tenant extraction works correctly:
# - Interface in Module: interface.parent should walk up to device via module hierarchy
# - Interface in nested Module: interface.parent should handle multi-level module nesting
def handle_object_save(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
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
    logger.debug(f"[SIGNAL] [handle_object_save] {sender} / {instance} / {created=}")
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
        if instance._dns_needs_processing:
            # prefetch_related("ip_addresses") can be a significant performance optimization. In the
            # case where a device with 128 interfaces, each with 4 IPs, was renamed, the device save
            # time dropped from ~30s to under 5s (84% reduction) in local testing.
            interfaces = instance.interfaces.prefetch_related("ip_addresses")

            if interfaces:
                rule_engine = DNSRuleEngine()
                # Get interface type name from first interface for logging; all interfaces will
                # have the same type (e.g. Interface, VMInterface, etc.)
                interface_type_name = interfaces[0]._meta.model_name
                logger.debug(
                    "%s %s fields changed - processing all %s for cascade updates",
                    model_name.title(),
                    instance,
                    interface_type_name,
                )

                rule_engine.process_objects_pipeline(interfaces)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Log the error but don't let it break the original object save
        logger.error(
            "[handle_object_with_interfaces_save] Failed to process DNS rules for %s %s: %s",
            model_name.title(),
            instance,
            exc,
        )


def _process_dns_rules_if_needed(instance, created, context="save"):
    """
    Helper function to process DNS rules for an object if needed.

    Args:
        instance: The object instance
        created: Boolean indicating if this was a new object
        context: String context for logging
    """
    # Check if DNS processing is needed (set by pre_save handler)
    should_process = created or instance._dns_needs_processing

    logger.debug(f"[SIGNAL] [{context}] {instance} / {created=} / should_process={should_process}")

    if should_process:
        logger.debug(f"[SIGNAL] [{context}] Processing DNS rules for {instance}")
        try:
            DNSRuleEngine().process_object(instance, created=created)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Log the error but don't let it break the original object save
            logger.error("[SIGNAL] [%s] Failed to process DNS rules for %s: %s", context, instance, exc)
    else:
        logger.debug(f"[SIGNAL] [{context}] Skipping DNS processing for {instance} - no relevant field changes")


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
    logger.debug("[SIGNAL] [handle_object_delete] %s / %s", sender, instance)

    try:
        DNSRuleEngine().delete_dns_records_for_object(instance)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Log the error but don't let it break the original object deletion
        logger.error("Failed to clean up DNS records for %s: %s", instance, exc)


@receiver(post_save, sender=IPAddressToInterface)
def handle_ipaddresstointerface_save(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Handle IPAddressToInterface save events to trigger DNS rule processing."""
    logger.debug(f"[SIGNAL] [handle_ipaddresstointerface_save] {sender} / '{instance}' ({kwargs})")

    #
    # We pass created=False because while the IPAddressToInterface is a new object, the interface is not.
    # We want to process the interface, not the IPAddressToInterface.
    DNSRuleEngine().process_object(instance.interface, created=False)


@receiver(post_delete, sender=IPAddressToInterface)
def handle_ipaddresstointerface_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Handle IPAddressToInterface delete events to clean up associated DNS records."""
    logger.debug(f"[SIGNAL] [handle_ipaddresstointerface_delete] {sender} / {instance} ({kwargs})")
    DNSRuleEngine().process_object(instance.interface, created=False)


@receiver(m2m_changed, sender=Service.ip_addresses.through)
@receiver(m2m_changed, sender=IPAddressToInterface)
def handle_m2m_changed(sender, instance, action, **kwargs):  # pylint: disable=unused-argument
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
        DNSRuleEngine().process_object(instance, created=False)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Log the error but don't let it break the original operation
        logger.error(
            "[SIGNAL] [handle_m2m_changed] Failed to process DNS rules for M2M change on %s: %s", instance, exc
        )
        # Don't re-raise - protect core IP assignment operations
