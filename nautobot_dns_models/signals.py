"""Signal handlers for nautobot_dns_models."""

import logging
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed, post_save, pre_delete, pre_save
from django.dispatch import receiver
from nautobot.core.utils.data import render_jinja2
from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import IPAddress

from nautobot_dns_models.models import (
    AAAARecordModel,
    ARecordModel,
    CNAMERecordModel,
    DNSRule,
    DNSZoneModel,
    MXRecordModel,
    NSRecordModel,
    PTRRecordModel,
    TXTRecordModel,
)

# Set up logging
logger = logging.getLogger(__name__)
log_format = "%(asctime)s %(levelname)s %(name)s %(message)s"
logging.basicConfig(format=log_format, level=logging.DEBUG)

# Map record types to model classes
RECORD_MODELS = {
    "A": ARecordModel,
    "AAAA": AAAARecordModel,
    "CNAME": CNAMERecordModel,
    "MX": MXRecordModel,
    "NS": NSRecordModel,
    "PTR": PTRRecordModel,
    "TXT": TXTRecordModel,
}


def create_dns_record(rule, obj):
    """Create a DNS record based on the rule and object."""
    logger.debug(f"Creating DNS record for rule {rule.name} (obj: {obj} (type: {type(obj)}))")
    if hasattr(obj, "ip_addresses"):
        logger.debug(f"Object {obj} has ip_addresses: {obj.ip_addresses.all()}")
    else:
        logger.debug(f"Object {obj} does not have ip_addresses")

    try:
        # Render templates using Nautobot's renderer
        context = {"object": obj}
        logger.debug(f"Context: {context}")
        zone_name = render_jinja2(rule.zone_template, context)
        record_name = render_jinja2(rule.name_template, context)
        record_value = render_jinja2(rule.value_template, context)

        logger.debug(f"Running render_jinja2 for record_value: {rule.value_template} (context: {context})")
        # Get or validate zone
        try:
            zone = DNSZoneModel.objects.get(name=zone_name)
        except DNSZoneModel.DoesNotExist:
            logger.debug(f"Zone {zone_name} does not exist for rule {rule.name}")
            return

        # Get record model class
        model_class = RECORD_MODELS.get(rule.record_type)
        if not model_class:
            logger.debug(f"Invalid record type {rule.record_type} for rule {rule.name}")
            return

        # Prepare common fields
        record_data = {
            "name": record_name,
            "zone": zone,
            "ttl": rule.ttl,
        }

        # Add type-specific fields
        if rule.record_type in ["A", "AAAA"]:
            # For A/AAAA records, if we have an IPAddress object directly, use it
            if hasattr(obj, "address"):
                logger.debug(f"Object {obj} has address: {obj.address}")
                record_data["address"] = obj
            # Otherwise try to get the IP from the record_value template
            else:
                logger.debug(f"Object {obj} does not have address, trying to get IP from record_value: {record_value}")
                try:
                    uuid_obj = UUID(record_value)
                    a_record = IPAddress.objects.get(pk=uuid_obj)
                    record_data["address"] = a_record
                except (ValueError, IPAddress.DoesNotExist):
                    logger.debug(f"Invalid or non-existent IP address {record_value} for {rule.record_type} record")
                    return
        elif rule.record_type == "CNAME":
            record_data["alias"] = record_value
        elif rule.record_type == "MX":
            record_data["mail_server"] = record_value
            record_data["preference"] = rule.mx_preference
        elif rule.record_type == "NS":
            record_data["server"] = record_value
        elif rule.record_type == "PTR":
            record_data["ptrdname"] = record_value
        elif rule.record_type == "TXT":
            record_data["text"] = record_value

        # Create or update record
        logger.debug(f"Creating or updating record {record_name} in zone {zone_name} with data {record_data}")
        record, created = model_class.objects.update_or_create(name=record_name, zone=zone, defaults=record_data)

        action = "Created" if created else "Updated"
        logger.info(f"{action} {rule.record_type} record {record_name} in zone {zone_name}")

    except Exception as e:
        logger.debug(f"Error creating DNS record for rule {rule.name}: {str(e)}")


