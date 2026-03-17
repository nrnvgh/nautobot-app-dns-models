"""SQL scope-filter helpers used by bulk reconciliation jobs."""

from django.db.models import Q
from nautobot.dcim.constants import MODULE_RECURSION_DEPTH_LIMIT


class BulkScopeFilterBuilder:
    """Build model-specific SQL scope filters for bulk job target querysets."""

    _MODEL_SCOPE_METHODS = {
        "dcim.device": "_apply_device",
        "dcim.interface": "_apply_interface",
        "virtualization.virtualmachine": "_apply_virtualmachine",
    }

    def apply(self, model_label, queryset, *, location_ids, tenant_ids):
        """Return `(queryset, used_sql_scope_filtering)` for requested model label."""
        method_name = self._MODEL_SCOPE_METHODS.get(model_label)
        if not method_name:
            return queryset, False

        handler = getattr(self, method_name)

        return handler(queryset, location_ids=location_ids, tenant_ids=tenant_ids)

    @staticmethod
    def _apply_device(queryset, *, location_ids, tenant_ids):
        """Apply direct device location/tenant filtering in SQL."""
        used_scope_filter = False
        if location_ids:
            queryset = queryset.filter(location_id__in=location_ids)
            used_scope_filter = True

        if tenant_ids:
            queryset = queryset.filter(tenant_id__in=tenant_ids)
            used_scope_filter = True

        return queryset, used_scope_filter

    def _apply_interface(self, queryset, *, location_ids, tenant_ids):
        """Apply recursive interface location/tenant filtering in SQL."""
        scope_filter = Q()
        used_scope_filter = False

        if location_ids:
            used_scope_filter = True
            scope_filter &= self._build_interface_parent_device_filter("location_id", location_ids)

        if tenant_ids:
            used_scope_filter = True
            tenant_filter = self._build_interface_parent_device_filter("tenant_id", tenant_ids)
            # Engine behavior prefers module tenant when present for module-backed interfaces.
            tenant_filter |= Q(module__tenant_id__in=tenant_ids)
            scope_filter &= tenant_filter

        if not used_scope_filter:
            return queryset, False

        queryset = queryset.filter(scope_filter)
        return queryset, True

    @staticmethod
    def _apply_virtualmachine(queryset, *, location_ids, tenant_ids):
        """Apply virtual machine location/tenant filtering in SQL."""
        used_scope_filter = False

        if location_ids:
            queryset = queryset.filter(cluster__location_id__in=location_ids)
            used_scope_filter = True

        if tenant_ids:
            # Engine parity: VM tenant overrides cluster tenant when set.
            queryset = queryset.filter(Q(tenant_id__in=tenant_ids) | Q(tenant_id__isnull=True, cluster__tenant_id__in=tenant_ids))
            used_scope_filter = True

        return queryset, used_scope_filter

    @staticmethod
    def _build_interface_parent_device_filter(field_name, values):
        """Build bounded recursive filter from interface to parent-device fields."""
        # Copied from nautobot.dcim.filters.mixins.ModularDeviceComponentFilterSetMixin.generate_query_filter_device()
        recursion_depth = max(0, MODULE_RECURSION_DEPTH_LIMIT - 1)
        query = Q(**{f"device__{field_name}__in": values})
        for level in range(recursion_depth):
            recursive_path = "module__parent_module_bay__" + "parent_module__parent_module_bay__" * level
            query |= Q(**{f"{recursive_path}parent_device__{field_name}__in": values})

        return query
