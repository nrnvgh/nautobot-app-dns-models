"""Rule resolution collaborator."""

import logging

from django.contrib.contenttypes.models import ContentType
from nautobot.dcim import models as dcim_models
from nautobot.ipam import models as ipam_models
from nautobot.virtualization import models as virtualization_models

from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER
from nautobot_dns_models.rules.engine.ruleset import RuleSetSelector
from nautobot_dns_models.rules.engine.scope import ScopeResolver

logger = logging.getLogger(__name__)


class RuleResolver:
    """Resolve applicable DNS rules for source objects."""

    def __init__(self, cache, context, *, selected_rules=None):
        """Store collaborator references and shared runtime context.

        Args:
            cache: Shared engine cache for applicable-rule memoization.
            context: Engine runtime context consumed by resolver collaborators.
            selected_rules: Optional explicit DNSRule objects to constrain
                applicability resolution during this engine run.
        """
        self._cache = cache
        self._context = context
        self._engine_logger = DEFAULT_ENGINE_LOGGER
        self._scope_resolver = ScopeResolver()
        self._ruleset_selector = RuleSetSelector()
        self._selected_rule_ids = {rule.pk for rule in selected_rules} if selected_rules else None

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
        return self._scope_resolver.get_object_location(source_obj)

    def get_object_tenant(self, source_obj):
        """Resolve tenant across supported source object types.

        Includes interface module/parent fallback handling and warning logs
        when relationship data is incomplete for interface-like objects.
        """
        return self._scope_resolver.get_object_tenant(source_obj)

    def _resolve_applicable_rules_for_scope(self, content_type, object_location, object_tenant):
        """Resolve rules for a specific content-type/location/tenant scope."""
        return self._ruleset_selector.resolve_for_scope(
            content_type,
            object_location,
            object_tenant,
            selected_rule_ids=self._selected_rule_ids,
        )