def delete_dns_record(rule, obj):
    """Delete DNS records based on the rule and object."""
    try:
        # Render templates using Nautobot's renderer
        context = {"object": obj}
        zone_name = render_jinja2(rule.zone_template, context)
        record_name = render_jinja2(rule.name_template, context)

        # Get zone
        try:
            zone = DNSZoneModel.objects.get(name=zone_name)
        except DNSZoneModel.DoesNotExist:
            logger.debug(f"Zone {zone_name} does not exist for rule {rule.name}")
            return

        # Get record model class
        record_class = RECORD_MODELS.get(rule.record_type)
        if not record_class:
            return

        # Find and delete matching records
        records = record_class.objects.filter(name=record_name, zone=zone)
        for record in records:
            record.delete()
            logger.info(f"Deleted {rule.record_type} record {record_name} in zone {zone_name}")

    except Exception as e:
        logger.debug(f"Error deleting DNS record for rule {rule.name}: {str(e)}")


def name_has_changed(instance, old_instance, receiver_name):
    """
    Check if an object's name has changed.

    Args:
        instance: The new instance being saved
        old_instance: The old instance from the database
        receiver_name: The name of the receiver function (e.g. 'pre_save')

    Returns:
        bool: True if name has changed, False if it hasn't
    """
    if old_instance.name == instance.name:
        logger.debug(f"[{receiver_name}] {instance.__class__.__name__} name unchanged")
        return False
    return True


def interface_has_changed(instance, old_instance, receiver_name):
    """
    Check if an interface's name or IP addresses have changed.

    Args:
        instance: The new instance being saved
        old_instance: The old instance from the database
        receiver_name: The name of the receiver function (e.g. 'pre_save')

    Returns:
        bool: True if name or IPs have changed, False if they haven't
    """
    # Check if name has changed using the existing function
    if name_has_changed(instance, old_instance, receiver_name):
        return True

    # Get old and new IP addresses
    old_ips = set(old_instance.ip_addresses.all())
    new_ips = set(instance.ip_addresses.all())
    logger.debug(f"[{receiver_name}] {old_ips=}, {new_ips=}")

    # Check if IPs have changed
    if old_ips != new_ips:
        logger.debug(f"[{receiver_name}] Interface IPs changed from {old_ips} to {new_ips}")
        return True

    logger.debug(f"[{receiver_name}] Interface {instance} unchanged, skipping")
    return False


@receiver(pre_save, sender=Interface)
def interface_pre_save(sender, instance, **kwargs):
    """When an Interface is about to be saved, handle DNS record cleanup.

    This handler is triggered before an Interface is saved and checks if it's being renamed
    or its IPs changed. If so, it deletes any existing DNS records so they can be recreated
    with the new name/IPs.
    """
    # Skip if this is a new object
    if not instance.pk:
        logger.debug("[interface_pre_save] Object is new, skipping")
        return

    logger.debug(f"[interface_pre_save] Handling interface changes for {instance} (sender: {sender})")

    try:
        # Get the old version of the object from the database
        old_instance = sender.objects.get(pk=instance.pk)
        logger.debug(f"[interface_pre_save] Old instance: {old_instance}")

        # If neither name nor IPs have changed, no need to update DNS records
        if not interface_has_changed(instance, old_instance, "interface_pre_save"):
            return

        # Get content type first and check for applicable rules
        content_type = ContentType.objects.get_for_model(sender)
        rules = DNSRule.objects.filter(content_type=content_type, enabled=True).order_by("priority")

        # If no rules apply to this content type, return early
        if not rules.exists():
            logger.debug(f"[interface_pre_save] No rules apply to content type '{content_type}', returning early")
            return

        for rule in rules:
            # Render templates for both old and new instances
            old_context = {"object": old_instance}
            new_context = {"object": instance}

            old_name = render_jinja2(rule.name_template, old_context)
            new_name = render_jinja2(rule.name_template, new_context)

            old_zone = render_jinja2(rule.zone_template, old_context)
            new_zone = render_jinja2(rule.zone_template, new_context)

            # If either the name or zone would change, delete the old record
            if old_name != new_name or old_zone != new_zone:
                logger.debug(
                    f"[interface_pre_save] Deleting old record for {rule.name} (old: {old_name}, new: {new_name})"
                )
                delete_dns_record(rule, old_instance)
            else:
                logger.debug(f"[interface_pre_save] No changes for {rule.name}, skipping")

    except Exception as e:
        logger.debug(f"Error handling interface changes for {instance}: {str(e)}")


