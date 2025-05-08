"""Signal handlers for nautobot_dns_models."""

import logging
from django.db.models.signals import post_save, pre_save, pre_delete, m2m_changed
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from nautobot.core.utils.data import render_jinja2
from uuid import UUID

from nautobot.extras.choices import LogLevelChoices
from nautobot.extras.models import JobResult
from nautobot.ipam.models import IPAddress
from nautobot.dcim.models import Device, Interface

from nautobot_dns_models.models import (
    DNSRule, DNSZoneModel, ARecordModel, AAAARecordModel, 
    CNAMERecordModel, MXRecordModel, NSRecordModel, 
    PTRRecordModel, TXTRecordModel
)

# Set up logging
logger = logging.getLogger(__name__)
log_format = "%(asctime)s %(levelname)s %(name)s %(message)s"
logging.basicConfig(format=log_format, level=logging.DEBUG)

# Map record types to model classes
RECORD_MODELS = {
    'A': ARecordModel,
    'AAAA': AAAARecordModel,
    'CNAME': CNAMERecordModel,
    'MX': MXRecordModel,
    'NS': NSRecordModel,
    'PTR': PTRRecordModel,
    'TXT': TXTRecordModel,
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
            'name': record_name,
            'zone': zone,
            'ttl': rule.ttl,
        }

        # Add type-specific fields
        if rule.record_type in ['A', 'AAAA']:
            # For A/AAAA records, if we have an IPAddress object directly, use it
            if hasattr(obj, 'address'):
                logger.debug(f"Object {obj} has address: {obj.address}")
                record_data['address'] = obj
            # Otherwise try to get the IP from the record_value template
            else:
                logger.debug(f"Object {obj} does not have address, trying to get IP from record_value: {record_value}")
                try:
                    uuid_obj = UUID(record_value)
                    a_record = IPAddress.objects.get(pk=uuid_obj)
                    record_data['address'] = a_record
                except (ValueError, IPAddress.DoesNotExist):
                    logger.debug(f"Invalid or non-existent IP address {record_value} for {rule.record_type} record")
                    return
        elif rule.record_type == 'CNAME':
            record_data['alias'] = record_value
        elif rule.record_type == 'MX':
            record_data['mail_server'] = record_value
            record_data['preference'] = rule.mx_preference
        elif rule.record_type == 'NS':
            record_data['server'] = record_value
        elif rule.record_type == 'PTR':
            record_data['ptrdname'] = record_value
        elif rule.record_type == 'TXT':
            record_data['text'] = record_value

        # Create or update record
        logger.debug(f"Creating or updating record {record_name} in zone {zone_name} with data {record_data}")
        record, created = model_class.objects.update_or_create(
            name=record_name,
            zone=zone,
            defaults=record_data
        )

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
        records = record_class.objects.filter(
            name=record_name,
            zone=zone
        )
        for record in records:
            record.delete()
            logger.info(f"Deleted {rule.record_type} record {record_name} in zone {zone_name}")

    except Exception as e:
        logger.debug(f"Error deleting DNS record for rule {rule.name}: {str(e)}")

@receiver(pre_save, sender=Interface)
def interface_pre_save(sender, instance, **kwargs):
    """
    When an Interface is about to be saved, check if it's being renamed and
    delete any existing DNS records so they can be recreated with the new name.
    """
    # Skip if this is a new object
    if not instance.pk:
        logger.debug(f"[interface_pre_save] Object is new, skipping")
        return

    logger.debug(f"[interface_pre_save] Handling object rename for {instance} (sender: {sender})")
    # Get content type first and check for applicable rules
    content_type = ContentType.objects.get_for_model(sender)
    rules = DNSRule.objects.filter(
        content_type=content_type,
        enabled=True
    ).order_by('priority')

    # If no rules apply to this content type, return early
    if not rules.exists():
        logger.debug(f"[interface_pre_save] No rules apply to content type '{content_type}', returning early") 
        return

    try:
        # Get the old version of the object from the database
        old_instance = sender.objects.get(pk=instance.pk)
        logger.debug(f"[interface_pre_save] Old instance: {old_instance}")

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
                logger.debug(f"[pre_save] Deleting old record for {rule.name} (old: {old_name}, new: {new_name})")
                delete_dns_record(rule, old_instance)
            else:
                logger.debug(f"[pre_save] No changes for {rule.name}, skipping")

    except Exception as e:
        logger.debug(f"Error handling rename for {instance}: {str(e)}")

@receiver(post_save, sender=Interface)
def interface_post_save(sender, instance, **kwargs):
    """When an Interface is saved, process any DNS rules that apply to it."""
    logger.debug(f"[interface_post_save] Handling interface save for {instance} (sender: {sender})")
    content_type = ContentType.objects.get_for_model(sender)

    # Find applicable rules
    rules = DNSRule.objects.filter(
        content_type=content_type,
        enabled=True
    ).order_by('priority')

    logger.debug(f"[interface_post_save] Found {rules.count()} applicable rules")

    # Process each rule
    for rule in rules:
        create_dns_record(rule, instance)

