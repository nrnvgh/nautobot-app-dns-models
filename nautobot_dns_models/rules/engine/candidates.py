"""Candidate expansion helpers for DNS rule materialization."""

from __future__ import annotations

import logging
import re
import uuid

from nautobot.ipam import models as ipam_models

from nautobot_dns_models import models as dns_models
from nautobot_dns_models.exceptions import DNSRuleRenderedValueLookupError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.models import DNSZone

from nautobot_dns_models.rules.engine.constants import (
    PHASE_CANDIDATE_EXPANSION,
    REASON_INVALID_ADDRESS_UUID,
    REASON_VIEW_NOT_FOUND,
    REASON_VIEW_TEMPLATE_EMPTY,
    REASON_ZONE_NOT_FOUND,
)
from nautobot_dns_models.rules.engine.template_proxies import wrap_for_template

logger = logging.getLogger(__name__)


class RecordCandidateBuilder:
    """Build rule candidates and resolve per-candidate context/view/zone."""

    def __init__(self, cache, render_template, default_view_getter, apply_record_type_fields):
        """Store caches and callables used during candidate expansion.

        Args:
            cache: Shared engine cache container for view/zone lookups.
            render_template: Callable rendering template strings from context.
            default_view_getter: Callable returning the default DNS view.
            apply_record_type_fields: Callable applying per-record-type field mutations.
        """
        self._cache = cache
        self._render_template = render_template
        self._default_view_getter = default_view_getter
        self._apply_record_type_fields = apply_record_type_fields

    def get_record_data_variations_for_rule(self, rule, context, base_record_data):
        """Build list of record data dictionaries (1 for single, N for multiple records)."""
        record_type = rule.record_type
        if record_type in ("A", "AAAA"):
            if rule.value_template:
                address_result = self._render_template(rule.value_template, context, "value_template")
                address_ids = address_result.split()
                record_variations = self._build_record_variations(rule, base_record_data, address_ids)
                return self._filter_record_variations_by_ip_version(rule, context, record_variations)

            raise DNSRuleTemplateRenderedEmptyError("value_template", "missing", [])

        record_data = base_record_data.copy()
        self._apply_record_type_fields(rule, context, record_data)
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

    @staticmethod
    def _filter_record_variations_by_ip_version(rule, context, record_variations):
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

    def get_dns_views_for_rule(self, rule, context):
        """Cache DNS view resolution for repeated templates."""
        if not rule.view_template:
            return [self._default_view_getter()]

        rendered = self._render_template(rule.view_template, context, "view_template")
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
        zone_name = self._render_template(rule.zone_template, context, "zone_template")
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
                message=f"Zone '{zone_name}' does not exist in selected DNS view(s): {', '.join(sorted(missing_view_names))}",
                reason_code=REASON_ZONE_NOT_FOUND,
            )

        return zones

    @staticmethod
    def build_record_context(base_context, record_data):
        """Build per-record template context, resolving `ip` when present."""
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

    @staticmethod
    def build_record_context_with_preloaded_ips(base_context, record_data, preloaded_ip_by_id):
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
