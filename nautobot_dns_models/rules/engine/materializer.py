"""Record materialization collaborator."""

import logging
import re
import uuid
from functools import cached_property

from jinja2 import TemplateError
from nautobot.ipam import models as ipam_models

from nautobot_dns_models import models as dns_models
from nautobot_dns_models.exceptions import DNSRuleRenderedValueLookupError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.models import DNSZone
from nautobot_dns_models.normalization import normalize_dns_name_if_enabled

from .constants import (
    PHASE_CANDIDATE_EXPANSION,
    REASON_INVALID_ADDRESS_UUID,
    REASON_VIEW_NOT_FOUND,
    REASON_VIEW_TEMPLATE_EMPTY,
    REASON_ZONE_NOT_FOUND,
)
from .template_proxies import wrap_for_template

logger = logging.getLogger(__name__)


class RecordMaterializer:
    """Materialize rendered DNS candidate data from rules and objects."""

    def __init__(self, engine, cache, context):
        """Store collaborator references and shared runtime context."""
        self._engine = engine
        self._cache = cache
        self._context = context
        self._engine_logger = engine._engine_logger

    @cached_property
    def _default_view(self):
        """Return the default DNS view, cached per engine instance."""
        logger.debug("[default_view] Getting default DNS view")
        return dns_models.DNSView.objects.get(pk=dns_models.get_default_view_pk())

    def render_template(self, template_str, context, field_name):
        """Render from cached compiled Jinja templates."""
        if "{{" not in template_str and "{%" not in template_str and "{#" not in template_str:
            result = template_str.strip()
            if not result:
                raise DNSRuleTemplateRenderedEmptyError(field_name, template_str, list(context.keys()))
            return result

        compiled_template = self._cache.compiled_template_cache.get(template_str)
        if compiled_template is None:
            if len(self._cache.compiled_template_cache) >= 1024:
                self._cache.compiled_template_cache.clear()
            compiled_template = self._context.jinja_env.from_string(template_str)
            self._cache.compiled_template_cache[template_str] = compiled_template

        raw_result = compiled_template.render(context)
        result = raw_result.strip()
        if not result:
            raise DNSRuleTemplateRenderedEmptyError(field_name, template_str, list(context.keys()))

        if "{{ no such element:" in raw_result:
            raise DNSRuleTemplateRenderedEmptyError(field_name, f"{template_str} → {result}", list(context.keys()))

        return result

    def _requires_ip_context(self, rule):
        template_text = " ".join([rule.view_template or "", rule.zone_template or ""])
        return bool(re.search(r"\bip\b", template_text))

    def calculate_desired_record_data(self, rule, source_obj, phase):
        """Calculate desired DNS record data for one rule/object pair."""
        base_context = {"obj": wrap_for_template(source_obj)}
        rendered_name = self.render_template(rule.name_template, base_context, "name_template")
        shared_record_data = {"name": normalize_dns_name_if_enabled(rendered_name)}
        requires_ip_context = self._requires_ip_context(rule)
        all_record_data = []
        record_variations = self.get_record_data_variations_for_rule(rule, base_context, shared_record_data)

        for record_data in record_variations:
            try:
                if requires_ip_context:
                    record_context = self._build_record_context(base_context, record_data)
                else:
                    record_context = dict(base_context)
                    record_context["record"] = record_data.copy()

                selected_views = self.get_dns_views_for_rule(rule, record_context)
                zones = self.get_zones_for_rule(rule, record_context, selected_views)
                for zone in zones:
                    all_record_data.append({**record_data, "zone": zone})

            except (
                DNSRuleTemplateRenderedEmptyError,
                DNSRuleRenderedValueLookupError,
                TemplateError,
                ValueError,
            ) as exc:
                self._engine_logger.log_candidate_skip(rule, source_obj, record_data, exc, phase=phase)
                continue

        return all_record_data

    def get_record_data_variations_for_rule(self, rule, context, base_record_data):
        """Build list of record data dictionaries (1 for single, N for multiple records)."""
        record_type = rule.record_type
        if record_type in ("A", "AAAA"):
            if rule.value_template:
                address_result = self.render_template(rule.value_template, context, "value_template")
                address_ids = address_result.split()
                record_variations = self._build_record_variations(rule, base_record_data, address_ids)
                return self._filter_record_variations_by_ip_version(rule, context, record_variations)

            raise DNSRuleTemplateRenderedEmptyError("value_template", "missing", [])

        record_data = base_record_data.copy()
        self._add_record_type_fields_single(rule, context, record_data)

        return [record_data]

    def _build_record_variations(self, rule, base_record_data, address_ids):
        record_variations = []
        for address_id in address_ids:
            address_id = address_id.strip()
            if not address_id:
                continue

            try:
                parsed_address_id = uuid.UUID(address_id)
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
            record_data["address_id"] = parsed_address_id
            record_variations.append(record_data)

        return record_variations

    def _filter_record_variations_by_ip_version(self, rule, context, record_variations):
        if rule.record_type not in ("A", "AAAA") or not record_variations:
            return record_variations

        target_ip_version = 4 if rule.record_type == "A" else 6
        candidate_address_ids = [record_data["address_id"] for record_data in record_variations]
        context_obj = context.get("obj")
        source_obj = getattr(context_obj, "_obj", context_obj)

        prefetched_ips = getattr(source_obj, "_prefetched_objects_cache", {}).get("ip_addresses")
        if prefetched_ips is not None:
            allowed_ids = {ip_obj.id for ip_obj in prefetched_ips if ip_obj.ip_version == target_ip_version}
        else:
            allowed_ids = set(
                ipam_models.IPAddress.objects.filter(
                    id__in=candidate_address_ids, ip_version=target_ip_version
                ).values_list("id", flat=True)
            )

        return [record_data for record_data in record_variations if record_data["address_id"] in allowed_ids]

    def _add_record_type_fields_single(self, rule, context, record_data):
        if record_type_method := getattr(self._engine, f"_add_record_type_fields_{rule.record_type}", None):
            record_type_method(rule, context, record_data)  # pylint: disable=not-callable

    def get_dns_views_for_rule(self, rule, context):
        """Cache DNS view resolution for repeated templates."""
        if not rule.view_template:
            return [self._default_view]

        rendered = self.render_template(rule.view_template, context, "view_template")
        raw_names = [token.strip() for token in re.split(r"[\s,]+", rendered) if token.strip()]
        if not raw_names:
            raise DNSRuleRenderedValueLookupError(
                field_name="view_template",
                message="view_template rendered no DNS view names.",
                reason_code=REASON_VIEW_TEMPLATE_EMPTY,
            )

        requested_names = list(dict.fromkeys(raw_names))
        cache_key = tuple(requested_names)
        cached_views = self._cache.view_lookup_cache.get(cache_key)
        if cached_views is not None:
            return cached_views

        matched_views = list(dns_models.DNSView.objects.filter(name__in=requested_names))
        matched_by_name = {view.name: view for view in matched_views}
        missing_names = [name for name in raw_names if name not in matched_by_name]
        if missing_names:
            raise DNSRuleRenderedValueLookupError(
                field_name="view_template",
                message=f"DNS view(s) not found from view_template: {', '.join(sorted(set(missing_names)))}",
                reason_code=REASON_VIEW_NOT_FOUND,
            )

        ordered_views = []
        seen_ids = set()
        for name in raw_names:
            view = matched_by_name[name]
            if view.id in seen_ids:
                continue
            ordered_views.append(view)
            seen_ids.add(view.id)

        self._cache.view_lookup_cache[cache_key] = ordered_views

        return ordered_views

    def get_zones_for_rule(self, rule, context, selected_views):
        """Cache zone lookups by zone-name and view-id tuple."""
        zone_name = self.render_template(rule.zone_template, context, "zone_template")
        view_ids = [view.id for view in selected_views]
        zone_cache_key = (zone_name, tuple(sorted(view_ids)))
        zones = self._cache.zone_lookup_cache.get(zone_cache_key)
        if zones is None:
            zones = list(DNSZone.objects.filter(name=zone_name, dns_view_id__in=view_ids))
            self._cache.zone_lookup_cache[zone_cache_key] = zones

        found_view_ids = {zone.dns_view_id for zone in zones}
        missing_view_ids = set(view_ids) - found_view_ids
        if missing_view_ids:
            missing_view_names = list(
                dns_models.DNSView.objects.filter(id__in=missing_view_ids).values_list("name", flat=True)
            )
            raise DNSRuleRenderedValueLookupError(
                field_name="zone_template",
                message=(
                    f"Zone '{zone_name}' does not exist in selected DNS view(s): "
                    f"{', '.join(sorted(missing_view_names))}"
                ),
                reason_code=REASON_ZONE_NOT_FOUND,
            )

        return zones

    def _build_record_context(self, base_context, record_data):
        context = dict(base_context)
        context["record"] = record_data.copy()
        address_id = record_data.get("address_id")
        if address_id:
            ip_obj = ipam_models.IPAddress.objects.filter(pk=address_id).first()
            if ip_obj is None:
                raise DNSRuleRenderedValueLookupError(
                    field_name="value_template",
                    message=f"Resolved IP address '{address_id}' was not found.",
                )
            context["ip"] = wrap_for_template(ip_obj)

        return context

    def build_record_context_with_preloaded_ips(self, base_context, record_data, preloaded_ip_by_id):
        """Build context using preloaded batch IP map, with fallback lookup for misses."""
        context = dict(base_context)
        context["record"] = record_data.copy()
        address_id = record_data.get("address_id")
        if not address_id:
            return context

        ip_obj = preloaded_ip_by_id.get(address_id)
        if ip_obj is None:
            ip_obj = ipam_models.IPAddress.objects.filter(pk=address_id).first()

        if ip_obj is None:
            raise DNSRuleRenderedValueLookupError(
                field_name="value_template",
                message=f"Resolved IP address '{address_id}' was not found.",
            )

        context["ip"] = wrap_for_template(ip_obj)
        return context
