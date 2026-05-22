"""Ruleset selection and precedence logic for DNS rules."""

from collections import defaultdict

from django.db import models as django_models

from nautobot_dns_models.models import DNSRule


class RuleSetSelector:
    """Resolve applicable rules for a scoped content type."""

    def resolve_for_scope(self, content_type, object_location, object_tenant, selected_rule_ids=None):
        """Resolve rules for a specific content-type/location/tenant scope.

        Args:
            content_type: Source object content type used to scope candidate rules.
            object_location: Resolved location for the source object, or None.
            object_tenant: Resolved tenant for the source object, or None.
            selected_rule_ids: Optional set of rule IDs used to constrain candidates.
                - ``None`` means no explicit selection filter is applied, so all
                  enabled scope-matching rules are considered by precedence logic.
                - An empty set means explicitly select no rules.

        Returns:
            list: Ordered list of applicable ``DNSRule`` objects after applying
                optional selection filtering and per-record-type scope precedence.
                The result contains at most one rule per DNS record type. When
                multiple scope levels are eligible for a record type, the most
                specific matching scope is selected in this order:
                ``location_tenant`` > ``location`` > ``tenant`` > ``global``.
        """
        if object_location is None and object_tenant is None:
            # Fast path for global-only scope lookups
            resolved_rules = self._resolve_global_scope_rules(content_type, selected_rule_ids)
        else:
            resolved_rules = self._resolve_scoped_rules(
                content_type,
                object_location,
                object_tenant,
                selected_rule_ids=selected_rule_ids,
            )

        return sorted(resolved_rules, key=lambda rule: rule.record_type)

    def _resolve_global_scope_rules(self, content_type, selected_rule_ids=None):
        """Resolve global-only rules for objects without location and tenant scope."""
        queryset = DNSRule.objects.filter(
            content_type=content_type, location__isnull=True, tenant__isnull=True, enabled=True
        )
        if selected_rule_ids is not None:
            queryset = queryset.filter(pk__in=selected_rule_ids)

        return list(queryset)

    def _resolve_scoped_rules(self, content_type, object_location, object_tenant, selected_rule_ids=None):
        """Resolve scoped rules using per-record-type scope precedence."""
        base_query = DNSRule.objects.filter(content_type=content_type, enabled=True)
        if selected_rule_ids is not None:
            base_query = base_query.filter(pk__in=selected_rule_ids)

        location_conditions = django_models.Q(location=object_location) | django_models.Q(location__isnull=True)
        tenant_conditions = django_models.Q(tenant=object_tenant) | django_models.Q(tenant__isnull=True)

        rules_by_type = self._get_rules_by_type(list(base_query.filter(location_conditions & tenant_conditions)))

        final_rules = []
        for rules in rules_by_type.values():
            # Select the first non-empty scope bucket by precedence.
            final_rules.extend(rules["location_tenant"] or rules["location"] or rules["tenant"] or rules["global"])

        return final_rules

    def _get_rules_by_type(self, all_rules):
        """Get rules by type and scope."""
        rules_by_type = defaultdict(lambda: {"location_tenant": [], "location": [], "tenant": [], "global": []})

        for rule in all_rules:
            record_type = rule.record_type
            has_location_scope = rule.location_id is not None
            has_tenant_scope = rule.tenant_id is not None

            if has_location_scope and has_tenant_scope:
                rules_by_type[record_type]["location_tenant"].append(rule)
            elif has_location_scope:
                rules_by_type[record_type]["location"].append(rule)
            elif has_tenant_scope:
                rules_by_type[record_type]["tenant"].append(rule)
            else:
                rules_by_type[record_type]["global"].append(rule)

        return rules_by_type
