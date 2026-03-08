"""DNS Rule Processing Engine for Nautobot DNS Models."""

import logging
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db import models as django_models
from jinja2 import TemplateError
from nautobot.apps.utils import render_jinja2
from nautobot.dcim import models as dcim_models
from nautobot.ipam import models as ipam_models
from nautobot.virtualization import models as virtualization_models

from nautobot_dns_models import models
from nautobot_dns_models.exceptions import DNSTemplateEmptyError
from nautobot_dns_models.models import (
    DNSRecord,
    DNSRule,
    DNSRuleRecord,
    DNSZone,
)
from nautobot_dns_models.normalization import normalize_dns_name
from nautobot_dns_models.rules.template_proxies import wrap_for_template

logger = logging.getLogger(__name__)

# Candidate/rule processing reason codes used for warning/error logs.
REASON_VIEW_TEMPLATE_EMPTY = "VIEW_TEMPLATE_EMPTY"
REASON_VIEW_NOT_FOUND = "VIEW_NOT_FOUND"
REASON_ZONE_NOT_FOUND = "ZONE_NOT_FOUND"
REASON_CANDIDATE_TEMPLATE_ERROR = "CANDIDATE_TEMPLATE_ERROR"
REASON_CANDIDATE_ERROR = "CANDIDATE_ERROR"
REASON_RECORD_VALIDATION_ERROR = "RECORD_VALIDATION_ERROR"
REASON_RECORD_INTEGRITY_ERROR = "RECORD_INTEGRITY_ERROR"
REASON_RULE_PROCESSING_ERROR = "RULE_PROCESSING_ERROR"
REASON_INVALID_ADDRESS_UUID = "INVALID_ADDRESS_UUID"
REASON_INTERFACE_PARENT_FALLBACK_FAILED = "INTERFACE_PARENT_FALLBACK_FAILED"

# Phase labels used for log consistency and queryability.
PHASE_CREATE = "create"
PHASE_UPDATE_RECONCILE = "update_reconcile"
PHASE_CANDIDATE_EXPANSION = "candidate_expansion"
PHASE_UNKNOWN = "unknown"


