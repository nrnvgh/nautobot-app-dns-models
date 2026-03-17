"""Primary DNS reconciliation engine."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from time import perf_counter

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.template import engines as django_template_engines
from jinja2 import TemplateError
from nautobot.ipam import models as ipam_models

from nautobot_dns_models import models as dns_models
from nautobot_dns_models.exceptions import (
    DNSTemplateEmptyError,
    DNSRecordContentTypeResolutionError,
    DNSRuleRenderedValueLookupError,
)
from nautobot_dns_models.models import DNSRuleRecord, DNSZone
from nautobot_dns_models.normalization import normalize_dns_name
from nautobot_dns_models.rules.engine import (
    PHASE_CREATE,
    PHASE_UPDATE_RECONCILE,
    REASON_VIEW_NOT_FOUND,
    REASON_VIEW_TEMPLATE_EMPTY,
    REASON_ZONE_NOT_FOUND,
    BaseDNSRuleEngine,
)
from nautobot_dns_models.rules.template_proxies import wrap_for_template

logger = logging.getLogger(__name__)


class DNSRuleEngine(BaseDNSRuleEngine):
    """Primary engine that reconciles in explicit batch phases."""

    # Tuned against ~65k update benchmarks:
    # - 250: ~2572 changed/sec (avg, best)
    # - 500: ~2459 changed/sec (avg)
    # - 1000: ~2468 changed/sec (avg)
    # Keep this constant in sync with docs/dev/reconcile_greenfield_performance_tally.md.
    BULK_RENAME_UPDATE_BATCH_SIZE = 250

    def __init__(self):
        """Initialize DNS rule engine and pipeline dispatch registry."""
        self._default_view_cache = None
        self._view_lookup_cache = {}
        self._zone_lookup_cache = {}
        self._applicable_rules_cache = {}
        self._compiled_template_cache = {}
        self._jinja_env = django_template_engines["jinja"].env
        self._pipeline_dispatch = {
            "rule_driven": self._process_objects,
        }
        self._active_pipeline_strategy = "rule_driven"
        self._pipeline_stage_metrics = {
            "batches": 0,
            "objects_total": 0,
            "tracking_rows_total": 0,
            "pending_rule_calculations_total": 0,
            "pending_bulk_updates_total": 0,
            "stage_seconds": {
                "fetch": 0.0,
                "planning": 0.0,
                "apply": 0.0,
                "bulk_flush": 0.0,
                "total": 0.0,
            },
        }

    @property
    def pipeline_strategy(self):
        """Return currently active pipeline strategy name."""
        return self._active_pipeline_strategy

    def process_objects_pipeline(self, source_objects, created=False):
        """Execute active pipeline handler for one source-object batch."""
        handler = self._pipeline_dispatch[self._active_pipeline_strategy]
        return handler(source_objects=source_objects, created=created)

    def process_object(self, source_obj, created=False):
        """Process one source object against applicable rules."""
        summary = self._initialize_processing_summary()
        content_type = ContentType.objects.get_for_model(source_obj)
        rules = self._get_applicable_rules(source_obj)
        rules_count = len(rules)

        if rules_count == 0:
            logger.debug(
                "No DNS rules found for %s - skipping DNS record processing for %s",
                content_type,
                source_obj,
            )
            return summary

        existing_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=str(source_obj.pk))
        existing_count = existing_records.count()
        summary["existing_rule_record_count"] = existing_count
        summary["had_existing_rule_records"] = existing_count > 0

        if created or existing_count == 0:
            create_summary = self._create_dns_records_for_object(source_obj, rules)
            summary["changed_record_count"] = create_summary["changed_record_count"]
            summary["changed"] = create_summary["changed"]
            summary["record_ops_create_count"] = create_summary["record_ops_create_count"]
            summary["record_ops_delete_count"] = create_summary["record_ops_delete_count"]
        else:
            update_summary = self._update_dns_records_for_object(source_obj, rules)
            summary["changed_record_count"] = update_summary["changed_record_count"]
            summary["changed"] = update_summary["changed"]
            summary["record_ops_create_count"] = update_summary["record_ops_create_count"]
            summary["record_ops_delete_count"] = update_summary["record_ops_delete_count"]

        return summary

    def register_pipeline_strategy(self, name, handler):
        """Register a custom pipeline strategy key to callable handler."""
        normalized = (name or "").strip().lower()
        if not normalized:
            return
        if not callable(handler):
            return
        self._pipeline_dispatch[normalized] = handler

    def set_pipeline_strategy(self, strategy):
        """Set active pipeline strategy for subsequent batch processing."""
        requested_strategy = (strategy or "rule_driven").strip().lower()
        if requested_strategy not in self._pipeline_dispatch:
            requested_strategy = "rule_driven"

        self._active_pipeline_strategy = requested_strategy

    def reset_pipeline_stage_metrics(self):
        """Reset cumulative stage metrics used for profiling/benchmark diagnostics."""
        self._pipeline_stage_metrics = {
            "batches": 0,
            "objects_total": 0,
            "tracking_rows_total": 0,
            "pending_rule_calculations_total": 0,
            "pending_bulk_updates_total": 0,
            "stage_seconds": {
                "fetch": 0.0,
                "planning": 0.0,
                "apply": 0.0,
                "bulk_flush": 0.0,
                "total": 0.0,
            },
        }

    def get_pipeline_stage_metrics(self):
        """Return cumulative and per-batch stage metrics for current run."""

        def _round_metric(value):
            return round(value, 3) if isinstance(value, float) else value

        stage_seconds = {
            stage_name: _round_metric(value)
            for stage_name, value in self._pipeline_stage_metrics["stage_seconds"].items()
        }
        metrics = {
            "batches": self._pipeline_stage_metrics["batches"],
            "objects_total": self._pipeline_stage_metrics["objects_total"],
            "tracking_rows_total": self._pipeline_stage_metrics["tracking_rows_total"],
            "pending_rule_calculations_total": self._pipeline_stage_metrics["pending_rule_calculations_total"],
            "pending_bulk_updates_total": self._pipeline_stage_metrics["pending_bulk_updates_total"],
            "stage_seconds": stage_seconds,
        }
        batches = metrics["batches"] or 1
        metrics["avg_per_batch"] = {
            "objects": _round_metric(metrics["objects_total"] / batches),
            "tracking_rows": _round_metric(metrics["tracking_rows_total"] / batches),
            "pending_rule_calculations": _round_metric(metrics["pending_rule_calculations_total"] / batches),
            "pending_bulk_updates": _round_metric(metrics["pending_bulk_updates_total"] / batches),
            "stage_seconds": {k: _round_metric(v / batches) for k, v in metrics["stage_seconds"].items()},
        }
        return metrics

    def _process_objects(self, source_objects, created=False):
        """Process one object batch through the default phased flow."""
        if not source_objects:
            return []

        if created:
            return [self.process_object(source_obj, created=True) for source_obj in source_objects]

        total_started_at = perf_counter()
        fetch_seconds = 0.0
        planning_seconds = 0.0
        apply_seconds = 0.0
        bulk_flush_seconds = 0.0

        # Stage 1: Fetch tracking rows
        fetch_started_at = perf_counter()
        fetch_result = self._fetch_tracking_data(source_objects)
        fetch_seconds += perf_counter() - fetch_started_at

        # Stage 2: Build work plan
        planning_started_at = perf_counter()
        plan_result = self._plan_work(
            source_objects=source_objects,
            tracking_by_object_id=fetch_result["tracking_by_object_id"],
        )
        # Stage 3: Materialize desired data from work plan
        self._materialize_desired_data(
            rule_work_items=plan_result["rule_work_items"],
            prepared_entry_by_object_id=plan_result["prepared_entry_by_object_id"],
            batch_address_ids=plan_result["batch_address_ids"],
        )
        planning_seconds += perf_counter() - planning_started_at

        # Stage 4: Apply reconciled changes
        apply_started_at = perf_counter()
        apply_result = self._apply_changes(plan_result["prepared_entries"])
        apply_seconds += perf_counter() - apply_started_at

        # Stage 5: Flush queued rename updates
        bulk_flush_started_at = perf_counter()
        self._flush_bulk_rename_updates(apply_result["pending_rename_updates"])
        bulk_flush_seconds += perf_counter() - bulk_flush_started_at
        self._record_pipeline_stage_metrics(
            {
                "objects": len(source_objects),
                "tracking_rows": len(fetch_result["tracking_rows"]),
                "pending_rule_calculations": plan_result["pending_rule_calculations"],
                "pending_bulk_updates": sum(
                    len(entries) for entries in apply_result["pending_rename_updates"].values()
                ),
                "stage_seconds": {
                    "fetch": fetch_seconds,
                    "planning": planning_seconds,
                    "apply": apply_seconds,
                    "bulk_flush": bulk_flush_seconds,
                    "total": perf_counter() - total_started_at,
                },
            }
        )
        return apply_result["summaries"]

    def _fetch_tracking_data(self, source_objects):
        """Stage 1: fetch and prefetch tracking rows for the current object batch."""
        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [source_obj.pk for source_obj in source_objects]
        tracking_rows = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))
        self._prefetch_tracking_dns_records(tracking_rows)

        tracking_by_object_id = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_object_id[tracking_row.object_id].append(tracking_row)

        return {
            "tracking_rows": tracking_rows,
            "tracking_by_object_id": tracking_by_object_id,
        }

    def _plan_work(
        self,
        source_objects,
        tracking_by_object_id,
    ):
        """Stage 2: build per-object prepared entries and per-rule work items."""
        prepared_entries = []
        prepared_entry_by_object_id = {}
        rule_work_items = defaultdict(list)
        batch_address_ids = set()

        for source_obj in source_objects:
            rules = self._get_applicable_rules(source_obj)
            desired_by_rule_id = {}
            failed_rule_ids = set()
            needed_rule_ids = set()

            for rule in rules:
                needs_records = self._object_needs_dns_records_for_rule(source_obj, rule)
                if not needs_records:
                    continue

                needed_rule_ids.add(rule.pk)
                try:
                    base_context = {"obj": wrap_for_template(source_obj)}
                    rendered_name = self._render_template(rule.name_template, base_context, "name_template")
                    shared_record_data = {"name": normalize_dns_name(rendered_name)}
                    record_variations = self._get_record_data_variations_for_rule(
                        rule, base_context, shared_record_data
                    )
                    requires_ip_context = self._requires_ip_context(rule)
                    if requires_ip_context:
                        for record_data in record_variations:
                            address_id = record_data.get("address_id")
                            if address_id:
                                batch_address_ids.add(address_id)

                    rule_work_items[rule.pk].append(
                        {
                            "object_id": source_obj.pk,
                            "rule": rule,
                            "base_context": base_context,
                            "record_variations": record_variations,
                            "requires_ip_context": requires_ip_context,
                        }
                    )
                except (TemplateError, DNSTemplateEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                    self._log_rule_processing_error(rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True)
                    failed_rule_ids.add(rule.pk)

            prepared_entry = {
                "source_obj": source_obj,
                "rules": rules,
                "needed_rule_ids": needed_rule_ids,
                "desired_by_rule_id": desired_by_rule_id,
                "failed_rule_ids": failed_rule_ids,
                "tracking_rows": tracking_by_object_id.get(source_obj.pk, []),
            }
            prepared_entries.append(prepared_entry)
            prepared_entry_by_object_id[source_obj.pk] = prepared_entry

        return {
            "prepared_entries": prepared_entries,
            "prepared_entry_by_object_id": prepared_entry_by_object_id,
            "rule_work_items": rule_work_items,
            "batch_address_ids": batch_address_ids,
            "pending_rule_calculations": sum(len(items) for items in rule_work_items.values()),
        }

    def _materialize_desired_data(
        self,
        rule_work_items,
        prepared_entry_by_object_id,
        batch_address_ids,
    ):
        """Stage 3: materialize desired record data into prepared entries."""
        preloaded_ip_by_id = {}
        if batch_address_ids:
            preloaded_ip_by_id = ipam_models.IPAddress.objects.in_bulk(batch_address_ids)

        for work_items in rule_work_items.values():
            for pending in work_items:
                prepared_entry = prepared_entry_by_object_id.get(pending["object_id"])
                if prepared_entry is None:
                    continue

                rule = pending["rule"]
                source_obj = prepared_entry["source_obj"]
                base_context = pending["base_context"]
                record_variations = pending["record_variations"]
                requires_ip_context = pending["requires_ip_context"]
                desired_by_rule_id = prepared_entry["desired_by_rule_id"]
                failed_rule_ids = prepared_entry["failed_rule_ids"]

                if rule.pk in failed_rule_ids:
                    continue

                all_record_data = []
                for record_data in record_variations:
                    try:
                        if requires_ip_context:
                            record_context = self._build_record_context_with_preloaded_ips(
                                base_context, record_data, preloaded_ip_by_id
                            )
                        else:
                            record_context = dict(base_context)
                            record_context["record"] = record_data.copy()

                        selected_views = self._get_dns_views_for_rule(rule, record_context)
                        zones = self._get_zones_for_rule(rule, record_context, selected_views)
                        for zone in zones:
                            all_record_data.append({**record_data, "zone": zone})

                    except (
                        DNSTemplateEmptyError,
                        DNSRuleRenderedValueLookupError,
                        TemplateError,
                        ValueError,
                    ) as exc:
                        self._log_candidate_skip(rule, source_obj, record_data, exc, phase=PHASE_UPDATE_RECONCILE)
                        continue

                desired_by_rule_id[rule.pk] = all_record_data

    def _apply_changes(self, prepared_entries):
        """Stage 4: apply prepared reconcile entries and queue rename updates."""
        pending_rename_updates = defaultdict(list)
        summaries = []
        for entry in prepared_entries:
            summaries.append(self._apply_prepared_reconcile_entry(entry, bulk_update_collector=pending_rename_updates))
        return {
            "summaries": summaries,
            "pending_rename_updates": pending_rename_updates,
        }

    def _requires_ip_context(self, rule):
        """Production tuning: only resolve ip context when templates reference ip."""
        template_text = " ".join([rule.view_template or "", rule.zone_template or ""])
        return bool(re.search(r"\bip\b", template_text))

    def _render_template(self, template_str, context, field_name):
        """Render from cached compiled Jinja templates."""
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
        """Scope-key cache for applicable-rule resolution."""
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
        """Cache DNS view resolution for repeated templates."""
        if not rule.view_template:
            if self._default_view_cache is None:
                self._default_view_cache = dns_models.DNSView.objects.get(pk=dns_models.get_default_view_pk())
            return [self._default_view_cache]

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
        cached_views = self._view_lookup_cache.get(cache_key)
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

        self._view_lookup_cache[cache_key] = ordered_views

        return ordered_views

    def _get_zones_for_rule(self, rule, context, selected_views):
        """Cache zone lookups by zone-name and view-id tuple."""
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
            missing_view_names = list(dns_models.DNSView.objects.filter(id__in=missing_view_ids).values_list("name", flat=True))
            raise DNSRuleRenderedValueLookupError(
                field_name="zone_template",
                message=(
                    f"Zone '{zone_name}' does not exist in selected DNS view(s): "
                    f"{', '.join(sorted(missing_view_names))}"
                ),
                reason_code=REASON_ZONE_NOT_FOUND,
            )
        return zones

    def _update_tracking_record_dns_record(
        self,
        rule,
        source_obj,
        tracking_record,
        desired_record_data,
        phase,
    ):
        """In-place rename via direct SQL update."""
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

    def _create_dns_records_for_object(self, source_obj, applicable_rules):
        """Create records for one source object."""
        changed_record_count = 0
        for rule in applicable_rules:
            if not self._object_needs_dns_records_for_rule(source_obj, rule):
                continue
            try:
                created_records = self._create_dns_record_from_rule(rule, source_obj)
                changed_record_count += len(created_records)
            except (TemplateError, DNSTemplateEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._log_rule_processing_error(rule, source_obj, exc, phase=PHASE_CREATE, cleanup=False)
                continue
        return {
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "record_ops_create_count": changed_record_count,
            "record_ops_delete_count": 0,
        }

    def _update_dns_records_for_object(self, source_obj, applicable_rules):
        """Update/reconcile records for one source object."""
        delete_count = self._cleanup_orphaned_records(source_obj, applicable_rules)
        create_count = 0
        update_count = 0

        for rule in applicable_rules:
            if not self._object_needs_dns_records_for_rule(source_obj, rule):
                delete_count += self._cleanup_records_for_rule(rule, source_obj)
                continue
            try:
                reconcile_summary = self._reconcile_records_for_rule(rule, source_obj)
                create_count += reconcile_summary["create"]
                delete_count += reconcile_summary["delete"]
                update_count += reconcile_summary.get("update", 0)
            except (TemplateError, DNSTemplateEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._log_rule_processing_error(rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True)
                delete_count += self._cleanup_records_for_rule(rule, source_obj)

        changed_record_count = create_count + delete_count + update_count
        return {
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "record_ops_create_count": create_count,
            "record_ops_delete_count": delete_count,
        }

    def _reconcile_records_for_rule(self, rule, source_obj):
        """Reconcile records for one rule/object pair."""
        tracking_records = self._get_existing_tracking_records(rule, source_obj)
        existing_records_by_content = {}
        existing_records_by_identity = {}
        for tracking_record in tracking_records:
            dns_record = tracking_record.dns_record
            content_key = self._get_record_content_key(dns_record)
            identity_key = self._get_record_identity_key(dns_record)
            existing_records_by_content[content_key] = tracking_record
            existing_records_by_identity[identity_key] = tracking_record

        desired_record_data = self._calculate_desired_record_data(rule, source_obj, phase=PHASE_UPDATE_RECONCILE)
        desired_records_by_content = {}
        desired_records_by_identity = {}
        for record_data in desired_record_data:
            content_key = self._get_record_content_key_from_data(record_data, rule.record_type)
            identity_key = self._get_record_identity_key_from_data(record_data, rule.record_type)
            desired_records_by_content[content_key] = record_data
            desired_records_by_identity[identity_key] = record_data

        existing_keys = set(existing_records_by_content.keys())
        desired_keys = set(desired_records_by_content.keys())
        existing_identity_keys = set(existing_records_by_identity.keys())
        desired_identity_keys = set(desired_records_by_identity.keys())

        records_to_delete_by_identity = existing_identity_keys - desired_identity_keys
        records_to_create_by_identity = desired_identity_keys - existing_identity_keys
        records_to_check_for_update = existing_identity_keys & desired_identity_keys

        for identity_key in records_to_delete_by_identity:
            self._delete_tracking_and_dns_record(existing_records_by_identity[identity_key])

        updated_count = 0
        keep_count = 0
        skipped_update = 0
        for identity_key in records_to_check_for_update:
            tracking_record = existing_records_by_identity[identity_key]
            desired_record = desired_records_by_identity[identity_key]
            update_result = self._update_tracking_record_dns_record(
                rule=rule,
                source_obj=source_obj,
                tracking_record=tracking_record,
                desired_record_data=desired_record,
                phase=PHASE_UPDATE_RECONCILE,
            )
            if update_result == "updated":
                updated_count += 1
            elif update_result == "unchanged":
                keep_count += 1
            else:
                skipped_update += 1

        created_records = []
        if records_to_create_by_identity:
            records_to_create_data = [desired_records_by_identity[key] for key in records_to_create_by_identity]
            created_records = self._create_records_from_data(
                rule, source_obj, records_to_create_data, phase=PHASE_UPDATE_RECONCILE
            )

        skipped_create = len(records_to_create_by_identity) - len(created_records)
        skipped_total = skipped_create + skipped_update
        self._log_reconcile_summary(
            rule=rule,
            source_obj=source_obj,
            counts={
                "existing": len(existing_keys),
                "desired": len(desired_keys),
                "keep": keep_count,
                "create": len(created_records),
                "delete": len(records_to_delete_by_identity),
                "skipped": skipped_total,
            },
        )
        return {
            "existing": len(existing_keys),
            "desired": len(desired_keys),
            "keep": keep_count,
            "create": len(created_records),
            "delete": len(records_to_delete_by_identity),
            "update": updated_count,
            "skipped": skipped_total,
            "changed_record_count": len(created_records) + len(records_to_delete_by_identity) + updated_count,
        }

    def _record_pipeline_stage_metrics(self, batch_metrics):
        """Accumulate one batch worth of stage metrics into engine totals."""
        self._pipeline_stage_metrics["batches"] += 1
        self._pipeline_stage_metrics["objects_total"] += batch_metrics["objects"]
        self._pipeline_stage_metrics["tracking_rows_total"] += batch_metrics["tracking_rows"]
        self._pipeline_stage_metrics["pending_rule_calculations_total"] += batch_metrics["pending_rule_calculations"]
        self._pipeline_stage_metrics["pending_bulk_updates_total"] += batch_metrics["pending_bulk_updates"]
        for stage_name, value in batch_metrics["stage_seconds"].items():
            self._pipeline_stage_metrics["stage_seconds"][stage_name] += value

    def _object_needs_dns_records_for_rule(self, source_obj, rule):
        """Hybrid fast-path: avoid per-object SQL checks when prefetch cache is present."""
        if rule.record_type not in ("A", "AAAA"):
            return True

        target_ip_version = 4 if rule.record_type == "A" else 6
        prefetched = getattr(source_obj, "_prefetched_objects_cache", {}).get("ip_addresses")
        if prefetched is not None:
            return any(getattr(ip_obj, "ip_version", None) == target_ip_version for ip_obj in prefetched)

        return super()._object_needs_dns_records_for_rule(source_obj, rule)

    def _build_record_context_with_preloaded_ips(self, base_context, record_data, preloaded_ip_by_id):
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

    def _prefetch_tracking_dns_records(self, tracking_rows):
        """Batch-resolve GenericFK dns_record objects and attach them to tracking rows."""
        if not tracking_rows:
            return

        tracking_rows_by_record_content_type = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_rows_by_record_content_type[tracking_row.dns_record_content_type_id].append(tracking_row)

        content_types = ContentType.objects.in_bulk(tracking_rows_by_record_content_type.keys())
        for record_content_type_id, rows in tracking_rows_by_record_content_type.items():
            record_content_type = content_types[record_content_type_id]
            record_model = record_content_type.model_class()
            if record_model is None:
                #
                # If this happens, something fairly serious is going on, so bail out.
                raise DNSRecordContentTypeResolutionError(
                    "Unable to resolve DNS record content type to model class: "
                    f"id={record_content_type_id} "
                    f"label={record_content_type.app_label}.{record_content_type.model} "
                    f"tracking_rows={len(rows)}"
                )

            record_ids = [tracking_row.dns_record_object_id for tracking_row in rows]
            records_by_id = record_model.objects.in_bulk(record_ids)
            for tracking_row in rows:
                tracking_row._prefetched_dns_record = records_by_id.get(tracking_row.dns_record_object_id)

    def _apply_prepared_reconcile_entry(
        self,
        entry,
        bulk_update_collector=None,
    ):
        """Apply prepared desired/tracking data for one source object."""
        source_obj = entry["source_obj"]
        rules = entry["rules"]
        needed_rule_ids = entry.get("needed_rule_ids", set())
        desired_by_rule_id = entry["desired_by_rule_id"]
        failed_rule_ids = entry["failed_rule_ids"]
        tracking_rows = entry["tracking_rows"]

        summary = self._initialize_processing_summary()
        existing_count = len(tracking_rows)
        summary["existing_rule_record_count"] = existing_count
        summary["had_existing_rule_records"] = existing_count > 0

        if not rules:
            return summary

        tracking_by_rule_id = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_rule_id[tracking_row.rule_id].append(tracking_row)

        applicable_rule_ids = {rule.pk for rule in rules}
        delete_count = self._cleanup_orphaned_records_prefetched(tracking_by_rule_id, applicable_rule_ids)
        create_count = 0
        update_count = 0

        for rule in rules:
            if needed_rule_ids and rule.pk not in needed_rule_ids:
                delete_count += self._cleanup_records_for_rule_prefetched(tracking_by_rule_id, rule.pk)
                continue

            if rule.pk in failed_rule_ids:
                delete_count += self._cleanup_records_for_rule_prefetched(tracking_by_rule_id, rule.pk)
                continue

            reconcile_summary = self._reconcile_records_for_rule_with_desired(
                rule=rule,
                source_obj=source_obj,
                tracking_records=tracking_by_rule_id.get(rule.pk, []),
                desired_record_data=desired_by_rule_id.get(rule.pk, []),
                bulk_update_collector=bulk_update_collector,
            )
            create_count += reconcile_summary["create"]
            delete_count += reconcile_summary["delete"]
            update_count += reconcile_summary.get("update", 0)

        changed_record_count = create_count + delete_count + update_count
        summary["changed_record_count"] = changed_record_count
        summary["changed"] = changed_record_count > 0
        summary["record_ops_create_count"] = create_count
        summary["record_ops_delete_count"] = delete_count

        return summary

    def _cleanup_orphaned_records_prefetched(
        self,
        tracking_by_rule_id,
        applicable_rule_ids,
    ):
        """Delete tracking/DNS rows for rules no longer applicable."""
        deleted_count = 0

        for rule_id in list(tracking_by_rule_id.keys()):
            if rule_id in applicable_rule_ids:
                continue
            deleted_count += self._cleanup_records_for_rule_prefetched(tracking_by_rule_id, rule_id)

        return deleted_count

    def _cleanup_records_for_rule_prefetched(
        self,
        tracking_by_rule_id,
        rule_id,
    ):
        """Delete all tracking/DNS rows for one rule from prefetched group."""
        tracking_rows = tracking_by_rule_id.pop(rule_id, [])
        for tracking_row in tracking_rows:
            self._delete_tracking_and_dns_record(tracking_row)
        return len(tracking_rows)

    def _reconcile_records_for_rule_with_desired(
        self,
        rule,
        source_obj,
        tracking_records,
        desired_record_data,
        bulk_update_collector=None,
    ):
        """Reconcile one rule using caller-provided tracking rows and desired rows."""
        def _resolve_dns_record(tracking_record):
            dns_record = getattr(tracking_record, "_prefetched_dns_record", None)
            if dns_record is None:
                dns_record = tracking_record.dns_record

            return dns_record

        existing_records_by_identity = {}
        for tracking_record in tracking_records:
            dns_record = _resolve_dns_record(tracking_record)
            if dns_record is None:
                continue

            identity_key = self._get_record_identity_key(dns_record)
            existing_records_by_identity[identity_key] = tracking_record

        desired_records_by_identity = {}
        for record_data in desired_record_data:
            identity_key = self._get_record_identity_key_from_data(record_data, rule.record_type)
            desired_records_by_identity[identity_key] = record_data

        existing_identity_keys = set(existing_records_by_identity.keys())
        desired_identity_keys = set(desired_records_by_identity.keys())

        records_to_delete_by_identity = existing_identity_keys - desired_identity_keys
        records_to_create_by_identity = desired_identity_keys - existing_identity_keys
        records_to_check_for_update = existing_identity_keys & desired_identity_keys

        for identity_key in records_to_delete_by_identity:
            self._delete_tracking_and_dns_record(existing_records_by_identity[identity_key])

        updated_count = 0
        keep_count = 0
        skipped_update = 0
        for identity_key in records_to_check_for_update:
            tracking_record = existing_records_by_identity[identity_key]
            desired_record = desired_records_by_identity[identity_key]
            if bulk_update_collector is not None:
                dns_record = _resolve_dns_record(tracking_record)
                if dns_record is None:
                    skipped_update += 1
                    continue

                desired_name = desired_record["name"]
                if dns_record.name == desired_name:
                    keep_count += 1
                    continue

                dns_record.name = desired_name
                bulk_update_collector[type(dns_record)].append(dns_record)
                updated_count += 1
            else:
                update_result = self._update_tracking_record_dns_record(
                    rule=rule,
                    source_obj=source_obj,
                    tracking_record=tracking_record,
                    desired_record_data=desired_record,
                    phase=PHASE_UPDATE_RECONCILE,
                )
                if update_result == "updated":
                    updated_count += 1
                elif update_result == "unchanged":
                    keep_count += 1
                else:
                    skipped_update += 1

        created_records = []
        if records_to_create_by_identity:
            records_to_create_data = [desired_records_by_identity[key] for key in records_to_create_by_identity]
            created_records = self._create_records_from_data(
                rule, source_obj, records_to_create_data, phase=PHASE_UPDATE_RECONCILE
            )

        skipped_create = len(records_to_create_by_identity) - len(created_records)
        skipped_total = skipped_create + skipped_update
        self._log_reconcile_summary(
            rule=rule,
            source_obj=source_obj,
            counts={
                "existing": len(existing_identity_keys),
                "desired": len(desired_identity_keys),
                "keep": keep_count,
                "create": len(created_records),
                "delete": len(records_to_delete_by_identity),
                "skipped": skipped_total,
            },
        )
        return {
            "create": len(created_records),
            "delete": len(records_to_delete_by_identity),
            "update": updated_count,
            "skipped": skipped_total,
        }

    def _flush_bulk_rename_updates(
        self,
        bulk_update_collector,
    ):
        """Execute queued rename updates in bulk."""
        for record_model, update_entries in bulk_update_collector.items():
            if not update_entries:
                continue
            record_model.objects.bulk_update(update_entries, ["name"], batch_size=self.BULK_RENAME_UPDATE_BATCH_SIZE)
