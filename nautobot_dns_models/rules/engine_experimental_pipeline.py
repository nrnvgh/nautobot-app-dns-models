"""Experimental batch-native reconciliation engine."""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Any

from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine import (
    ContentType,
    DNSRuleRecord,
    DNSTemplateEmptyError,
    DNSZone,
    PHASE_UPDATE_RECONCILE,
    TemplateError,
    ValidationError,
    ipam_models,
    logger,
    normalize_dns_name,
    wrap_for_template,
)
from nautobot_dns_models.rules.engine_experimental import ExperimentalDNSRuleEngine
from nautobot_dns_models.rules.pipeline_strategies import (
    HybridPipelineStrategy,
    PythonFirstPipelineStrategy,
    RuleDrivenPipelineStrategy,
    SQLHeavyPipelineStrategy,
)


class ExperimentalPipelineDNSRuleEngine(ExperimentalDNSRuleEngine):
    """Experimental engine that reconciles in explicit batch phases."""

    # Tuned against ~65k update benchmarks:
    # - 250: ~2572 changed/sec (avg, best)
    # - 500: ~2459 changed/sec (avg)
    # - 1000: ~2468 changed/sec (avg)
    # Keep this constant in sync with docs/dev/reconcile_greenfield_performance_tally.md.
    BULK_RENAME_UPDATE_BATCH_SIZE = 250

    def __init__(self):
        """Initialize experimental pipeline engine and strategy registry."""
        super().__init__()
        self._pipeline_strategies = {
            "python_first": PythonFirstPipelineStrategy(),
            "hybrid": HybridPipelineStrategy(),
            "rule_driven": RuleDrivenPipelineStrategy(),
            "sql_heavy": SQLHeavyPipelineStrategy(),
        }
        self._active_pipeline_strategy = "python_first"
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

    def set_pipeline_strategy(self, strategy: str | None) -> None:
        """Set active pipeline strategy for subsequent batch processing."""
        requested_strategy = (strategy or "python_first").strip().lower()
        if requested_strategy not in self._pipeline_strategies:
            requested_strategy = "python_first"
        self._active_pipeline_strategy = requested_strategy

    @property
    def pipeline_strategy(self) -> str:
        """Return currently active pipeline strategy name."""
        return self._active_pipeline_strategy

    def reset_pipeline_stage_metrics(self) -> None:
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

    def get_pipeline_stage_metrics(self) -> dict[str, Any]:
        """Return cumulative and per-batch stage metrics for current run."""
        metrics = {
            "batches": self._pipeline_stage_metrics["batches"],
            "objects_total": self._pipeline_stage_metrics["objects_total"],
            "tracking_rows_total": self._pipeline_stage_metrics["tracking_rows_total"],
            "pending_rule_calculations_total": self._pipeline_stage_metrics["pending_rule_calculations_total"],
            "pending_bulk_updates_total": self._pipeline_stage_metrics["pending_bulk_updates_total"],
            "stage_seconds": dict(self._pipeline_stage_metrics["stage_seconds"]),
        }
        batches = metrics["batches"] or 1
        metrics["avg_per_batch"] = {
            "objects": metrics["objects_total"] / batches,
            "tracking_rows": metrics["tracking_rows_total"] / batches,
            "pending_rule_calculations": metrics["pending_rule_calculations_total"] / batches,
            "pending_bulk_updates": metrics["pending_bulk_updates_total"] / batches,
            "stage_seconds": {k: v / batches for k, v in metrics["stage_seconds"].items()},
        }
        return metrics

    def _record_pipeline_stage_metrics(self, batch_metrics: dict[str, Any]) -> None:
        """Accumulate one batch worth of stage metrics into engine totals."""
        self._pipeline_stage_metrics["batches"] += 1
        self._pipeline_stage_metrics["objects_total"] += batch_metrics["objects"]
        self._pipeline_stage_metrics["tracking_rows_total"] += batch_metrics["tracking_rows"]
        self._pipeline_stage_metrics["pending_rule_calculations_total"] += batch_metrics["pending_rule_calculations"]
        self._pipeline_stage_metrics["pending_bulk_updates_total"] += batch_metrics["pending_bulk_updates"]
        for stage_name, value in batch_metrics["stage_seconds"].items():
            self._pipeline_stage_metrics["stage_seconds"][stage_name] += value

    def process_objects_pipeline(self, source_objects: list[Any], created: bool = False) -> list[dict[str, Any]]:
        """Execute current pipeline strategy for one source-object batch."""
        strategy = self._pipeline_strategies[self._active_pipeline_strategy]
        return strategy.process_objects_pipeline(self, source_objects, created=created)

    def _process_objects_pipeline_python_first(
        self, source_objects: list[Any], created: bool = False
    ) -> list[dict[str, Any]]:
        """Run a four-phase pipeline for a same-model object batch."""
        if not source_objects:
            return []
        if created:
            return [self.process_object(source_obj, created=True) for source_obj in source_objects]

        total_started_at = perf_counter()
        fetch_seconds = 0.0
        planning_seconds = 0.0
        apply_seconds = 0.0
        bulk_flush_seconds = 0.0

        fetch_started_at = perf_counter()
        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [source_obj.pk for source_obj in source_objects]
        tracking_rows = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))
        self._prefetch_tracking_dns_records(tracking_rows)

        tracking_by_object_id: dict[Any, list[DNSRuleRecord]] = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_object_id[tracking_row.object_id].append(tracking_row)
        fetch_seconds += perf_counter() - fetch_started_at

        planning_started_at = perf_counter()
        prepared_entries = []
        pending_rule_calculations: list[dict[str, Any]] = []
        batch_address_ids: set[Any] = set()
        for source_obj in source_objects:
            rules = self._get_applicable_rules(source_obj)
            desired_by_rule_id: dict[Any, list[dict[str, Any]]] = {}
            failed_rule_ids: set[Any] = set()
            for rule in rules:
                if not self._object_needs_dns_records_for_rule(source_obj, rule):
                    continue
                try:
                    base_context = {"obj": wrap_for_template(source_obj)}
                    rendered_name = self._render_template(rule.name_template, base_context, "name_template")
                    shared_record_data = {"name": normalize_dns_name(rendered_name)}
                    record_variations = self._get_record_data_variations_for_rule(rule, base_context, shared_record_data)
                    requires_ip_context = self._requires_ip_context(rule)
                    if requires_ip_context:
                        for record_data in record_variations:
                            address_id = record_data.get("address_id")
                            if address_id:
                                batch_address_ids.add(address_id)
                    pending_rule_calculations.append(
                        {
                            "source_obj": source_obj,
                            "rule": rule,
                            "base_context": base_context,
                            "record_variations": record_variations,
                            "requires_ip_context": requires_ip_context,
                            "desired_by_rule_id": desired_by_rule_id,
                            "failed_rule_ids": failed_rule_ids,
                        }
                    )
                except (TemplateError, DNSTemplateEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                    self._log_rule_processing_error(
                        rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True
                    )
                    failed_rule_ids.add(rule.pk)
            prepared_entries.append(
                {
                    "source_obj": source_obj,
                    "rules": rules,
                    "desired_by_rule_id": desired_by_rule_id,
                    "failed_rule_ids": failed_rule_ids,
                    "tracking_rows": tracking_by_object_id.get(source_obj.pk, []),
                }
            )

        preloaded_ip_by_id: dict[Any, Any] = {}
        if batch_address_ids:
            preloaded_ip_by_id = ipam_models.IPAddress.objects.in_bulk(batch_address_ids)

        for pending in pending_rule_calculations:
            rule: DNSRule = pending["rule"]
            source_obj = pending["source_obj"]
            base_context: dict[str, Any] = pending["base_context"]
            record_variations: list[dict[str, Any]] = pending["record_variations"]
            requires_ip_context: bool = pending["requires_ip_context"]
            desired_by_rule_id: dict[Any, list[dict[str, Any]]] = pending["desired_by_rule_id"]
            failed_rule_ids: set[Any] = pending["failed_rule_ids"]

            if rule.pk in failed_rule_ids:
                continue

            all_record_data: list[dict[str, Any]] = []
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
                except (ValidationError, DNSTemplateEmptyError, TemplateError, ValueError) as exc:
                    self._log_candidate_skip(rule, source_obj, record_data, exc, phase=PHASE_UPDATE_RECONCILE)
                    continue

            desired_by_rule_id[rule.pk] = all_record_data
        planning_seconds += perf_counter() - planning_started_at
        pending_rename_updates: dict[type, list[Any]] = defaultdict(list)
        apply_started_at = perf_counter()
        summaries: list[dict[str, Any]] = []
        for entry in prepared_entries:
            summaries.append(self._apply_prepared_reconcile_entry(entry, bulk_update_collector=pending_rename_updates))
        apply_seconds += perf_counter() - apply_started_at

        bulk_flush_started_at = perf_counter()
        self._flush_bulk_rename_updates(pending_rename_updates)
        bulk_flush_seconds += perf_counter() - bulk_flush_started_at
        self._record_pipeline_stage_metrics(
            {
                "objects": len(source_objects),
                "tracking_rows": len(tracking_rows),
                "pending_rule_calculations": len(pending_rule_calculations),
                "pending_bulk_updates": sum(len(entries) for entries in pending_rename_updates.values()),
                "stage_seconds": {
                    "fetch": fetch_seconds,
                    "planning": planning_seconds,
                    "apply": apply_seconds,
                    "bulk_flush": bulk_flush_seconds,
                    "total": perf_counter() - total_started_at,
                },
            }
        )
        return summaries

    def _process_objects_pipeline_hybrid(
        self, source_objects: list[Any], created: bool = False
    ) -> list[dict[str, Any]]:
        """Hybrid pipeline: precompute rule applicability and avoid repeated needs-check queries."""
        if not source_objects:
            return []
        if created:
            return [self.process_object(source_obj, created=True) for source_obj in source_objects]

        total_started_at = perf_counter()
        fetch_seconds = 0.0
        planning_seconds = 0.0
        apply_seconds = 0.0
        bulk_flush_seconds = 0.0

        fetch_started_at = perf_counter()
        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [source_obj.pk for source_obj in source_objects]
        tracking_rows = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))
        self._prefetch_tracking_dns_records(tracking_rows)

        tracking_by_object_id: dict[Any, list[DNSRuleRecord]] = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_object_id[tracking_row.object_id].append(tracking_row)
        fetch_seconds += perf_counter() - fetch_started_at

        planning_started_at = perf_counter()
        prepared_entries = []
        pending_rule_calculations: list[dict[str, Any]] = []
        batch_address_ids: set[Any] = set()
        for source_obj in source_objects:
            rules = self._get_applicable_rules(source_obj)
            desired_by_rule_id: dict[Any, list[dict[str, Any]]] = {}
            failed_rule_ids: set[Any] = set()
            needed_rule_ids: set[Any] = set()

            for rule in rules:
                needs_records = self._object_needs_dns_records_for_rule_prefetched(source_obj, rule)
                if not needs_records:
                    continue
                needed_rule_ids.add(rule.pk)
                try:
                    base_context = {"obj": wrap_for_template(source_obj)}
                    rendered_name = self._render_template(rule.name_template, base_context, "name_template")
                    shared_record_data = {"name": normalize_dns_name(rendered_name)}
                    record_variations = self._get_record_data_variations_for_rule(rule, base_context, shared_record_data)
                    requires_ip_context = self._requires_ip_context(rule)
                    if requires_ip_context:
                        for record_data in record_variations:
                            address_id = record_data.get("address_id")
                            if address_id:
                                batch_address_ids.add(address_id)
                    pending_rule_calculations.append(
                        {
                            "source_obj": source_obj,
                            "rule": rule,
                            "base_context": base_context,
                            "record_variations": record_variations,
                            "requires_ip_context": requires_ip_context,
                            "desired_by_rule_id": desired_by_rule_id,
                            "failed_rule_ids": failed_rule_ids,
                        }
                    )
                except (TemplateError, DNSTemplateEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                    self._log_rule_processing_error(
                        rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True
                    )
                    failed_rule_ids.add(rule.pk)
            prepared_entries.append(
                {
                    "source_obj": source_obj,
                    "rules": rules,
                    "needed_rule_ids": needed_rule_ids,
                    "desired_by_rule_id": desired_by_rule_id,
                    "failed_rule_ids": failed_rule_ids,
                    "tracking_rows": tracking_by_object_id.get(source_obj.pk, []),
                }
            )

        preloaded_ip_by_id: dict[Any, Any] = {}
        if batch_address_ids:
            preloaded_ip_by_id = ipam_models.IPAddress.objects.in_bulk(batch_address_ids)

        for pending in pending_rule_calculations:
            rule: DNSRule = pending["rule"]
            source_obj = pending["source_obj"]
            base_context: dict[str, Any] = pending["base_context"]
            record_variations: list[dict[str, Any]] = pending["record_variations"]
            requires_ip_context: bool = pending["requires_ip_context"]
            desired_by_rule_id: dict[Any, list[dict[str, Any]]] = pending["desired_by_rule_id"]
            failed_rule_ids: set[Any] = pending["failed_rule_ids"]

            if rule.pk in failed_rule_ids:
                continue

            all_record_data: list[dict[str, Any]] = []
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
                except (ValidationError, DNSTemplateEmptyError, TemplateError, ValueError) as exc:
                    self._log_candidate_skip(rule, source_obj, record_data, exc, phase=PHASE_UPDATE_RECONCILE)
                    continue

            desired_by_rule_id[rule.pk] = all_record_data
        planning_seconds += perf_counter() - planning_started_at
        pending_rename_updates: dict[type, list[Any]] = defaultdict(list)
        apply_started_at = perf_counter()
        summaries: list[dict[str, Any]] = []
        for entry in prepared_entries:
            summaries.append(self._apply_prepared_reconcile_entry(entry, bulk_update_collector=pending_rename_updates))
        apply_seconds += perf_counter() - apply_started_at

        bulk_flush_started_at = perf_counter()
        self._flush_bulk_rename_updates(pending_rename_updates)
        bulk_flush_seconds += perf_counter() - bulk_flush_started_at
        self._record_pipeline_stage_metrics(
            {
                "objects": len(source_objects),
                "tracking_rows": len(tracking_rows),
                "pending_rule_calculations": len(pending_rule_calculations),
                "pending_bulk_updates": sum(len(entries) for entries in pending_rename_updates.values()),
                "stage_seconds": {
                    "fetch": fetch_seconds,
                    "planning": planning_seconds,
                    "apply": apply_seconds,
                    "bulk_flush": bulk_flush_seconds,
                    "total": perf_counter() - total_started_at,
                },
            }
        )
        return summaries

    def _process_objects_pipeline_rule_driven(
        self, source_objects: list[Any], created: bool = False
    ) -> list[dict[str, Any]]:
        """Prototype rule-driven pipeline: group planning work by rule across objects."""
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
        fetch_result = self._rule_driven_stage_fetch_tracking(source_objects)
        fetch_seconds += perf_counter() - fetch_started_at

        # Stage 2: Build rule-driven work plan
        planning_started_at = perf_counter()
        plan_result = self._rule_driven_stage_plan_work(
            source_objects=source_objects,
            tracking_by_object_id=fetch_result["tracking_by_object_id"],
        )
        # Stage 3: Materialize desired data from work plan
        self._rule_driven_stage_materialize_desired_data(
            rule_work_items=plan_result["rule_work_items"],
            prepared_entry_by_object_id=plan_result["prepared_entry_by_object_id"],
            batch_address_ids=plan_result["batch_address_ids"],
        )
        planning_seconds += perf_counter() - planning_started_at

        # Stage 4: Apply reconciled changes
        apply_started_at = perf_counter()
        apply_result = self._rule_driven_stage_apply_changes(plan_result["prepared_entries"])
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
                "pending_bulk_updates": sum(len(entries) for entries in apply_result["pending_rename_updates"].values()),
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

    def _rule_driven_stage_fetch_tracking(self, source_objects: list[Any]) -> dict[str, Any]:
        """Stage 1: fetch and prefetch tracking rows for the current object batch."""
        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [source_obj.pk for source_obj in source_objects]
        tracking_rows = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))
        self._prefetch_tracking_dns_records(tracking_rows)

        tracking_by_object_id: dict[Any, list[DNSRuleRecord]] = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_object_id[tracking_row.object_id].append(tracking_row)

        return {
            "tracking_rows": tracking_rows,
            "tracking_by_object_id": tracking_by_object_id,
        }

    def _rule_driven_stage_plan_work(
        self,
        source_objects: list[Any],
        tracking_by_object_id: dict[Any, list[DNSRuleRecord]],
    ) -> dict[str, Any]:
        """Stage 2: build per-object prepared entries and per-rule work items."""
        prepared_entries: list[dict[str, Any]] = []
        prepared_entry_by_object_id: dict[Any, dict[str, Any]] = {}
        rule_work_items: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        batch_address_ids: set[Any] = set()

        for source_obj in source_objects:
            rules = self._get_applicable_rules(source_obj)
            desired_by_rule_id: dict[Any, list[dict[str, Any]]] = {}
            failed_rule_ids: set[Any] = set()
            needed_rule_ids: set[Any] = set()

            for rule in rules:
                needs_records = self._object_needs_dns_records_for_rule_prefetched(source_obj, rule)
                if not needs_records:
                    continue
                needed_rule_ids.add(rule.pk)
                try:
                    base_context = {"obj": wrap_for_template(source_obj)}
                    rendered_name = self._render_template(rule.name_template, base_context, "name_template")
                    shared_record_data = {"name": normalize_dns_name(rendered_name)}
                    record_variations = self._get_record_data_variations_for_rule(rule, base_context, shared_record_data)
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
                    self._log_rule_processing_error(
                        rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True
                    )
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

    def _rule_driven_stage_materialize_desired_data(
        self,
        rule_work_items: dict[Any, list[dict[str, Any]]],
        prepared_entry_by_object_id: dict[Any, dict[str, Any]],
        batch_address_ids: set[Any],
    ) -> None:
        """Stage 3: materialize desired record data into prepared entries."""
        preloaded_ip_by_id: dict[Any, Any] = {}
        if batch_address_ids:
            preloaded_ip_by_id = ipam_models.IPAddress.objects.in_bulk(batch_address_ids)

        for work_items in rule_work_items.values():
            for pending in work_items:
                prepared_entry = prepared_entry_by_object_id.get(pending["object_id"])
                if prepared_entry is None:
                    continue

                rule: DNSRule = pending["rule"]
                source_obj = prepared_entry["source_obj"]
                base_context: dict[str, Any] = pending["base_context"]
                record_variations: list[dict[str, Any]] = pending["record_variations"]
                requires_ip_context: bool = pending["requires_ip_context"]
                desired_by_rule_id: dict[Any, list[dict[str, Any]]] = prepared_entry["desired_by_rule_id"]
                failed_rule_ids: set[Any] = prepared_entry["failed_rule_ids"]

                if rule.pk in failed_rule_ids:
                    continue

                all_record_data: list[dict[str, Any]] = []
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
                    except (ValidationError, DNSTemplateEmptyError, TemplateError, ValueError) as exc:
                        self._log_candidate_skip(rule, source_obj, record_data, exc, phase=PHASE_UPDATE_RECONCILE)
                        continue

                desired_by_rule_id[rule.pk] = all_record_data

    def _rule_driven_stage_apply_changes(self, prepared_entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Stage 4: apply prepared reconcile entries and queue rename updates."""
        pending_rename_updates: dict[type, list[Any]] = defaultdict(list)
        summaries: list[dict[str, Any]] = []
        for entry in prepared_entries:
            summaries.append(self._apply_prepared_reconcile_entry(entry, bulk_update_collector=pending_rename_updates))
        return {
            "summaries": summaries,
            "pending_rename_updates": pending_rename_updates,
        }

    def _object_needs_dns_records_for_rule_prefetched(self, source_obj: Any, rule: DNSRule) -> bool:
        """Hybrid fast-path: avoid per-object SQL checks when prefetch cache is present."""
        if rule.record_type not in ("A", "AAAA"):
            return True

        target_ip_version = 4 if rule.record_type == "A" else 6
        prefetched = getattr(source_obj, "_prefetched_objects_cache", {}).get("ip_addresses")
        if prefetched is not None:
            return any(getattr(ip_obj, "ip_version", None) == target_ip_version for ip_obj in prefetched)
        return self._object_needs_dns_records_for_rule(source_obj, rule)

    def _build_record_context_with_preloaded_ips(
        self, base_context: dict[str, Any], record_data: dict[str, Any], preloaded_ip_by_id: dict[Any, Any]
    ) -> dict[str, Any]:
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
            raise ValidationError({"value_template": f"Resolved IP address '{address_id}' was not found."})

        context["ip"] = wrap_for_template(ip_obj)
        return context

    def _prefetch_tracking_dns_records(self, tracking_rows: list[DNSRuleRecord]) -> None:
        """Batch-resolve GenericFK dns_record objects and attach them to tracking rows."""
        if not tracking_rows:
            return

        rows_by_record_content_type: dict[Any, list[DNSRuleRecord]] = defaultdict(list)
        for tracking_row in tracking_rows:
            rows_by_record_content_type[tracking_row.dns_record_content_type_id].append(tracking_row)

        content_types = ContentType.objects.in_bulk(rows_by_record_content_type.keys())
        for record_content_type_id, rows in rows_by_record_content_type.items():
            record_content_type = content_types.get(record_content_type_id)
            if record_content_type is None:
                continue

            record_model = record_content_type.model_class()
            if record_model is None:
                continue

            record_ids = [tracking_row.dns_record_object_id for tracking_row in rows]
            records_by_id = record_model.objects.in_bulk(record_ids)
            for tracking_row in rows:
                tracking_row._prefetched_dns_record = records_by_id.get(tracking_row.dns_record_object_id)

    def _apply_prepared_reconcile_entry(
        self,
        entry: dict[str, Any],
        bulk_update_collector: dict[type, list[Any]] | None = None,
    ) -> dict[str, Any]:
        """Apply prepared desired/tracking data for one source object."""
        source_obj = entry["source_obj"]
        rules: list[DNSRule] = entry["rules"]
        needed_rule_ids: set[Any] = entry.get("needed_rule_ids", set())
        desired_by_rule_id: dict[Any, list[dict[str, Any]]] = entry["desired_by_rule_id"]
        failed_rule_ids: set[Any] = entry["failed_rule_ids"]
        tracking_rows: list[DNSRuleRecord] = entry["tracking_rows"]

        summary = self._initialize_processing_summary()
        existing_count = len(tracking_rows)
        summary["existing_rule_record_count"] = existing_count
        summary["had_existing_rule_records"] = existing_count > 0

        if not rules:
            return summary

        tracking_by_rule_id: dict[Any, list[DNSRuleRecord]] = defaultdict(list)
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
        tracking_by_rule_id: dict[Any, list[DNSRuleRecord]],
        applicable_rule_ids: set[Any],
    ) -> int:
        """Delete tracking/DNS rows for rules no longer applicable."""
        deleted_count = 0
        for rule_id in list(tracking_by_rule_id.keys()):
            if rule_id in applicable_rule_ids:
                continue
            deleted_count += self._cleanup_records_for_rule_prefetched(tracking_by_rule_id, rule_id)
        return deleted_count

    def _cleanup_records_for_rule_prefetched(
        self,
        tracking_by_rule_id: dict[Any, list[DNSRuleRecord]],
        rule_id: Any,
    ) -> int:
        """Delete all tracking/DNS rows for one rule from prefetched group."""
        tracking_rows = tracking_by_rule_id.pop(rule_id, [])
        for tracking_row in tracking_rows:
            self._delete_tracking_and_dns_record(tracking_row)
        return len(tracking_rows)

    def _reconcile_records_for_rule_with_desired(
        self,
        rule: DNSRule,
        source_obj: Any,
        tracking_records: list[DNSRuleRecord],
        desired_record_data: list[dict[str, Any]],
        bulk_update_collector: dict[type, list[Any]] | None = None,
    ) -> dict[str, int]:
        """Reconcile one rule using caller-provided tracking rows and desired rows."""
        existing_records_by_identity = {}
        for tracking_record in tracking_records:
            dns_record = getattr(tracking_record, "_prefetched_dns_record", None)
            if dns_record is None:
                dns_record = tracking_record.dns_record
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
                dns_record = getattr(tracking_record, "_prefetched_dns_record", None)
                if dns_record is None:
                    dns_record = tracking_record.dns_record
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
            created_records = self._create_records_from_data(rule, source_obj, records_to_create_data, phase=PHASE_UPDATE_RECONCILE)

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
        bulk_update_collector: dict[type, list[Any]],
    ) -> None:
        """Execute queued rename updates in bulk."""
        for record_model, update_entries in bulk_update_collector.items():
            if not update_entries:
                continue
            record_model.objects.bulk_update(update_entries, ["name"], batch_size=self.BULK_RENAME_UPDATE_BATCH_SIZE)
