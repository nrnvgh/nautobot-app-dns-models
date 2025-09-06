"""DNS Rule Processing Engine for Nautobot DNS Models."""

import logging
from typing import Any, Dict

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
#
# TODO Use TemplateSyntaxError instead of TemplateError? it required a line number argument.
from jinja2 import TemplateError

from nautobot.core.utils.data import render_jinja2

from nautobot_dns_models.models import (
    ARecord,
    AAAARecord,
    CNAMERecord,
    DNSRule,
    DNSRuleRecord,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    RECORD_TYPE_CHOICES,
    SRVRecord,
    TXTRecord,
)

logger = logging.getLogger(__name__)


# Mapping of record types to their corresponding model classes
RECORD_MODEL_MAPPING = {
    "A": ARecord,
    "AAAA": AAAARecord,
    "CNAME": CNAMERecord,
    "MX": MXRecord,
    "NS": NSRecord,
    "PTR": PTRRecord,
    "SRV": SRVRecord,
    "TXT": TXTRecord,
}


class DNSRuleEngine:
    """Engine for processing DNS rules and creating DNS records."""

    def process_object(self, source_obj: Any, created: bool = False) -> None:
        """
        Process an object against all applicable DNS rules.

        Args:
            source_obj: The object that triggered the rule processing
            created: Whether this is a newly created object
        """
        content_type = ContentType.objects.get_for_model(source_obj)
        rules = DNSRule.objects.filter(content_type=content_type, enabled=True).order_by("priority")
        
        logger.debug(f"Processing {source_obj} (type: {content_type}) - found {rules.count()} rules")
        
        if rules.count() == 0:
            logger.error(f"No DNS rules found for {content_type} - skipping DNS record processing for {source_obj}")
            return

        # Check if this object already has DNS records
        source_content_type = ContentType.objects.get_for_model(source_obj)
        existing_records = DNSRuleRecord.objects.filter(
            content_type=source_content_type,
            object_id=str(source_obj.pk)
        )
        logger.debug(f"DNS record lookup for {source_obj} (pk={source_obj.pk}, name='{getattr(source_obj, 'name', 'N/A')}'): found {existing_records.count()} existing records")
        
        if created or existing_records.count() == 0:
            # Create new DNS records for new objects OR objects with no existing records
            if created:
                logger.error(f"Taking CREATE path for {source_obj} (created={created}, existing_records={existing_records.count()})") 
            else:
                logger.debug(f"UPDATE scenario with no existing records - this may indicate first-time DNS processing for {source_obj}")
            for rule in rules:
                try:
                    result = self.create_dns_record_from_rule(rule, source_obj)
                    if result is None:
                        logger.debug(f"Skipped creating DNS record from rule {rule.name} for {source_obj} (template rendering failed)")
                except ValidationError as e:
                    logger.error(f"ValidationError while creating DNS record from rule {rule.name} for {source_obj}: {e}")
                    # Re-raise ValidationError to allow proper error handling upstream
                    raise
                except Exception as e:
                    logger.error(f"Failed to create DNS record from rule {rule.name} for {source_obj}: {e} (type={type(e)})")
                    raise
        else:
            # Update existing DNS records for modified objects
            logger.debug(f"Taking UPDATE path for {source_obj} (existing_records={existing_records.count()})")
            self.update_dns_records_for_object(source_obj)

    def create_dns_record_from_rule(self, rule: DNSRule, source_obj: Any) -> Any | None:
        """
        Create a DNS record based on a rule and source object.

        Args:
            rule: The DNS rule to apply
            source_obj: The source object to create a record for

        Returns:
            The created DNS record, or None if creation failed
        """
        logger.debug(f"create_dns_record_from_rule: {rule} / {source_obj}")
        try:
            # Prepare Jinja context
            context = {"obj": source_obj}

            # Render templates - if any fail, return None (don't create record)
            try:
                zone_name = self._render_template(rule.zone_template, context, "zone_template")
                record_name = self._render_template(rule.name_template, context, "name_template")
            except Exception as template_error:
                logger.debug(f"Template rendering failed for rule {rule.name} on {source_obj}: {template_error}")
                return None

            # Get the DNS zone
            try:
                zone = DNSZone.objects.get(name=zone_name)
            except DNSZone.DoesNotExist:
                logger.error(f"DNS zone '{zone_name}' not found for rule {rule.name}")
                return None

            # Get the record model class
            record_class = RECORD_MODEL_MAPPING.get(rule.record_type)
            if not record_class:
                logger.error(f"Unknown record type '{rule.record_type}' in rule {rule.name}")
                return None

            # Prepare base record data
            record_data = {
                "name": record_name,
                "zone": zone,
            }

            # Add record-type specific fields - if this fails, return None
            try:
                self._add_record_type_fields(rule, context, record_data)
            except Exception as template_error:
                logger.debug(f"Record-specific template rendering failed for rule {rule.name} on {source_obj}: {template_error}")
                return None

            # Create the DNS record
            dns_record = record_class.objects.create(**record_data)

            # Create the linking record
            DNSRuleRecord.objects.create(
                rule=rule,
                content_type=ContentType.objects.get_for_model(source_obj),
                object_id=str(source_obj.id),
                dns_record_content_type=ContentType.objects.get_for_model(dns_record),
                dns_record_object_id=str(dns_record.id),
            )

            logger.info(f"Created DNS record {dns_record} from rule {rule.name} for {source_obj}")
            return dns_record
        except ValidationError as e:
            logger.error(f"[2] ValidationError while creating DNS record from rule {rule.name} for {source_obj}: {e}")
            return None
        except Exception as e:
            logger.error(f"[2] Failed to create DNS record from rule {rule.name} for {source_obj}: {e} (type={type(e)})")
            return None

    def update_dns_records_for_object(self, source_obj: Any) -> None:
        """
        Update all DNS records created from a source object.
        If templates can't be rendered (e.g., IP removed), delete the DNS record.

        Args:
            source_obj: The source object whose DNS records should be updated
        """
        content_type = ContentType.objects.get_for_model(source_obj)
        rule_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=str(source_obj.id))

        for rule_record in rule_records:
            try:
                # Re-render templates with updated object data
                context = {"obj": source_obj}
                dns_record = rule_record.dns_record

                # If DNS record doesn't exist (was deleted due to previous template failure),
                # try to create a new one
                if dns_record is None:
                    logger.info(f"DNS record missing for rule {rule_record.rule.name} - attempting to recreate")
                    new_record = self.create_dns_record_from_rule(rule_record.rule, source_obj)
                    if new_record:
                        # Update the linking record to point to the new DNS record
                        rule_record.dns_record_content_type = ContentType.objects.get_for_model(new_record)
                        rule_record.dns_record_object_id = str(new_record.id)
                        rule_record.save()
                        logger.info(f"Recreated DNS record {new_record} for {source_obj}")
                    else:
                        logger.debug(f"Could not recreate DNS record for rule {rule_record.rule.name} - template still failing")
                        # If we can't recreate the record, delete the stale linking record
                        logger.info(f"Deleting stale DNSRuleRecord for rule {rule_record.rule.name}")
                        rule_record.delete()
                    continue

                # Try to update zone
                zone_name = self._render_template(rule_record.rule.zone_template, context, "zone_template")
                try:
                    zone = DNSZone.objects.get(name=zone_name)
                    dns_record.zone = zone
                except DNSZone.DoesNotExist:
                    logger.error(f"DNS zone '{zone_name}' not found for rule {rule_record.rule.name}")
                    continue

                # Try to update record name
                record_name = self._render_template(rule_record.rule.name_template, context, "name_template")
                dns_record.name = record_name

                # Try to update record-type specific fields
                record_data = {}
                self._add_record_type_fields(rule_record.rule, context, record_data)

                # Apply the updates
                for field, value in record_data.items():
                    setattr(dns_record, field, value)

                dns_record.save()
                logger.info(f"Updated DNS record {dns_record} for {source_obj}")

            except Exception as e:
                # If template rendering fails (e.g., IP removed), delete the DNS record
                logger.info(f"Template rendering failed for {rule_record.dns_record} - deleting record: {e}")
                try:
                    dns_record = rule_record.dns_record
                    rule_record.delete()  # Delete the linking record first
                    
                    # Only delete the DNS record if it exists
                    if dns_record is not None:
                        dns_record.delete()
                        logger.info(f"Deleted DNS record {dns_record} for {source_obj} due to template failure")
                    else:
                        logger.info(f"DNS record was already None, only deleted linking record for {source_obj}")
                except Exception as delete_error:
                    logger.error(f"Failed to delete DNS record {rule_record.dns_record}: {delete_error}")

    def delete_dns_records_for_object(self, source_obj: Any) -> None:
        """
        Delete all DNS records created from a source object.

        Args:
            source_obj: The source object whose DNS records should be deleted
        """
        content_type = ContentType.objects.get_for_model(source_obj)
        rule_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.id)

        for rule_record in rule_records:
            try:
                dns_record = rule_record.dns_record
                if dns_record:
                    dns_record.delete()
                    logger.info(f"Deleted DNS record {dns_record} for {source_obj}")
                rule_record.delete()
            except Exception as e:
                logger.error(f"Failed to delete DNS record for {source_obj}: {e}")

    def _render_template(self, template_str: str, context: Dict[str, Any], field_name: str) -> str:
        """
        Render a Jinja2 template with the given context.

        Args:
            template_str: The template string to render
            context: The context variables for rendering
            field_name: The name of the field being rendered (for error messages)

        Returns:
            The rendered template string

        Raises:
            TemplateError: If template rendering fails
        """
        try:
            result = render_jinja2(template_str, context)
            
            # Check if the result looks like a template error
            if result and "{{ no such element:" in result:
                logger.error(f"Template rendering failed for {field_name}: {result}")
                raise TemplateError(f"Template rendering failed for {field_name}: {result}")
            
            return result
        except TemplateError as e:
            logger.error(f"Caught exception: Template rendering failed for {field_name}: {e}")
            raise TemplateError(f"Failed to render {field_name}: {e}") from e

    def _add_record_type_fields(self, rule: DNSRule, context: Dict[str, Any], record_data: Dict[str, Any]) -> None:
        """
        Add record-type specific fields to the record data.

        Args:
            rule: The DNS rule containing the templates
            context: The Jinja context for rendering
            record_data: The dictionary to add fields to
        """
        record_type = rule.record_type

        if record_type in ["A", "AAAA"]:
            # A and AAAA records need address_id field (foreign key to IPAddress)
            if rule.value_template:
                address_id = self._render_template(rule.value_template, context, "value_template")
                record_data["address_id"] = address_id

        elif record_type == "CNAME":
            # CNAME records need alias field
            if rule.value_template:
                record_data["alias"] = self._render_template(rule.value_template, context, "value_template")

        elif record_type == "TXT":
            # TXT records need text field
            if rule.value_template:
                record_data["text"] = self._render_template(rule.value_template, context, "value_template")

        elif record_type == "PTR":
            # PTR records need ptrdname field
            if rule.value_template:
                record_data["ptrdname"] = self._render_template(rule.value_template, context, "value_template")

        elif record_type == "NS":
            # NS records need server field
            if rule.value_template:
                record_data["server"] = self._render_template(rule.value_template, context, "value_template")

        elif record_type == "MX":
            # MX records need mail_server and preference fields
            if rule.value_template:
                record_data["mail_server"] = self._render_template(rule.value_template, context, "value_template")
            if rule.preference_template:
                preference_str = self._render_template(rule.preference_template, context, "preference_template")
                record_data["preference"] = int(preference_str)

        elif record_type == "SRV":
            # SRV records need target, priority, weight, and port fields
            if rule.value_template:
                record_data["target"] = self._render_template(rule.value_template, context, "value_template")
            if rule.priority_template:
                priority_str = self._render_template(rule.priority_template, context, "priority_template")
                record_data["priority"] = int(priority_str)
            if rule.weight_template:
                weight_str = self._render_template(rule.weight_template, context, "weight_template")
                record_data["weight"] = int(weight_str)
            if rule.port_template:
                port_str = self._render_template(rule.port_template, context, "port_template")
                record_data["port"] = int(port_str)


# Global instance for use by signal handlers
dns_rule_engine = DNSRuleEngine()