@receiver(pre_save, sender=Device)
def device_pre_save(sender, instance, **kwargs):
    """
    When a Device is about to be saved, check if it's being renamed and
    delete any existing DNS records so they can be recreated with the new name.
    This includes both device-based records and interface-based records that
    might use the device name in their templates.
    """
    # Skip if this is a new object
    if not instance.pk:
        logger.debug(f"[device_pre_save] Device is new, skipping")
        return

    logger.debug(f"[device_pre_save] Handling device rename for {instance} (sender: {sender})")
    
    # Get content types for both Device and Interface
    device_ct = ContentType.objects.get_for_model(Device)
    interface_ct = ContentType.objects.get_for_model(Interface)
    
    # Get rules for both content types
    device_rules = DNSRule.objects.filter(
        content_type=device_ct,
        enabled=True
    ).order_by('priority')
    
    interface_rules = DNSRule.objects.filter(
        content_type=interface_ct,
        enabled=True
    ).order_by('priority')

    # If no rules apply to either content type, return early
    if not device_rules.exists() and not interface_rules.exists():
        logger.debug(f"[device_pre_save] No rules apply to either Device or Interface content types, returning early") 
        return

    try:
        # Get the old version of the object from the database
        old_instance = sender.objects.get(pk=instance.pk)
        logger.debug(f"[device_pre_save] Old device instance: {old_instance}")

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
                logger.debug(f"[device_pre_save] Deleting old device record for {rule.name} (old: {old_name}, new: {new_name})")
                delete_dns_record(rule, old_instance)
            else:
                logger.debug(f"[device_pre_save] No changes for device rule {rule.name}, skipping")

        # Process interface-based rules for each interface
        for old_interface in old_instance.interfaces.all():
            # Get the corresponding interface from the new instance
            try:
                new_interface = instance.interfaces.get(name=old_interface.name)
            except Interface.DoesNotExist:
                logger.debug(f"[device_pre_save] Interface {old_interface.name} no longer exists on device {instance.name}")
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
                    logger.debug(f"[device_pre_save] Deleting old interface record for {rule.name} (old: {old_name}, new: {new_name})")
                    delete_dns_record(rule, old_interface)
                else:
                    logger.debug(f"[device_pre_save] No changes for interface rule {rule.name}, skipping")

    except Exception as e:
        logger.debug(f"Error handling device rename for {instance}: {str(e)}")

@receiver(post_save, sender=Device)
def device_post_save(sender, instance, **kwargs):
    """
    When a Device is saved, process any DNS rules that apply to it.
    This includes both device-based records and interface-based records that
    might use the device name in their templates.
    """
    logger.debug(f"[device_post_save] Handling device save for {instance} (sender: {sender})")
    
    # Get content types for both Device and Interface
    device_ct = ContentType.objects.get_for_model(Device)
    interface_ct = ContentType.objects.get_for_model(Interface)
    
    # Get rules for both content types
    device_rules = DNSRule.objects.filter(
        content_type=device_ct,
        enabled=True
    ).order_by('priority')
    
    interface_rules = DNSRule.objects.filter(
        content_type=interface_ct,
        enabled=True
    ).order_by('priority')

    logger.debug(f"[device_post_save] Found {device_rules.count()} device rules and {interface_rules.count()} interface rules")

    # Process device-based rules
    for rule in device_rules:
        create_dns_record(rule, instance)

    # Process interface-based rules for each interface
    for interface in instance.interfaces.all():
        for rule in interface_rules:
            create_dns_record(rule, interface)

@receiver(m2m_changed, sender=Interface.ip_addresses.through)
def handle_m2m_changed(sender, instance, action, reverse, model, pk_set, **kwargs):
    """Handle changes to Interface-IPAddress many-to-many relationships."""
    if action == "post_add":
        logger.debug(f"[{sender}] M2M changed for {instance} (action: {action}, reverse: {reverse}, model: {model}, pk_set: {pk_set})")
        
        # We only care about Interface objects since they provide the naming context
        if reverse:
            # IPAddress is the instance, need to get the interfaces
            for interface_id in pk_set:
                interface = Interface.objects.get(pk=interface_id)
                logger.debug(f"Processing interface {interface} from reverse relation")
                process_interface_dns_rules(interface)
        else:
            # Interface is the instance
            logger.debug(f"Processing interface {instance} directly")
            process_interface_dns_rules(instance)

def process_interface_dns_rules(interface):
    """Process DNS rules for an interface."""
    interface_ct = ContentType.objects.get_for_model(Interface)
    
    # Find applicable rules for Interface
    rules = DNSRule.objects.filter(
        content_type=interface_ct,
        enabled=True
    ).order_by('priority')
    
    logger.debug(f"Found {rules.count()} applicable rules for interface {interface}")
    
    # Process rules
    for rule in rules:
        create_dns_record(rule, interface)

@receiver(pre_delete)
def cleanup_dns_records(sender, instance, **kwargs):
    """
    When an object is deleted, find any DNS records that were created by rules for this object
    and delete them.
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
                matching_records = record_model.objects.filter(
                    name=record_name,
                    zone__name=zone_name
                )
                
                # Log the deletions
                for record in matching_records:
                    record.delete()
                    
            except Exception as e:
                # Log any errors but don't prevent the object deletion
                # We might want to create a JobResult to log this
                JobResult.objects.create(
                    name=f"DNS Record Cleanup for {instance}",
                    obj=instance,
                    status="failed",
                    data={
                        "error": str(e),
                        "rule": str(rule),
                    }
                ).log(
                    f"Failed to cleanup DNS records: {str(e)}",
                    level_choice=LogLevelChoices.LOG_ERROR
                ) 
        
        
    
    