@receiver(post_save, sender=Interface)
def interface_post_save(sender, instance, **kwargs):
    """When an Interface is saved, process any DNS rules that apply to it.

    This handler is triggered after an Interface is saved and processes any DNS rules
    that apply to the interface, creating or updating DNS records as needed.
    """
    logger.debug(f"[interface_post_save] Handling interface save for {instance} (sender: {sender})")

    try:
        # Get the old version of the object from the database
        old_instance = sender.objects.get(pk=instance.pk)
        logger.debug(f"[interface_post_save] Old instance: {old_instance}")

        # If neither name nor IPs have changed, no need to update DNS records
        if not interface_has_changed(instance, old_instance, "interface_post_save"):
            return

        content_type = ContentType.objects.get_for_model(sender)

        # Find applicable rules
        rules = DNSRule.objects.filter(content_type=content_type, enabled=True).order_by("priority")

        logger.debug(f"[interface_post_save] Found {rules.count()} applicable rules")

        # Process each rule
        for rule in rules:
            create_dns_record(rule, instance)

    except Exception as e:
        logger.debug(f"Error handling interface save for {instance}: {str(e)}")


@receiver(pre_save, sender=Device)
def device_pre_save(sender, instance, **kwargs):
    """When a Device is about to be saved, handle DNS record cleanup.

    This handler is triggered before a Device is saved and checks if it's being renamed.
    If so, it deletes any existing DNS records (both device and interface records) so they
    can be recreated with the new name.
    """
    # Skip if this is a new object
    if not instance.pk:
        logger.debug("[device_pre_save] Device is new, skipping")
        return

    logger.debug(f"[device_pre_save] Handling device rename for {instance} (sender: {sender})")

    try:
        # Get the old version of the object from the database
        old_instance = sender.objects.get(pk=instance.pk)
        logger.debug(f"[device_pre_save] Old device instance: {old_instance}")

        # If the name hasn't changed, no need to update DNS records
        if not name_has_changed(instance, old_instance, "pre_save"):
            return

        # Get content types for both Device and Interface
        device_ct = ContentType.objects.get_for_model(Device)
        interface_ct = ContentType.objects.get_for_model(Interface)

        # Get rules for both content types
        device_rules = DNSRule.objects.filter(content_type=device_ct, enabled=True).order_by("priority")

        interface_rules = DNSRule.objects.filter(content_type=interface_ct, enabled=True).order_by("priority")

        # If no rules apply to either content type, return early
        if not device_rules.exists() and not interface_rules.exists():
            logger.debug(
                "[device_pre_save] No rules apply to either Device or Interface content types, returning early"
            )
            return

        # Process device-based rules
        for rule in device_rules:
            # Render templates for both old and new instances
            old_context = {"object": old_instance}
            new_context = {"object": instance}

            old_name = render_jinja2(rule.name_template, old_context)
            new_name = render_jinja2(rule.name_template, new_context)

            old_zone = render_jinja2(rule.zone_template, old_context)
            new_zone = render_jinja2(rule.zone_template, new_context)

            # If either the name or zone would change, delete the old record
            if old_name != new_name or old_zone != new_zone:
                logger.debug(
                    f"[device_pre_save] Deleting old device record for {rule.name} (old: {old_name}, new: {new_name})"
                )
                delete_dns_record(rule, old_instance)
            else:
                logger.debug(f"[device_pre_save] No changes for device rule {rule.name}, skipping")

        # Process interface-based rules for each interface
        for old_interface in old_instance.interfaces.all():
            # Get the corresponding interface from the new instance
            try:
                new_interface = instance.interfaces.get(name=old_interface.name)
            except Interface.DoesNotExist:
                logger.debug(
                    f"[device_pre_save] Interface {old_interface.name} no longer exists on device {instance.name}"
                )
                continue

            for rule in interface_rules:
                # Render templates for both old and new instances
                old_context = {"object": old_interface}
                new_context = {"object": new_interface}

                old_name = render_jinja2(rule.name_template, old_context)
                new_name = render_jinja2(rule.name_template, new_context)

                old_zone = render_jinja2(rule.zone_template, old_context)
                new_zone = render_jinja2(rule.zone_template, new_context)

                logger.debug(f"[device_pre_save] Old interface name: {old_name}, new interface name: {new_name}")
                logger.debug(f"[device_pre_save] Old interface zone: {old_zone}, new interface zone: {new_zone}")

                # If either the name or zone would change, delete the old record
                if old_name != new_name or old_zone != new_zone:
                    logger.debug(
                        f"[device_pre_save] Deleting old interface record for {rule.name} (old: {old_name}, new: {new_name})"
                    )
                    delete_dns_record(rule, old_interface)
                else:
                    logger.debug(f"[device_pre_save] No changes for interface rule {rule.name}, skipping")

    except Exception as e:
        logger.debug(f"Error handling device rename for {instance}: {str(e)}")


