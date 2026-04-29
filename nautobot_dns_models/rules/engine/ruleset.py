"""Ruleset selection and precedence logic for DNS rules."""

from collections import defaultdict

from django.db import models as django_models

from nautobot_dns_models.models import DNSRule


class RuleSetSelector:
    """Resolve applicable rules for a scoped content type."""

    def resolve_for_scope(self, content_type, object_location, object_tenant, selected_rule_ids=None):
        """Resolve rules for a specific content-type/location/tenant scope."""
        if object_location is None and object_tenant is None:
            queryset = DNSRule.objects.filter(
                content_type=content_type, location__isnull=True, tenant__isnull=True, enabled=True
            )
            if selected_rule_ids:
                queryset = queryset.filter(pk__in=selected_rule_ids)
            return list(queryset)

        base_query = DNSRule.objects.filter(content_type=content_type, enabled=True)
        if selected_rule_ids:
            base_query = base_query.filter(pk__in=selected_rule_ids)

        location_conditions = django_models.Q(location=object_location) | django_models.Q(location__isnull=True)
        tenant_conditions = django_models.Q(tenant=object_tenant) | django_models.Q(tenant__isnull=True)
        all_rules = list(base_query.filter(location_conditions & tenant_conditions))
        # rules_by_type = self._get_rules_by_type(all_rules, object_location, object_tenant)
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
                final_rule_pks.extend([rule.pk for rule in rules["location_tenant"]])
            elif rules["location"]:
                final_rule_pks.extend([rule.pk for rule in rules["location"]])
            elif rules["tenant"]:
                final_rule_pks.extend([rule.pk for rule in rules["tenant"]])
            elif rules["global"]:
                final_rule_pks.extend([rule.pk for rule in rules["global"]])

        final_rule_pk_set = set(final_rule_pks)
        return [rule for rule in all_rules if rule.pk in final_rule_pk_set]

    def _get_rules_by_type(self, all_rules, object_location, object_tenant):
        """Get rules by type and scope."""
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

        return rules_by_type
