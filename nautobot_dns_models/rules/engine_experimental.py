"""Experimental reconciliation engine entry point."""

import re

from django.template import engines as django_template_engines
from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine import (
    ContentType,
    DNSTemplateEmptyError,
    DNSZone,
    IntegrityError,
    PHASE_UNKNOWN,
    ValidationError,
    models,
)
from nautobot_dns_models.rules.engine_safe import SafeDNSRuleEngine


class ExperimentalDNSRuleEngine(SafeDNSRuleEngine):
    """Experimental engine initialized with safe-path behavior."""

    def __init__(self):
        """Initialize experimental runtime caches."""
        self._default_view_cache = None
        self._view_lookup_cache = {}
        self._zone_lookup_cache = {}
        self._applicable_rules_cache = {}
        self._compiled_template_cache = {}
        self._jinja_env = django_template_engines["jinja"].env

    def reset_runtime_caches(self):
        """Clear per-run scope cache to avoid stale rule objects across jobs."""
        self._default_view_cache = None
        self._view_lookup_cache.clear()
        self._zone_lookup_cache.clear()
        self._applicable_rules_cache.clear()

    def _use_direct_update(self):
        """Experimental tuning: enable direct SQL rename updates."""
        return True

    def _requires_ip_context(self, rule):
        """Experimental tuning: only resolve ip context when templates reference ip."""
        template_text = " ".join([rule.view_template or "", rule.zone_template or ""])
        return bool(re.search(r"\bip\b", template_text))

    def process_objects_batch(self, source_objects, created=False):
        """Experimental chunk-level processing entrypoint for batch tests."""
        summaries = []
        for source_obj in source_objects:
            try:
                summaries.append(self.process_object(source_obj, created=created))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                summaries.append({"_batch_failed": True, "_batch_error": str(exc)})
        return summaries

    def _render_template(self, template_str, context, field_name):
        """Experimental tuning: render from cached compiled Jinja templates."""
        # Only short-circuit when there is no Jinja2 syntax ({{, {%, {#).
        if "{{" not in template_str and "{%" not in template_str and "{#" not in template_str:
            result = template_str.strip()
            if not result:
                raise DNSTemplateEmptyError(field_name, template_str, list(context.keys()))

            return result

        compiled_template = self._compiled_template_cache.get(template_str)
        if compiled_template is None:
            if len(self._compiled_template_cache) >= 1024:
                self._compiled_template_cache.clear()
            compiled_template = self._jinja_env.from_string(template_str)
            self._compiled_template_cache[template_str] = compiled_template

        result = compiled_template.render(context)
        if not result:
            raise DNSTemplateEmptyError(field_name, template_str, list(context.keys()))
        if "{{ no such element:" in result:
            raise DNSTemplateEmptyError(field_name, f"{template_str} → {result}", list(context.keys()))
        return result

    def _get_applicable_rules(self, source_obj):
        """Experimental tuning: scope-key cache for applicable-rule resolution."""
        content_type = ContentType.objects.get_for_model(source_obj)
        object_location = self._get_object_location(source_obj)
        object_tenant = self._get_object_tenant(source_obj)

        cache_key = (
            content_type.pk,
            getattr(object_location, "pk", None),
            getattr(object_tenant, "pk", None),
        )
        cached_rules = self._applicable_rules_cache.get(cache_key)
        if cached_rules is not None:
            return cached_rules

        selected_rules = self._resolve_applicable_rules_for_scope(content_type, object_location, object_tenant)
        self._applicable_rules_cache[cache_key] = selected_rules
        return selected_rules

    def _get_dns_views_for_rule(self, rule, context):
        """Experimental tuning: cache DNS view resolution for repeated templates."""
        if not rule.view_template:
            if self._default_view_cache is None:
                self._default_view_cache = models.DNSView.objects.get(pk=models.get_default_view_pk())
            return [self._default_view_cache]
        rendered = self._render_template(rule.view_template, context, "view_template")
        raw_names = [token.strip() for token in re.split(r"[\s,]+", rendered) if token.strip()]
        if not raw_names:
            raise ValidationError({"view_template": "view_template rendered no DNS view names."})
        requested_names = list(dict.fromkeys(raw_names))
        cache_key = tuple(requested_names)
        cached_views = self._view_lookup_cache.get(cache_key)
        if cached_views is not None:
            return cached_views
        matched_views = list(models.DNSView.objects.filter(name__in=requested_names))
        matched_by_name = {view.name: view for view in matched_views}
        missing_names = [name for name in raw_names if name not in matched_by_name]
        if missing_names:
            raise ValidationError(
                {"view_template": "DNS view(s) not found from view_template: " f"{', '.join(sorted(set(missing_names)))}"}
            )
        ordered_views = []
        seen_ids = set()
        for name in raw_names:
            view = matched_by_name[name]
            if view.id in seen_ids:
                continue
            ordered_views.append(view)
            seen_ids.add(view.id)
        self._view_lookup_cache[cache_key] = ordered_views
        return ordered_views

    def _get_zones_for_rule(self, rule, context, selected_views):
        """Experimental tuning: cache zone lookups by zone-name and view-id tuple."""
        if rule.zone_template:
            zone_name = self._render_template(rule.zone_template, context, "zone_template")
            view_ids = [view.id for view in selected_views]
            zone_cache_key = (zone_name, tuple(sorted(view_ids)))
            zones = self._zone_lookup_cache.get(zone_cache_key)
            if zones is None:
                zones = list(DNSZone.objects.filter(name=zone_name, dns_view_id__in=view_ids))
                self._zone_lookup_cache[zone_cache_key] = zones
            found_view_ids = {zone.dns_view_id for zone in zones}
            missing_view_ids = set(view_ids) - found_view_ids
            if missing_view_ids:
                missing_view_names = list(models.DNSView.objects.filter(id__in=missing_view_ids).values_list("name", flat=True))
                raise ValidationError(
                    {
                        "zone_template": (
                            f"Zone '{zone_name}' does not exist in selected DNS view(s): "
                            f"{', '.join(sorted(missing_view_names))}"
                        )
                    }
                )
            return zones
        raise ValidationError({"zone_template": "DNS rule must define a zone_template."})

    def _calculate_desired_record_data(self, rule, source_obj, phase=PHASE_UNKNOWN):
        """IP prefetch shortcut disabled; use base safe-style behavior."""
        # Previously this method set `_current_source_obj` so `_build_record_context`
        # could resolve `ip` from prefetched relation data.
        return super()._calculate_desired_record_data(rule, source_obj, phase=phase)

    def _build_record_context(self, base_context, record_data):
        """IP prefetch shortcut disabled; use base safe-style behavior."""
        # Previously this method attempted a fast path against `source_obj.ip_addresses`.
        return super()._build_record_context(base_context, record_data)

    def _update_tracking_record_dns_record(
        self,
        rule,
        source_obj,
        tracking_record,
        desired_record_data,
        phase,
    ):
        """Experimental tuning: in-place rename via direct SQL update."""
        dns_record = tracking_record.dns_record
        desired_name = desired_record_data["name"]
        if dns_record.name == desired_name:
            return "unchanged"
        try:
            updated = type(dns_record).objects.filter(pk=dns_record.pk).update(name=desired_name)
            if updated != 1:
                raise ValueError(f"Failed to update DNS record '{dns_record.pk}'")
            dns_record.name = desired_name
        except (ValidationError, IntegrityError, ValueError) as exc:
            self._log_record_update_failure(rule, source_obj, desired_record_data, exc, phase=phase)
            return "failed"
        return "updated"