@receiver(post_save, sender=Device)
def device_post_save(sender, instance, **kwargs):
    """When a Device is saved, process any DNS rules that apply to it and its interfaces.

    This handler is triggered after a Device is saved and processes any DNS rules
    that apply to both the device and its interfaces, creating or updating DNS records as needed.
    """
    logger.debug(f"[device_post_save] Handling device save for {instance} ({sender=}, {kwargs=})")

    try:
        # Get the old version of the object from the database
        old_instance = sender.objects.get(pk=instance.pk)
        logger.debug(f"[device_post_save] Old device instance: {old_instance}")

        # If the name hasn't changed, no need to update DNS records
        if not name_has_changed(instance, old_instance, "device_post_save"):
            return

        # Get content types for both Device and Interface
        device_ct = ContentType.objects.get_for_model(Device)
        interface_ct = ContentType.objects.get_for_model(Interface)

        # Get rules for both content types
        device_rules = DNSRule.objects.filter(content_type=device_ct, enabled=True).order_by("priority")

        interface_rules = DNSRule.objects.filter(content_type=interface_ct, enabled=True).order_by("priority")

        logger.debug(
            f"[device_post_save] Found {device_rules.count()} device rules and {interface_rules.count()} interface rules"
        )

        # Process device-based rules
        for rule in device_rules:
            create_dns_record(rule, instance)

        # Process interface-based rules for each interface
        for interface in instance.interfaces.all():
            for rule in interface_rules:
                create_dns_record(rule, interface)

    except Exception as e:
        logger.debug(f"Error handling device save for {instance}: {str(e)}")


@receiver(m2m_changed, sender=Interface.ip_addresses.through)
def handle_m2m_changed(sender, instance, action, reverse, model, pk_set, **kwargs):
    """Handle changes to Interface-IPAddress many-to-many relationships.

    This handler is triggered when the relationship between an Interface and its IP addresses
    changes, either through addition or removal of IPs.
    """
    logger.debug(f"[{sender}] M2M changed for {instance} ({action=}, {reverse=}, {model=}, {pk_set=})")

    if action in ["post_add", "post_remove"]:
        # We only care about Interface objects since they provide the naming context
        if reverse:
            # IPAddress is the instance, need to get the interfaces
            for interface_id in pk_set:
                interface = Interface.objects.get(pk=interface_id)
                logger.debug(f"Processing interface {interface} from reverse relation")
                process_interface_dns_rules(interface, action)
        else:
            # Interface is the instance
            logger.debug(f"Processing interface {instance} directly")
            process_interface_dns_rules(instance, action)


def process_interface_dns_rules(interface, action="post_add"):
    """Process DNS rules for an interface.

    This function processes all DNS rules that apply to an interface, either creating
    or deleting DNS records based on the action being performed.

    Args:
        interface: The interface to process
        action: The action being performed ("post_add" or "post_remove")
    """
    interface_ct = ContentType.objects.get_for_model(Interface)

    # Find applicable rules for Interface
    rules = DNSRule.objects.filter(content_type=interface_ct, enabled=True).order_by("priority")

    logger.debug(f"Found {rules.count()} applicable rules for interface {interface}")

    # Process rules
    for rule in rules:
        if action == "post_remove":
            delete_dns_record(rule, interface)
        elif action == "post_add":
            create_dns_record(rule, interface)
        else:
            logger.debug(f"Unsupported action '{action}' for interface {interface}, skipping")


@receiver(pre_delete)
def cleanup_dns_records(sender, instance, **kwargs):
    """When an object is deleted, clean up its DNS records.

    This handler is triggered before an object is deleted and removes any DNS records
    that were created by rules for this object.
    """
    logger.debug(f"[pre_delete] Cleaning up DNS records for {instance} (sender: {sender})")
    # Get the content type of the object being deleted
    content_type = ContentType.objects.get_for_model(sender)

    # Find any rules that apply to this content type
    applicable_rules = DNSRule.objects.filter(content_type=content_type)

    if not applicable_rules.exists():
        # No rules for this type of object, nothing to do
        return

    # For each rule type, find and delete matching records
    for rule in applicable_rules:
        record_model = RECORD_MODELS.get(rule.record_type)
        if record_model:
            # Find records that match this rule's pattern
            # We'll need to evaluate the rule's templates with the object's data
            # to find the matching records
            try:
                # Get the zone name for this object
                zone_name = rule.render_zone_template(instance)
                # Get the record name for this object
                record_name = rule.render_name_template(instance)

                # Find and delete matching records
                matching_records = record_model.objects.filter(name=record_name, zone__name=zone_name)

                # Log the deletions
                for record in matching_records:
                    record.delete()

            except Exception as e:
                # Log any errors but don't prevent the object deletion
                logger.debug(f"Error cleaning up DNS records for {instance}: {str(e)}")
