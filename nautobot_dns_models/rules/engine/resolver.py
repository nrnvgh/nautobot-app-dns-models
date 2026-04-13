"""Rule resolution collaborator."""

import logging
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.db import models as django_models
from nautobot.dcim import models as dcim_models
from nautobot.ipam import models as ipam_models
from nautobot.virtualization import models as virtualization_models

from nautobot_dns_models.models import DNSRule

from .constants import PHASE_UNKNOWN, REASON_INTERFACE_PARENT_FALLBACK_FAILED

logger = logging.getLogger(__name__)


class RuleResolver:
    """Resolve applicable DNS rules for source objects."""

    def __init__(self, engine, cache, context):
        """Store collaborator references and shared runtime context."""
        self._engine = engine
        self._cache = cache
        self._context = context
        self._engine_logger = engine._engine_logger

    def get_applicable_rules(self, source_obj):
        """Scope-key cache for applicable-rule resolution."""
        content_type = ContentType.objects.get_for_model(source_obj)
        object_location = self.get_object_location(source_obj)
        object_tenant = self.get_object_tenant(source_obj)
        cache_key = (content_type.pk, getattr(object_location, "pk", None), getattr(object_tenant, "pk", None))
        cached_rules = self._cache.applicable_rules_cache.get(cache_key)
        if cached_rules is not None:
            return cached_rules

        selected_rules = self._resolve_applicable_rules_for_scope(content_type, object_location, object_tenant)
        self._cache.applicable_rules_cache[cache_key] = selected_rules

        return selected_rules

    def _resolve_applicable_rules_for_scope(self, content_type, object_location, object_tenant):
        """Resolve rules for a specific content-type/location/tenant scope."""
        if object_location is None and object_tenant is None:
            return list(
                DNSRule.objects.filter(
                    content_type=content_type, location__isnull=True, tenant__isnull=True, enabled=True
                )
            )

        base_query = DNSRule.objects.filter(content_type=content_type, enabled=True)
        location_conditions = django_models.Q(location=object_location) | django_models.Q(location__isnull=True)
        tenant_conditions = django_models.Q(tenant=object_tenant) | django_models.Q(tenant__isnull=True)
        all_rules = list(base_query.filter(location_conditions & tenant_conditions))
        rules_by_type = defaultdict(lambda: {"location_tenant": [], "location": [], "tenant": [], "global": []})
        for rule in all_rules:
            record_type = rule.record_type
            if rule.location == object_location and rule.tenant == object_tenant:
                rules_by_type[record_type]["location_tenant"].append(rule)
            elif rule.location == object_location and rule.tenant is None:
                rules_by_type[record_type]["location"].append(rule)
            elif rule.location is None and rule.tenant == object_tenant:
                rules_by_type[record_type]["tenant"].append(rule)
            else:
                rules_by_type[record_type]["global"].append(rule)

        final_rule_pks = []
        for rules in rules_by_type.values():
            if rules["location_tenant"]:
                final_rule_pks.extend([r.pk for r in rules["location_tenant"]])
            elif rules["location"]:
                final_rule_pks.extend([r.pk for r in rules["location"]])
            elif rules["tenant"]:
                final_rule_pks.extend([r.pk for r in rules["tenant"]])
            elif rules["global"]:
                final_rule_pks.extend([r.pk for r in rules["global"]])

        final_rule_pk_set = set(final_rule_pks)

        return [rule for rule in all_rules if rule.pk in final_rule_pk_set]

    def object_needs_dns_records_for_rule(self, source_obj, rule):
        """Return whether this object should produce records for the given rule."""
        if rule.record_type not in ("A", "AAAA"):
            return True

        target_ip_version = 4 if rule.record_type == "A" else 6
        prefetched = getattr(source_obj, "_prefetched_objects_cache", {}).get("ip_addresses")
        if prefetched is not None:
            return any(ip_obj.ip_version == target_ip_version for ip_obj in prefetched)

        if isinstance(source_obj, (dcim_models.Interface, virtualization_models.VMInterface)):
            return source_obj.ip_addresses.filter(ip_version=target_ip_version).exists()

        if isinstance(source_obj, (dcim_models.Device, virtualization_models.VirtualMachine)):
            return (rule.record_type == "A" and source_obj.primary_ip4 is not None) or (
                rule.record_type == "AAAA" and source_obj.primary_ip6 is not None
            )

        if isinstance(source_obj, ipam_models.Service):
            return source_obj.ip_addresses.filter(ip_version=target_ip_version).exists()

        return False

    def get_object_location(self, source_obj):
        """Resolve location across supported source object types.

        Includes interface parent fallback handling and warning logs when
        relationship data is incomplete for interface-like objects.
        """
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.location

            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.location

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "location",
                self._engine_logger._safe_model_label(source_obj),
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._engine_logger._safe_model_label(source_obj),
                    "source_id": str(source_obj.pk),
                    "source_repr": str(source_obj),
                    "resolution_field": "location",
                    "parent_type": type(parent).__name__,
                },
            )
            return None

        if isinstance(source_obj, virtualization_models.VMInterface):
            if source_obj.virtual_machine:
                return source_obj.virtual_machine.location
            return None

        if isinstance(source_obj, dcim_models.Device):
            return source_obj.location

        if isinstance(source_obj, virtualization_models.VirtualMachine):
            return source_obj.location

        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.location
            if source_obj.virtual_machine:
                return source_obj.virtual_machine.location
            return None

        return None

    def get_object_tenant(self, source_obj):
        """Resolve tenant across supported source object types.

        Includes interface module/parent fallback handling and warning logs
        when relationship data is incomplete for interface-like objects.
        """
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.tenant

            module = source_obj.module
            if module and module.tenant:
                return module.tenant

            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.tenant

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "tenant",
                self._engine_logger._safe_model_label(source_obj),
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._engine_logger._safe_model_label(source_obj),
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

        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.tenant

            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.tenant or vm.cluster.tenant

            return None

        return None
