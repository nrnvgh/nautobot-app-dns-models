"""DNS Rule Processing Engine for Nautobot DNS Models."""

import logging
from collections import defaultdict
from typing import Any, Dict

from django.contrib.contenttypes.models import ContentType
from django.db import models
from jinja2 import TemplateError
from nautobot.apps.utils import render_jinja2

from nautobot_dns_models.exceptions import DNSTemplateEmptyError
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CNAMERecord,
    DNSRule,
    DNSRuleRecord,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
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
        # Get all applicable rules for this object type
        rules = self._get_applicable_rules(source_obj)
        rules_count = rules.count()

        if rules_count == 0:
            logger.debug(f"No DNS rules found for {content_type} - skipping DNS record processing for {source_obj}")
            return

        # Check if this object already has DNS records
        logger.debug(f"Processing {source_obj} (type: {content_type}) - found {rules_count} rules")
        existing_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=str(source_obj.pk))

        # Check existing record count once (serves both logging and conditional logic)
        existing_count = existing_records.count()
        logger.debug(
            f"DNS record lookup for {source_obj} (pk={source_obj.pk}, name=\"{getattr(source_obj, 'name', 'N/A')}\"): found {existing_count} existing records"
        )

        if created or existing_count == 0:
            # Create new DNS records for new objects OR objects with no existing records
            if created:
                logger.debug(
                    f"Taking CREATE path for {source_obj} (created={created}, existing_records={existing_count})"
                )
            else:
                logger.debug(
                    f"UPDATE scenario with no existing records - this may indicate first-time DNS processing for {source_obj}"
                )
            self.create_dns_records_for_object(source_obj, rules)
        else:
            # Update existing DNS records for modified objects
            logger.debug(f"Taking UPDATE path for {source_obj} (existing_records={existing_count})")
            self.update_dns_records_for_object(source_obj, rules)

    def create_dns_records_for_object(self, source_obj: Any, applicable_rules: models.QuerySet) -> None:
        """
        Create DNS records for an object by processing all applicable rules.

        Uses same exception handling pattern as update_dns_records_for_object
        for consistent multi-rule processing.

        Args:
            source_obj: The source object to create DNS records for
            applicable_rules: Pre-fetched QuerySet of applicable rules
        """
        logger.debug(f"Creating DNS records for {source_obj}")

        for rule in applicable_rules:
            try:
                created_records = self.create_dns_record_from_rule(rule, source_obj)
                if not created_records:
                    logger.debug(f"No records created from rule {rule.name} for {source_obj}")
                else:
                    logger.debug(f"Created {len(created_records)} DNS records from rule {rule.name} for {source_obj}")
            except (
                TemplateError,
                DNSTemplateEmptyError,
                DNSZone.DoesNotExist,
                ValueError,
            ) as exc:
                # Template/data errors - don't stop other rules
                logger.warning(f"Rule {rule.name} failed for {source_obj}: {exc}")
                continue

    def create_dns_record_from_rule(self, rule: DNSRule, source_obj: Any) -> list[Any]:
        """
        Create one or more DNS records based on a rule and source object.

        Now aligned with update reconciliation pattern - uses shared helper methods
        for consistent template rendering, zone lookup, and record creation logic.

        Args:
            rule: The DNS rule to apply
            source_obj: The source object to create a record for

        Returns:
            List of created DNS records (empty list if creation failed)

        Note:
            Jinja2 exceptions bubble up naturally for proper error handling.
            Empty result indicates template/data issues, not programming errors.
        """
        logger.debug(f"create_dns_record_from_rule: {rule} / {source_obj}")

        # Calculate what DNS records should exist (reuses update logic)
        desired_record_data_list = self._calculate_desired_record_data(rule, source_obj)
        if not desired_record_data_list:
            logger.debug(f"No record data generated for rule {rule.name}")
            return []

        # Create DNS records and tracking records (reuses update logic)
        created_records = self._create_records_from_data(rule, source_obj, desired_record_data_list)

        logger.debug(f"Created {len(created_records)} DNS records from rule {rule.name} for {source_obj}")
        return created_records

    def update_dns_records_for_object(self, source_obj: Any, applicable_rules: models.QuerySet) -> None:
        """
        Update DNS records for an object by reconciling current vs desired state.

        Uses reconciliation pattern: compare what should exist vs what does exist,
        then make minimal changes to achieve desired state.

        Args:
            source_obj: The source object whose DNS records should be updated
            applicable_rules: Pre-fetched QuerySet of applicable rules
        """
        logger.debug(f"Updating DNS records for {source_obj}")

        # Clean up records from rules that are no longer applicable
        self._cleanup_orphaned_records(source_obj, applicable_rules)

        for rule in applicable_rules:
            try:
                logger.debug(f"Reconciling records for rule {rule.name} on {source_obj}")
                self._reconcile_records_for_rule(rule, source_obj)
            except (
                TemplateError,
                DNSTemplateEmptyError,
                DNSZone.DoesNotExist,
                ValueError,
            ) as exc:
                # Expected template/data errors - don't stop other rules
                logger.warning(f"Update failed for rule {rule.name} on {source_obj}: {exc}")
                # Clean up existing records for this failed rule
                self._cleanup_records_for_rule(rule, source_obj)
                continue

    def _get_object_location(self, source_obj: Any) -> Any:
        """
        Extract location from source object for location-scoped rule resolution.

        Location extraction logic:
        - Device: device.location (required field in Nautobot)
        - Interface: interface.device.location (device.location is required)
        - VirtualMachine: vm.cluster.location (future)
        - VMInterface: vminterface.virtual_machine.cluster.location (future)
        - Service: None (global scope for anycast) (future)
        - InterfaceRedundancyGroup: None (complex multi-location) (future)

        Args:
            source_obj: The object to extract location from

        Returns:
            Location object or None if object type is not location-aware
        """
        # Device objects have direct location (required field)
        if hasattr(source_obj, "location"):
            return source_obj.location

        # Interface objects get location from device (device.location is required)
        if hasattr(source_obj, "device"):
            return source_obj.device.location

        # TODO: Add future model location extraction:
        # - VirtualMachine: return source_obj.cluster.location if hasattr(source_obj, "cluster")
        # - VMInterface: return source_obj.virtual_machine.cluster.location
        # - Service: return None (global scope for anycast)
        # - InterfaceRedundancyGroup: return None (complex multi-location scenario)

        # Object type is not location-aware
        return None

    def _get_object_tenant(self, source_obj: Any) -> Any:
        """
        Extract tenant from source object for tenant-scoped rule resolution.

        Tenant extraction logic:
        - Device: device.tenant (optional field in Nautobot)
        - Interface: interface.device.tenant (inherited from device)
        - VirtualMachine: vm.tenant (future)
        - VMInterface: vminterface.virtual_machine.tenant (future)
        - Service: service.tenant (future)
        - Other objects: None (no tenant awareness)

        Args:
            source_obj: The object to extract tenant from

        Returns:
            Tenant object or None if object has no tenant or type is not tenant-aware
        """
        # Device objects have direct tenant (optional field)
        if hasattr(source_obj, "tenant"):
            return source_obj.tenant

        # Interface objects get tenant from device (device.tenant is optional)
        if hasattr(source_obj, "device") and hasattr(source_obj.device, "tenant"):
            return source_obj.device.tenant

        # TODO: Add future model tenant extraction:
        # - VirtualMachine: return source_obj.tenant if hasattr(source_obj, "tenant")
        # - VMInterface: return source_obj.virtual_machine.tenant
        # - Service: return source_obj.tenant (for anycast services)

        # Object type is not tenant-aware or has no tenant assigned
        return None

    def _get_applicable_rules(self, source_obj: Any) -> models.QuerySet:
        """
        Get all DNS rules that apply to the given source object.

        Tenant+Location-scoped rule resolution with per-record-type precedence:
        1. For each record type, prefer most specific rule in this order:
           a. Location+Tenant specific (most specific)
           b. Location specific (location-wide, any tenant)
           c. Tenant specific (tenant-wide, any location)
           d. Global (any tenant, any location)
        2. Different record types can use different rule sources
        3. Location-first precedence: locations are more specific than tenants

        Args:
            source_obj: The object to find applicable rules for

        Returns:
            QuerySet of applicable DNSRule objects
        """
        content_type = ContentType.objects.get_for_model(source_obj)
        object_location = self._get_object_location(source_obj)
        object_tenant = self._get_object_tenant(source_obj)

        # Early return for objects with no location or tenant - only global rules can apply
        if object_location is None and object_tenant is None:
            logger.debug(f"Using global rules for {source_obj} (no location, no tenant)")
            return DNSRule.objects.filter(
                content_type=content_type, location__isnull=True, tenant__isnull=True, enabled=True
            )

        # Build query for all potentially applicable rules
        base_query = DNSRule.objects.filter(content_type=content_type, enabled=True)

        # Get all rules that could apply based on location and tenant
        location_conditions = models.Q(location=object_location) | models.Q(location__isnull=True)
        tenant_conditions = models.Q(tenant=object_tenant) | models.Q(tenant__isnull=True)

        all_rules = base_query.filter(location_conditions & tenant_conditions)

        # Group rules by record type and precedence level
        rules_by_type = defaultdict(
            lambda: {
                "location_tenant": [],  # Most specific
                "location": [],  # Location-wide
                "tenant": [],  # Tenant-wide
                "global": [],  # Least specific
            }
        )

        for rule in all_rules:
            record_type = rule.record_type

            if rule.location == object_location and rule.tenant == object_tenant:
                rules_by_type[record_type]["location_tenant"].append(rule)
            elif rule.location == object_location and rule.tenant is None:
                rules_by_type[record_type]["location"].append(rule)
            elif rule.location is None and rule.tenant == object_tenant:
                rules_by_type[record_type]["tenant"].append(rule)
            else:  # rule.location is None and rule.tenant is None
                rules_by_type[record_type]["global"].append(rule)

        # For each record type, select highest precedence rule (location-first)
        final_rule_pks = []
        for record_type, rules in rules_by_type.items():
            if rules["location_tenant"]:
                final_rule_pks.extend([r.pk for r in rules["location_tenant"]])
                logger.debug(f"Using location+tenant rule for {source_obj} record type {record_type}")
            elif rules["location"]:
                final_rule_pks.extend([r.pk for r in rules["location"]])
                logger.debug(f"Using location rule for {source_obj} record type {record_type}")
            elif rules["tenant"]:
                final_rule_pks.extend([r.pk for r in rules["tenant"]])
                logger.debug(f"Using tenant rule for {source_obj} record type {record_type}")
            elif rules["global"]:
                final_rule_pks.extend([r.pk for r in rules["global"]])
                logger.debug(f"Using global rule for {source_obj} record type {record_type}")

        # Return QuerySet filtered to selected rules
        return DNSRule.objects.filter(pk__in=final_rule_pks)

    def _reconcile_records_for_rule(self, rule: DNSRule, source_obj: Any) -> None:
        """Reconcile DNS records for a single rule against current object state."""
        # STEP 1: Determine what SHOULD exist (target state)
        desired_record_data = self._calculate_desired_record_data(rule, source_obj)
        logger.debug(f"Rule {rule.name}: desired record data: {desired_record_data}")

        # STEP 2: Get what currently exists
        existing_tracking_records = self._get_existing_tracking_records(rule, source_obj)
        logger.debug(f"Rule {rule.name}: existing tracking records: {existing_tracking_records}")
        # STEP 3: Compare and reconcile
        existing_count = existing_tracking_records.count()
        desired_count = len(desired_record_data)

        logger.debug(f"Rule {rule.name}: existing={existing_count}, desired={desired_count}")

        if desired_count == 0:
            # No records should exist - clean up everything
            logger.info(
                f"No records needed for {rule.name} on {source_obj} - cleaning up {existing_count} existing records"
            )
            self._cleanup_records_for_rule(rule, source_obj)
        elif existing_count == desired_count:
            # Same count - update existing records in place
            logger.debug(f"Updating {existing_count} existing records in place for {rule.name}")
            self._update_existing_records(existing_tracking_records, desired_record_data)
        else:
            # Count changed - delete and recreate is cleanest approach
            logger.info(
                f"Record count changed for {rule.name} on {source_obj} ({existing_count}→{desired_count}) - recreating"
            )
            self._cleanup_records_for_rule(rule, source_obj)
            if desired_record_data:  # Only create if there's data
                self._create_records_from_data(rule, source_obj, desired_record_data)

    def _calculate_desired_record_data(self, rule: DNSRule, source_obj: Any) -> list[dict[str, Any]]:
        """Calculate what DNS record data should exist (without creating records)."""
        context = {"obj": source_obj}

        # Build base record data - exceptions bubble up naturally
        base_record_data = {
            "name": self._render_template(rule.name_template, context, "name_template"),
            "zone": self._get_zone_for_rule(rule, context),
        }

        # Get variations (handles multi-record A/AAAA logic)
        record_data_list = self._build_record_data_variations(rule, context, base_record_data)
        return record_data_list

    def _get_zone_for_rule(self, rule: DNSRule, context: dict[str, Any]) -> DNSZone:
        """Extract zone logic into reusable method."""
        if rule.zone_template:
            zone_name = self._render_template(rule.zone_template, context, "zone_template")
            return DNSZone.objects.get(name=zone_name)
        else:
            return rule.zone_fixed

    def _get_existing_tracking_records(self, rule: DNSRule, source_obj: Any) -> models.QuerySet:
        """Get existing tracking records for a rule+object combination."""
        return DNSRuleRecord.objects.filter(
            rule=rule, content_type=ContentType.objects.get_for_model(source_obj), object_id=source_obj.id
        )

    def _update_existing_records(
        self, tracking_records: models.QuerySet, desired_record_data: list[dict[str, Any]]
    ) -> None:
        """Update existing records when count matches desired count."""
        tracking_records_list = list(tracking_records)  # Evaluate QuerySet once

        for tracking_record, desired_data in zip(tracking_records_list, desired_record_data):
            dns_record = tracking_record.dns_record

            if dns_record is None:
                # Handle missing DNS records gracefully - recreate the DNS record
                logger.warning(f"DNS record missing for tracking record {tracking_record} - recreating")
                record_class = self._get_record_class(tracking_record.rule.record_type)
                dns_record = record_class.objects.create(**desired_data)

                # Update tracking record to point to new DNS record
                tracking_record.dns_record_content_type = ContentType.objects.get_for_model(dns_record)
                tracking_record.dns_record_object_id = dns_record.id
                tracking_record.save()
                logger.debug(f"Recreated missing DNS record for {tracking_record}")
            else:
                # Update existing DNS record
                for field, value in desired_data.items():
                    setattr(dns_record, field, value)
                dns_record.save()
                logger.debug(f"Updated DNS record {dns_record}")

    def _cleanup_records_for_rule(self, rule: DNSRule, source_obj: Any) -> None:
        """Clean up all DNS records for a specific rule+object combination."""
        tracking_records = self._get_existing_tracking_records(rule, source_obj)

        deleted_dns_count = 0
        deleted_tracking_count = 0

        for tracking_record in tracking_records:
            dns_record = tracking_record.dns_record

            # Delete tracking record first
            tracking_record.delete()
            deleted_tracking_count += 1

            # Then delete actual DNS record if it exists
            if dns_record:
                dns_record.delete()
                deleted_dns_count += 1

        if deleted_dns_count > 0 or deleted_tracking_count > 0:
            logger.info(
                f"Cleaned up {deleted_dns_count} DNS records and {deleted_tracking_count} tracking records for {rule.name} on {source_obj}"
            )

    def _cleanup_orphaned_records(self, source_obj: Any, applicable_rules: models.QuerySet) -> None:
        """
        Clean up DNS records from rules that are no longer applicable to the source object.

        This handles scenarios like:
        - Device location changes (old location-specific rules no longer apply)
        - Rule modifications (disabled, deleted, or scope changes)
        - Object attribute changes that affect rule applicability

        Args:
            source_obj: The source object whose orphaned records should be cleaned up
            applicable_rules: QuerySet of currently applicable rules for this object
        """
        content_type = ContentType.objects.get_for_model(source_obj)
        existing_tracking_records = DNSRuleRecord.objects.filter(
            content_type=content_type, object_id=str(source_obj.pk)
        )

        # Find and clean up records from rules that are no longer applicable
        orphaned_records = existing_tracking_records.exclude(rule__in=applicable_rules)
        for tracking_record in orphaned_records:
            logger.debug(f"Cleaning up orphaned record from rule {tracking_record.rule.name} for {source_obj}")
            self._cleanup_records_for_rule(tracking_record.rule, source_obj)

    def _create_records_from_data(
        self, rule: DNSRule, source_obj: Any, record_data_list: list[dict[str, Any]]
    ) -> list[Any]:
        """Create DNS records and tracking records from prepared data, returning the created DNS records."""
        record_class = self._get_record_class(rule.record_type)
        created_records = []

        for record_data in record_data_list:
            # Create the DNS record
            dns_record = record_class.objects.create(**record_data)

            # Create the tracking record
            rule_record = DNSRuleRecord.objects.create(
                rule=rule,
                content_type=ContentType.objects.get_for_model(source_obj),
                object_id=source_obj.id,
                dns_record_content_type=ContentType.objects.get_for_model(dns_record),
                dns_record_object_id=dns_record.id,
            )

            # Create dependency tracking records for Jinja templates
            self._create_jinja_dependency_records(rule, rule_record, source_obj)

            created_records.append(dns_record)
            logger.info(f"Created DNS record {dns_record} from rule {rule.name} for {source_obj}")

        return created_records

    def _get_record_class(self, record_type: str):
        """Get the DNS record model class for a given record type."""
        record_class = RECORD_MODEL_MAPPING.get(record_type)
        if not record_class:
            raise ValueError(f'Unknown record type "{record_type}"')
        return record_class

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
            DNSTemplateEmptyError: If template renders empty or error strings
            TemplateError: Jinja2 template errors (TemplateSyntaxError, TemplateAssertionError, etc.)
        """
        logger.debug(f"Rendering template: {template_str} with context: {context}")
        result = render_jinja2(template_str, context)  # Let jinja2 exceptions bubble
        logger.debug(f"Template (({template_str})) rendered to result: {result}")

        # Check for falsy results (None, empty string, etc.)
        if not result:
            raise DNSTemplateEmptyError(field_name, template_str, list(context.keys()))

        # Check for template error strings that render_jinja2 sometimes returns
        # Pattern: "{{ no such element: None[\"id\"] }}" when accessing attributes on None
        # This occurs in DEBUG=True environments where Django uses jinja2.runtime.DebugUndefined
        # instead of regular Undefined, causing descriptive error strings instead of empty results
        if "{{ no such element:" in result:
            raise DNSTemplateEmptyError(field_name, f"{template_str} → {result}", list(context.keys()))

        return result

    def _build_record_data_variations(
        self, rule: DNSRule, context: dict[str, Any], base_record_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Build list of record data dictionaries (1 for single, N for multiple records).

        Handles the case where value templates return multiple IPs (space-delimited UUIDs)
        and creates separate record data for each one.

        Args:
            rule: The DNS rule containing templates
            context: Jinja context for template rendering
            base_record_data: Base data shared across all records (name, zone, etc.)

        Returns:
            List of record_data dictionaries ready for DNS record creation
        """
        record_type = rule.record_type

        if record_type in ["A", "AAAA"]:
            logger.debug(f"Building A/AAAA record data variations from rule {rule.name}")
            # Handle A/AAAA records with potential multiple IPs
            if rule.value_template:
                address_result = self._render_template(rule.value_template, context, "value_template")
                logger.debug(f"A/AAAA record data variations from rule {rule.name} - address result: {address_result}")

                # Split on space - handles both single and multiple IPs uniformly
                address_ids = address_result.split()
                logger.debug(
                    f"Building {len(address_ids)} {record_type} record data variations from IPs: {address_result}"
                )

                record_variations = []
                for address_id in address_ids:
                    record_data = base_record_data.copy()
                    record_data["address_id"] = address_id.strip()
                    record_variations.append(record_data)
                return record_variations
            else:
                # No value template - raise exception rather than return empty
                raise DNSTemplateEmptyError("value_template", "missing", [])

        else:
            # Other record types - use existing single-record logic
            record_data = base_record_data.copy()
            self._add_record_type_fields_single(rule, context, record_data)
            return [record_data]

    def _add_record_type_fields_single(
        self, rule: DNSRule, context: Dict[str, Any], record_data: Dict[str, Any]
    ) -> None:
        """
        Add record-type specific fields to the record data.

        Args:
            rule: The DNS rule containing the templates
            context: The Jinja context for rendering
            record_data: The dictionary to add fields to

        Raises:
            DNSTemplateEmptyError: If any required template renders empty
        """
        record_type = rule.record_type

        # A/AAAA records are now handled in _build_record_data_variations
        # to support multiple IP addresses cleanly
        if record_type in ["A", "AAAA"]:
            # This method no longer handles A/AAAA - they're handled in the variations builder
            pass

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

    def _create_jinja_dependency_records(self, rule: DNSRule, rule_record: "DNSRuleRecord", source_obj: Any) -> None:
        """
        Create dependency tracking records for Jinja rule templates.

        Note: This is a placeholder implementation for the dependency tracking POC.
        The actual implementation was filed away as "successful POC" for now.

        Args:
            rule: The DNS rule that was processed
            rule_record: The DNSRuleRecord tracking record
            source_obj: The source object that triggered rule processing
        """
        # Placeholder - dependency tracking implementation was successful POC
        # but has been deferred for now to focus on core multi-record functionality
        logger.debug(f"Dependency tracking placeholder for rule {rule.name} - implementation deferred")
        pass


# Global instance for use by signal handlers
dns_rule_engine = DNSRuleEngine()