class BaseDNSRuleEngine(ABC):
    """Abstract base engine for DNS rule reconciliation."""

    @abstractmethod
    def process_object(self, source_obj: Any, created: bool = False) -> dict[str, int | bool]:
        """Process a source object against all applicable rules."""

    @abstractmethod
    def _use_lookup_cache(self) -> bool:
        """Return whether cached view/zone lookups should be enabled."""

    @abstractmethod
    def _use_direct_update(self) -> bool:
        """Return whether in-place updates should use direct SQL update path."""

    @abstractmethod
    def _requires_ip_context(self, rule: DNSRule) -> bool:
        """Return whether desired-data rendering should resolve per-candidate ip context."""

    @abstractmethod
    def _create_dns_records_for_object(self, source_obj: Any, applicable_rules: list[DNSRule]) -> dict[str, int | bool]:
        """Create DNS records for a source object using applicable rules."""

    @abstractmethod
    def _update_dns_records_for_object(self, source_obj: Any, applicable_rules: list[DNSRule]) -> dict[str, int | bool]:
        """Reconcile DNS records for a source object using applicable rules."""

    @abstractmethod
    def _reconcile_records_for_rule(self, rule: DNSRule, source_obj: Any) -> dict[str, int]:
        """Reconcile existing and desired records for one rule/object pair."""

    @abstractmethod
    def _calculate_desired_record_data(
        self, rule: DNSRule, source_obj: Any, phase: str = PHASE_UNKNOWN
    ) -> list[dict[str, Any]]:
        """Calculate desired record data for one rule/object pair."""

    @abstractmethod
    def _get_zones_for_rule(
        self, rule: DNSRule, context: dict[str, Any], selected_views: list[models.DNSView], use_cache: bool = False
    ) -> list[DNSZone]:
        """Resolve DNS zones for one rule/context pair."""

    @abstractmethod
    def _get_dns_views_for_rule(
        self, rule: DNSRule, context: dict[str, Any], use_cache: bool = False
    ) -> list[models.DNSView]:
        """Resolve DNS views for one rule/context pair."""

    @abstractmethod
    def _update_tracking_record_dns_record(
        self,
        rule: DNSRule,
        source_obj: Any,
        tracking_record: DNSRuleRecord,
        desired_record_data: dict[str, Any],
        phase: str,
    ) -> str:
        """Apply in-place update for an existing tracking record."""

    def delete_dns_records_for_object(self, source_obj: Any) -> None:
        """
        Delete all DNS records created from a source object.

        Args:
            source_obj: The source object whose DNS records should be deleted
        """
        content_type = ContentType.objects.get_for_model(source_obj)
        rule_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.id)

        for rule_record in rule_records:
            self._delete_tracking_and_dns_record(rule_record)

    def preload_tracking_records_for_objects(self, source_objects: list[Any]) -> None:
        """Optionally preload tracking records for a batch of source objects."""
        del source_objects
        return None

    def reset_runtime_caches(self) -> None:
        """Clear per-engine runtime caches before a new reconciliation run."""
        return None

    @staticmethod
    def _initialize_processing_summary() -> dict[str, int | bool]:
        """Default object-level processing summary."""
        return {
            "had_existing_rule_records": False,
            "existing_rule_record_count": 0,
            "changed": False,
            "changed_record_count": 0,
            "record_ops_create_count": 0,
            "record_ops_delete_count": 0,
        }

    #
    # Internal methods
    #

    @staticmethod
    def _safe_model_label(obj: Any) -> str:
        """Return model label if available, else object type name."""
        meta = getattr(obj, "_meta", None)
        return getattr(meta, "label_lower", obj.__class__.__name__)

    def _build_log_extra(
        self,
        rule: DNSRule,
        source_obj: Any,
        reason_code: str,
        phase: str,
        exc: Exception | None = None,
        record_data: dict[str, Any] | None = None,
        cleanup: bool | None = None,
    ) -> dict[str, Any]:
        """Build structured logging context for hybrid log output."""
        extra = {
            "event": "dnsrule_engine",
            "reason_code": reason_code,
            "phase": phase,
            "rule_id": str(rule.pk),
            "rule_name": rule.name,
            "record_type": rule.record_type,
            "source_ct": self._safe_model_label(source_obj),
            "source_id": str(source_obj.pk),
            "source_repr": str(source_obj),
        }

        if exc is not None:
            extra["exception_type"] = type(exc).__name__
            extra["error"] = str(exc)

        if cleanup is not None:
            extra["cleanup"] = cleanup

        if record_data is not None:
            extra["candidate_address_id"] = str(record_data.get("address_id", ""))
            extra["candidate_name"] = record_data.get("name")
            zone = record_data.get("zone")
            extra["candidate_zone_id"] = str(getattr(zone, "id", "")) if zone is not None else ""

        return extra

    @staticmethod
    def _infer_reason_code(exc: Exception, default_reason: str) -> str:
        """Infer stable reason code from known exception shapes."""
        if isinstance(exc, DNSTemplateEmptyError):
            message = str(exc)
            if "view_template" in message:
                return REASON_VIEW_TEMPLATE_EMPTY
            return REASON_CANDIDATE_TEMPLATE_ERROR

        if isinstance(exc, TemplateError):
            return REASON_CANDIDATE_TEMPLATE_ERROR

        if isinstance(exc, ValidationError):
            message_dict = getattr(exc, "message_dict", {})
            view_errors = " ".join(message_dict.get("view_template", []))
            if "rendered no DNS view names" in view_errors:
                return REASON_VIEW_TEMPLATE_EMPTY
            if "not found from view_template" in view_errors:
                return REASON_VIEW_NOT_FOUND

            zone_errors = " ".join(message_dict.get("zone_template", []))
            if "does not exist in selected DNS view" in zone_errors:
                return REASON_ZONE_NOT_FOUND

        return default_reason

    def _log_rule_processing_error(
        self, rule: DNSRule, source_obj: Any, exc: Exception, phase: str, cleanup: bool = False
    ) -> None:
        """Emit hybrid warning for top-level rule processing failures."""
        reason_code = self._infer_reason_code(exc, REASON_RULE_PROCESSING_ERROR)
        logger.warning(
            "dnsrule_rule_failed reason=%s rule=%s source=%s:%s cleanup=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            cleanup,
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                cleanup=cleanup,
            ),
        )

    def _log_candidate_skip(
        self, rule: DNSRule, source_obj: Any, record_data: dict[str, Any], exc: Exception, phase: str
    ) -> None:
        """Emit hybrid warning for per-candidate skip decisions."""
        reason_code = self._infer_reason_code(exc, REASON_CANDIDATE_ERROR)
        logger.warning(
            "dnsrule_candidate_skipped reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    def _log_record_create_failure(
        self, rule: DNSRule, source_obj: Any, record_data: dict[str, Any], exc: Exception, phase: str
    ) -> None:
        """Emit hybrid warning for record creation failures."""
        reason_code = (
            REASON_RECORD_INTEGRITY_ERROR if isinstance(exc, IntegrityError) else REASON_RECORD_VALIDATION_ERROR
        )
        logger.warning(
            "dnsrule_record_create_failed reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    def _log_record_update_failure(
        self, rule: DNSRule, source_obj: Any, record_data: dict[str, Any], exc: Exception, phase: str
    ) -> None:
        """Emit hybrid warning for record update failures."""
        reason_code = (
            REASON_RECORD_INTEGRITY_ERROR if isinstance(exc, IntegrityError) else REASON_RECORD_VALIDATION_ERROR
        )
        logger.warning(
            "dnsrule_record_update_failed reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    def _log_reconcile_summary(self, rule: DNSRule, source_obj: Any, counts: dict[str, int]) -> None:
        """Emit per-rule reconciliation outcome summary."""
        logger.info(
            "dnsrule_reconcile_summary rule=%s source=%s:%s existing=%s desired=%s keep=%s create=%s delete=%s skipped=%s",
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            counts["existing"],
            counts["desired"],
            counts["keep"],
            counts["create"],
            counts["delete"],
            counts["skipped"],
            extra={
                **self._build_log_extra(
                    rule=rule,
                    source_obj=source_obj,
                    reason_code="RECONCILE_SUMMARY",
                    phase=PHASE_UPDATE_RECONCILE,
                ),
                "existing_count": counts["existing"],
                "desired_count": counts["desired"],
                "keep_count": counts["keep"],
                "create_count": counts["create"],
                "delete_count": counts["delete"],
                "skipped_count": counts["skipped"],
            },
        )

    def _object_needs_dns_records_for_rule(self, source_obj: Any, rule: DNSRule) -> bool:
        """
        Determine if an object needs DNS records for a specific rule.

        Args:
            source_obj: The source object to check
            rule: The rule to check
        """
        if rule.record_type in ("A", "AAAA"):
            target_ip_version = 4 if rule.record_type == "A" else 6

            if isinstance(source_obj, (dcim_models.Interface, virtualization_models.VMInterface)):
                return source_obj.ip_addresses.filter(ip_version=target_ip_version).exists()

            if isinstance(source_obj, (dcim_models.Device, virtualization_models.VirtualMachine)):
                return (rule.record_type == "A" and source_obj.primary_ip4 is not None) or (
                    rule.record_type == "AAAA" and source_obj.primary_ip6 is not None
                )

            if isinstance(source_obj, ipam_models.Service):
                return source_obj.ip_addresses.filter(ip_version=target_ip_version).exists()

            return False

        #
        # No "don't create" logic implemented for other record types yet
        return True

    def _create_dns_record_from_rule(self, rule: DNSRule, source_obj: Any) -> list[Any]:
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
        # Calculate what DNS records should exist (reuses update logic)
        desired_record_data_list = self._calculate_desired_record_data(rule, source_obj, phase=PHASE_CREATE)
        if not desired_record_data_list:
            return []

        # Create DNS records and tracking records (reuses update logic)
        created_records = self._create_records_from_data(rule, source_obj, desired_record_data_list, phase=PHASE_CREATE)

        # logger.debug(f"Created {len(created_records)} DNS records from rule {rule.name} for {source_obj}")
        return created_records

    def _get_object_location(self, source_obj: Any) -> Any:
        """
        Extract location from source object for location-scoped rule resolution.

        Location extraction logic:
        - Device: device.location (required field in Nautobot)
        - Interface: interface.device.location, with module-backed fallback via interface.parent
        - Service: service.device.location OR service.virtual_machine.location (which is just a proxy for cluster.location)
        - VirtualMachine: vm.cluster.location
        - VMInterface: vminterface.virtual_machine.location (which is just a proxy for cluster.location)
        - InterfaceRedundancyGroup: None (complex multi-location) (future)

        Args:
            source_obj: The object to extract location from

        Returns:
            Location object or None if object type is not location-aware
        """
        # Interface objects are the hot path for signal-driven processing.
        if isinstance(source_obj, dcim_models.Interface):
            #
            # Interface.device is set when the interface is a component of a device.
            if source_obj.device:
                return source_obj.device.location

            # Module-backed interfaces may expose their containing Device via parent.
            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.location

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "location",
                self._safe_model_label(source_obj),
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._safe_model_label(source_obj),
                    "source_id": str(source_obj.pk),
                    "source_repr": str(source_obj),
                    "resolution_field": "location",
                    "parent_type": type(parent).__name__,
                },
            )
            return None

        if isinstance(source_obj, virtualization_models.VMInterface):
            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.location
            return None

        # Device objects have direct location (required field in Nautobot).
        if isinstance(source_obj, dcim_models.Device):
            return source_obj.location

        # VM.location property resolves to cluster.location.
        if isinstance(source_obj, virtualization_models.VirtualMachine):
            return source_obj.location

        # Service objects can be attached to either Device or VirtualMachine.
        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.location

            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.location

            return None

        return None

    def _get_object_tenant(self, source_obj: Any) -> Any:
        """
        Extract tenant from source object for tenant-scoped rule resolution.

        Tenant extraction logic:
        - Device: device.tenant (optional field in Nautobot)
        - Interface: interface.device.tenant, with module-backed fallback via interface.parent
        - Service: service.device.tenant OR service.virtual_machine.tenant (with cluster.tenant fallback)
        - VirtualMachine: vm.tenant (with cluster.tenant fallback)
        - VMInterface: vminterface.virtual_machine.tenant (with cluster.tenant fallback)
        - Other objects: None (no tenant awareness)

        Args:
            source_obj: The object to extract tenant from

        Returns:
            Tenant object or None if object has no tenant or type is not tenant-aware
        """
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.tenant

            module = source_obj.module
            # NOTE: This currently checks only the directly attached module tenant.
            # NOTE: It does not walk ancestor modules/module-bays to discover tenant.
            if module and module.tenant:
                return module.tenant

            # Module-backed interfaces may expose their containing Device via parent.
            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.tenant

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "tenant",
                self._safe_model_label(source_obj),
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._safe_model_label(source_obj),
                    "source_id": str(source_obj.pk),
                    "source_repr": str(source_obj),
                    "resolution_field": "tenant",
                    "parent_type": type(parent).__name__,
                },
            )
            return None

        if isinstance(source_obj, virtualization_models.VMInterface):
            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.tenant or vm.cluster.tenant

            return None

        if isinstance(source_obj, dcim_models.Device):
            return source_obj.tenant

        if isinstance(source_obj, virtualization_models.VirtualMachine):
            return source_obj.tenant or source_obj.cluster.tenant

        # Service objects can be attached to either Device or VirtualMachine.
        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.tenant

            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.tenant or vm.cluster.tenant

            return None

        # Object type is not tenant-aware or has no tenant assigned
        return None

    def _get_applicable_rules(self, source_obj: Any) -> list[DNSRule]:
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
            List of applicable DNSRule objects
        """
        content_type = ContentType.objects.get_for_model(source_obj)
        object_location = self._get_object_location(source_obj)
        object_tenant = self._get_object_tenant(source_obj)
        return self._resolve_applicable_rules_for_scope(content_type, object_location, object_tenant)

    def _resolve_applicable_rules_for_scope(
        self,
        content_type,
        object_location: Any,
        object_tenant: Any,
    ) -> list[DNSRule]:
        """Resolve rules for a specific content-type/location/tenant scope."""

        # Early return for objects with no location or tenant - only global rules can apply
        if object_location is None and object_tenant is None:
            # logger.debug(f"Using global rules for {source_obj} (no location, no tenant)")
            return list(
                DNSRule.objects.filter(content_type=content_type, location__isnull=True, tenant__isnull=True, enabled=True)
            )

        # Build query for all potentially applicable rules
        base_query = DNSRule.objects.filter(content_type=content_type, enabled=True)

        # Get all rules that could apply based on location and tenant
        location_conditions = django_models.Q(location=object_location) | django_models.Q(location__isnull=True)
        tenant_conditions = django_models.Q(tenant=object_tenant) | django_models.Q(tenant__isnull=True)

        all_rules = list(base_query.filter(location_conditions & tenant_conditions))

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
                # logger.debug(f"Using location+tenant rule for {source_obj} record type {record_type}")
            elif rules["location"]:
                final_rule_pks.extend([r.pk for r in rules["location"]])
                # logger.debug(f"Using location rule for {source_obj} record type {record_type}")
            elif rules["tenant"]:
                final_rule_pks.extend([r.pk for r in rules["tenant"]])
                # logger.debug(f"Using tenant rule for {source_obj} record type {record_type}")
            elif rules["global"]:
                final_rule_pks.extend([r.pk for r in rules["global"]])
                # logger.debug(f"Using global rule for {source_obj} record type {record_type}")

        # Return selected rules from the already-fetched candidate set.
        final_rule_pk_set = set(final_rule_pks)
        return [rule for rule in all_rules if rule.pk in final_rule_pk_set]

    def _build_record_context(self, base_context: dict[str, Any], record_data: dict[str, Any]) -> dict[str, Any]:
        """Build per-record template context, including selected IP when available."""
        context = dict(base_context)
        context["record"] = record_data.copy()

        address_id = record_data.get("address_id")
        if address_id:
            ip_obj = ipam_models.IPAddress.objects.filter(pk=address_id).first()
            if ip_obj is None:
                raise ValidationError({"value_template": f"Resolved IP address '{address_id}' was not found."})
            context["ip"] = wrap_for_template(ip_obj)

        return context

    def _get_existing_tracking_records(self, rule: DNSRule, source_obj: Any) -> django_models.QuerySet:
        """Get existing tracking records for a rule+object combination."""
        return DNSRuleRecord.objects.filter(
            rule=rule, content_type=ContentType.objects.get_for_model(source_obj), object_id=source_obj.id
        )

    def _get_existing_records_by_rule_and_object(self, rule: DNSRule, source_obj: Any) -> dict[str, DNSRuleRecord]:
        tracking_records = self._get_existing_tracking_records(rule, source_obj)
        existing_records_by_content = {}
        for tracking_record in tracking_records:
            dns_record = tracking_record.dns_record
            content_key = self._get_record_content_key(dns_record)
            # logger.debug(f"Existing record content key: '{content_key}'")
            existing_records_by_content[content_key] = tracking_record

        return existing_records_by_content

    def _get_desired_records_by_rule_and_object(self, rule: DNSRule, source_obj: Any) -> dict[str, dict[str, Any]]:
        desired_record_data = self._calculate_desired_record_data(rule, source_obj, phase=PHASE_UPDATE_RECONCILE)
        desired_records_by_content = {}
        for record_data in desired_record_data:
            content_key = self._get_record_content_key_from_data(record_data, rule.record_type)
            logger.debug(f"Desired record content key: '{content_key}'")
            desired_records_by_content[content_key] = record_data

        return desired_records_by_content

    def _cleanup_records_for_rule(self, rule: DNSRule, source_obj: Any) -> int:
        """Clean up all DNS records for a specific rule+object combination."""
        tracking_records = self._get_existing_tracking_records(rule, source_obj)
        deleted_count = 0

        for tracking_record in tracking_records:
            self._delete_tracking_and_dns_record(tracking_record)
            deleted_count += 1

        return deleted_count

    def _cleanup_orphaned_records(self, source_obj: Any, applicable_rules: django_models.QuerySet) -> int:
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
        deleted_count = 0
        orphaned_rule_ids = orphaned_records.values_list("rule_id", flat=True).distinct()
        for orphaned_rule in DNSRule.objects.filter(pk__in=orphaned_rule_ids):
            # logger.debug(f"Cleaning up orphaned record from rule {orphaned_rule.name} for {source_obj}")
            deleted_count += self._cleanup_records_for_rule(orphaned_rule, source_obj)

        return deleted_count

    def _create_records_from_data(
        self, rule: DNSRule, source_obj: Any, record_data_list: list[dict[str, Any]], phase: str = PHASE_UNKNOWN
    ) -> list[Any]:
        """Create DNS records and tracking records from prepared data, returning the created DNS records."""
        record_class = self._get_record_class(rule.record_type)

        created_records = []

        for record_data in record_data_list:
            # Create the DNS record. This is a best-effort operation; if any of them fail, log the error and continue.
            try:
                with transaction.atomic():
                    dns_record = record_class(**record_data)  # pylint: disable=not-callable
                    dns_record.validated_save()

                    DNSRuleRecord.objects.create(
                        rule=rule,
                        content_type=ContentType.objects.get_for_model(source_obj),
                        object_id=source_obj.id,
                        dns_record_content_type=ContentType.objects.get_for_model(dns_record),
                        dns_record_object_id=dns_record.id,
                    )
            except (ValidationError, IntegrityError) as exc:
                self._log_record_create_failure(rule, source_obj, record_data, exc, phase=phase)
                continue

            created_records.append(dns_record)
            # logger.debug(f"Created DNS record {dns_record} from rule {rule.name} for {source_obj}")

        return created_records

    def _get_record_class(self, record_type: str):
        """Get the DNS record model class for a given record type."""
        record_type_name = f"{record_type}Record"
        record_class = getattr(models, record_type_name, None)

        if not record_class:
            raise ValueError(f'Unknown record type "{record_type}"')

        if not issubclass(record_class, DNSRecord):
            raise ValueError(f"Record type '{record_type}' is not a valid DNS record type")

        return record_class

    def _render_template(self, template_str: str, context: dict[str, Any], field_name: str) -> str:
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
        # logger.debug(f"Rendering template: {template_str} with context: {context}")
        result = render_jinja2(template_str, context)  # Let jinja2 exceptions bubble
        # logger.debug(f"Template (({template_str})) rendered to result: '{result}'")

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

    def _get_record_content_key(self, dns_record) -> str:
        """Generate a content-based key for record comparison."""
        record_type = dns_record.__class__.__name__
        base_key = f"{record_type}:{dns_record.name}:{dns_record.zone_id}"

        suffix = "unknown"
        if hasattr(dns_record, "address_id"):  # A/AAAA
            suffix = dns_record.address_id

        return f"{base_key}:{suffix}"

    def _get_record_identity_key(self, dns_record) -> str:
        """Generate an identity key that excludes mutable fields such as rendered name."""
        record_type = dns_record.__class__.__name__

        if hasattr(dns_record, "address_id"):  # A/AAAA
            return f"{record_type}:{dns_record.zone_id}:{dns_record.address_id}"

        return self._get_record_content_key(dns_record)

    def _get_record_content_key_from_data(self, record_data: dict, rule_record_type: str) -> str:
        """Generate content key from record data dict."""
        zone_id = record_data["zone"].id
        name = record_data["name"]

        record_type = f"{rule_record_type}Record"
        if rule_record_type in ("A", "AAAA"):
            suffix = record_data["address_id"]
        else:
            raise ValueError(f"Unsupported record type for content key generation: {rule_record_type}")

        return f"{record_type}:{name}:{zone_id}:{suffix}"

    def _get_record_identity_key_from_data(self, record_data: dict, rule_record_type: str) -> str:
        """Generate identity key from record data dict."""
        zone_id = record_data["zone"].id
        record_type = f"{rule_record_type}Record"

        if rule_record_type in ("A", "AAAA"):
            return f"{record_type}:{zone_id}:{record_data['address_id']}"

        return self._get_record_content_key_from_data(record_data, rule_record_type)

    def _delete_tracking_and_dns_record(self, tracking_record) -> None:
        """Delete both the DNS record and its tracking record."""
        # logger.debug(f"Deleting DNS record {tracking_record.dns_record} and tracking record {tracking_record}")

        try:
            #
            # Just delete the DNS record; the assciated tracking record is cascade-deleted
            # via the GenericRelation on the DNSRecord model.
            tracking_record.dns_record.delete()
        except Exception as exc:
            logger.error(
                "Failed to delete DNS record '%s' and tracking record '%s': %s (%s)",
                tracking_record.dns_record,
                tracking_record,
                exc,
                type(exc).__name__,
            )
            raise

    def _get_record_data_variations_for_rule(
        self, rule: DNSRule, context: dict[str, Any], base_record_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Build list of record data dictionaries (1 for single, N for multiple records).

        Handles the case where value templates return multiple IPs (space-delimited UUIDs)
        and creates separate record data for each one.

        Args:
            rule: The DNS rule containing templates
            context: Jinja context for template rendering
            base_record_data: Base data shared across all records (name, etc.)

        Returns:
            List of record_data dictionaries ready for DNS record creation
        """
        record_type = rule.record_type

        if record_type in ("A", "AAAA"):
            # logger.debug(f"Building A/AAAA record data variations from rule {rule.name}")
            # Handle A/AAAA records with potential multiple IPs
            if rule.value_template:
                address_result = self._render_template(rule.value_template, context, "value_template")
                # logger.debug(f"A/AAAA record data variations from rule {rule.name} - address result: {address_result}")

                # Split on space - handles both single and multiple IPs uniformly
                address_ids = address_result.split()

                return self._build_record_variations(rule, base_record_data, address_ids)

            # No value template - raise exception rather than return empty
            raise DNSTemplateEmptyError("value_template", "missing", [])

        # Other record types - use existing single-record logic
        record_data = base_record_data.copy()
        self._add_record_type_fields_single(rule, context, record_data)
        return [record_data]

    def _build_record_variations(
        self, rule: DNSRule, base_record_data: dict[str, Any], address_ids: list[str]
    ) -> list[dict[str, Any]]:
        """
        Build list of record data dictionaries for a given list of address IDs.

        Args:
            rule: The DNS rule containing the templates
            base_record_data: Base data shared across all records (name, zone, etc.)
            address_ids: List of address IDs to build record data for

        Returns:
            List of record data dictionaries ready for DNS record creation
        """
        record_variations = []
        for address_id in address_ids:
            address_id = address_id.strip()
            if not address_id:
                continue

            try:
                uuid.UUID(address_id)
            except ValueError:
                logger.warning(
                    "dnsrule_candidate_skipped reason=%s rule=%s invalid_address_id=%s",
                    REASON_INVALID_ADDRESS_UUID,
                    rule.name,
                    address_id,
                    extra={
                        "event": "dnsrule_engine",
                        "reason_code": REASON_INVALID_ADDRESS_UUID,
                        "phase": PHASE_CANDIDATE_EXPANSION,
                        "rule_id": str(rule.pk),
                        "rule_name": rule.name,
                        "record_type": rule.record_type,
                        "invalid_address_id": address_id,
                    },
                )
                continue

            record_data = base_record_data.copy()
            record_data["address_id"] = address_id
            record_variations.append(record_data)

        return record_variations

    def _add_record_type_fields_single(
        self, rule: DNSRule, context: dict[str, Any], record_data: dict[str, Any]
    ) -> None:
        """
        Add record-type specific fields to the record data.

        Args:
            rule: The DNS rule containing the templates
            context: The Jinja context for rendering
            record_data: The dictionary to add fields to

        Side effect: Adds record-type specific fields to the record data.

        Raises:
            DNSTemplateEmptyError: If any required template renders empty
        """
        # A/AAAA records are now handled in _get_record_data_variations_for_rule
        # to support multiple IP addresses cleanly
        if rule.record_type in ("A", "AAAA"):
            # This method no longer handles A/AAAA - they're handled in the variations builder
            pass

        if record_type_method := getattr(self, f"_add_record_type_fields_{rule.record_type}", None):
            record_type_method(rule, context, record_data)  # pylint: disable=not-callable


