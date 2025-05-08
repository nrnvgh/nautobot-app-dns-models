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


def get_zone_for_rule(rule, context):
    """
    Get the DNS zone for a rule based on its zone template.
    
    Args:
        rule: The DNSRule instance
        context: The context dictionary for template rendering
        
    Returns:
        DNSZoneModel or None: The zone if found, None if not found or error
    """
    try:
        zone_name = render_jinja2(rule.zone_template, context)
        return DNSZoneModel.objects.get(name=zone_name)
    except DNSZoneModel.DoesNotExist:
        logger.debug(f"Zone {zone_name} does not exist for rule {rule.name}")
        return None
    except Exception as e:
        logger.debug(f"Error getting zone for rule {rule.name}: {str(e)}")
        return None


def cleanup_dns_records(obj):
    """
    Clean up DNS records associated with an object.
    
    This function handles both deletion and IP changes by:
    1. Finding all DNS rules that apply to the object's type
    2. Rendering the templates to get the record names and zones
    3. Deleting any matching records
    
    Args:
        obj: The object (Device or Interface) whose DNS records should be cleaned up
    """
    logger.debug(f"[cleanup_dns_records] Cleaning up DNS records for {obj}")
    try:
        # Get content type for the object
        content_type = ContentType.objects.get_for_model(obj)
        
        # Find applicable rules
        rules = DNSRule.objects.filter(content_type=content_type, enabled=True)
        
        for rule in rules:
            logger.debug(f"[cleanup_dns_records] Processing rule {rule.name}")
            try:
                # Render templates to get record details
                context = {"object": obj}
                record_name = render_jinja2(rule.name_template, context)
                
                # Get the zone
                zone = get_zone_for_rule(rule, context)
                if not zone:
                    continue
                
                # Get the record model class
                record_class = RECORD_MODELS.get(rule.record_type)
                if not record_class:
                    logger.debug(f"Invalid record type {rule.record_type} for rule {rule.name}")
                    continue
                
                # Find and delete matching records
                records = record_class.objects.filter(name=record_name, zone=zone)
                for record in records:
                    record.delete()
                    logger.info(f"Deleted {rule.record_type} record {record_name} in zone {zone.name}")
                    
            except Exception as e:
                logger.debug(f"Error processing rule {rule.name}: {str(e)}")
                continue
                
    except Exception as e:
        logger.debug(f"Error cleaning up DNS records for {obj}: {str(e)}")


def create_dns_records(obj):
    """
    Create DNS records for an object based on its current state.
    
    This function:
    1. Finds all DNS rules that apply to the object's type
    2. Renders the templates to get the record names and zones
    3. Creates new records based on the current state
    
    Args:
        obj: The object (Device or Interface) whose DNS records should be created
    """
    logger.debug(f"[create_dns_records] Creating DNS records for {obj}")
    try:
        # Get content type for the object
        content_type = ContentType.objects.get_for_model(obj)
        
        # Find applicable rules
        rules = DNSRule.objects.filter(content_type=content_type, enabled=True)
        
        for rule in rules:
            logger.debug(f"[create_dns_records] Processing rule {rule.name} (value_template: {rule.value_template})")
            try:
                # Render templates to get record details
                context = {"object": obj}
                record_name = render_jinja2(rule.name_template, context)
                record_value = render_jinja2(rule.value_template, context)
                logger.debug(f"[create_dns_records] {record_name=} {record_value=}")
                
                # Skip if no record value was returned
                if not record_value:
                    logger.debug(f"No value returned from template for rule {rule.name}, skipping")
                    continue
                
                # Get the zone
                zone = get_zone_for_rule(rule, context)
                if not zone:
                    continue
                
                logger.debug(f"[create_dns_records] Zone: {zone}")
                # Get the record model class
                record_class = RECORD_MODELS.get(rule.record_type)
                if not record_class:
                    logger.debug(f"Invalid record type {rule.record_type} for rule {rule.name}")
                    continue
                
                # Prepare record data
                record_data = {
                    "name": record_name,
                    "zone": zone,
                    "ttl": rule.ttl,
                }
                
                logger.debug(f"[create_dns_records] Record data (stage 1): {record_data}")
                # Add type-specific fields
                if rule.record_type in ["A", "AAAA"]:
                    logger.debug(f"[create_dns_records] Record type: {rule.record_type}")
                    # For A/AAAA records, if we have an IPAddress object directly, use it
                    if hasattr(obj, "address"):
                        logger.debug(f"[create_dns_records] Address object: '{obj}'")
                        record_data["address"] = obj
                    # Otherwise try to get the IP from the record_value template
                    else:
                        try:
                            uuid_obj = UUID(record_value)
                            record_data["address"] = IPAddress.objects.get(pk=uuid_obj)
                            logger.debug(f"[create_dns_records] Address object from DB: '{record_data['address']}'")
                        except ValueError:
                            #
                            # In the basic {{ interface.ip_addresses }} case, if there are no IPs on the interface,
                            # the value_template will return '{{ no such element: None[&#39;id&#39;] }}', which obviously
                            # isn't a UUID.
                            #
                            # FIXME: See if there's a template which can properly trap for this, but it's not the
                            # FIXME: end of the world if not, it's just a little untidy.
                            #
                            logger.debug(f"Invalid UUID '{record_value}' ({rule.record_type} record)")
                            continue
                        except IPAddress.DoesNotExist:
                            logger.debug(f"No IP address found for UUID '{record_value}' ({rule.record_type} record)")
                            continue
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
                record, created = record_class.objects.update_or_create(
                    name=record_name,
                    zone=zone,
                    defaults=record_data
                )
                
                action = "Created" if created else "Updated"
                logger.info(f"{action} {rule.record_type} record {record_name} in zone {zone.name}")
                
            except Exception as e:
                logger.debug(f"Error processing rule {rule.name}: {str(e)}")
                continue
                
    except Exception as e:
        logger.debug(f"Error creating DNS records for {obj}: {str(e)}")


@receiver(m2m_changed, sender=Interface.ip_addresses.through)
def handle_interface_ip_changes(sender, instance, action, pk_set, **kwargs):
    """
    Handle changes to interface IP addresses.
    
    This signal handler is triggered when IP addresses are added to or removed from
    an interface. It ensures that DNS records are properly updated to reflect these changes.
    
    Args:
        sender: The model class that triggered the signal
        instance: The Interface instance being modified
        action: The type of change (pre_add, post_add, pre_remove, post_remove, pre_clear, post_clear)
        pk_set: Set of primary keys of the related objects being added/removed
    """
    logger.debug(f"[m2m_changed] Interface IP change detected: {action} for interface {instance}")
    
    if action == "pre_clear":
        logger.debug(f"[m2m_changed] pre_clear triggered for interface {instance}")
        return
        
    if action == "post_clear":
        logger.debug(f"[m2m_changed] post_clear triggered for interface {instance}")
        return
        
    if action == "post_add":
        logger.debug(f"[m2m_changed] post_add triggered for interface {instance}")
        # Clean up existing records and create new ones
        cleanup_dns_records(instance)
        create_dns_records(instance)
        
    elif action == "post_remove":
        logger.debug(f"[m2m_changed] post_remove triggered for interface {instance}")
        # Clean up existing records and create new ones
        cleanup_dns_records(instance)
        create_dns_records(instance)
