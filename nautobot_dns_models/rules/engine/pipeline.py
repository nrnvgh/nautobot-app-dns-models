"""Pipeline orchestration for batched DNS reconciliation."""

from __future__ import annotations

import logging
from collections import defaultdict
from time import perf_counter

from django.contrib.contenttypes.models import ContentType
from jinja2 import TemplateError
from nautobot.ipam import models as ipam_models

from nautobot_dns_models.exceptions import (
    DNSRuleRenderedValueLookupError,
    DNSRuleTemplateRenderedEmptyError,
)
from nautobot_dns_models.models import DNSRuleRecord, DNSZone
from nautobot_dns_models.normalization import normalize_dns_name_if_enabled
from nautobot_dns_models.rules.engine.constants import PHASE_UPDATE_RECONCILE
from nautobot_dns_models.rules.engine.execution_mode import ExecutionMode
from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER
from nautobot_dns_models.rules.engine.metrics import ObjectProcessingMetrics, PipelineBatchMetrics
from nautobot_dns_models.rules.engine.template_proxies import wrap_for_template
from nautobot_dns_models.rules.engine.types import (
    ApplyChangesResult,
    FetchTrackingDataResult,
    PlanWorkResult,
    PreparedReconcileEntry,
    RuleWorkItem,
)

logger = logging.getLogger(__name__)


class EnginePipeline:
    """Run fetch/plan/materialize/apply stages for object batches."""

    def __init__(
        self,
        *,
        writer,
        resolver,
        materializer,
        context,
        pipeline_metrics,
        batched_create_state,
    ):
        """Store collaborators and mutable batch execution state.

        Args:
            writer: Persistence/reconcile collaborator for apply stage operations.
            resolver: Rule resolver collaborator for scope and applicability.
            materializer: Record materializer used for desired data generation.
            context: Engine runtime context (including execution mode).
            pipeline_metrics: Metrics collector for per-batch timing and counts.
            batched_create_state: Shared mutable state for batched-create queueing.
        """
        self._writer = writer
        self._resolver = resolver
        self._materializer = materializer
        self._context = context
        self._engine_logger = DEFAULT_ENGINE_LOGGER
        self._pipeline_metrics = pipeline_metrics
        self._batched_create_state = batched_create_state

    def process_objects_pipeline(self, source_objects):
        """Process one batch of source objects."""
        logger.debug("[process_objects_pipeline] Processing batch of %d objects", len(source_objects))
        if not source_objects:
            return []

        batch_metrics = PipelineBatchMetrics(objects=len(source_objects))
        total_started_at = perf_counter()
        logger.info("[process_objects_pipeline] Starting batch of %d objects", len(source_objects))

        with batch_metrics.time_stage("fetch"):
            fetch_result = self._fetch_tracking_data(source_objects)

        with batch_metrics.time_stage("planning"):
            logger.debug("[process_objects_pipeline] Planning work for %d objects", len(source_objects))
            plan_result = self._plan_work(
                source_objects=source_objects,
                tracking_by_object_id=fetch_result.tracking_by_object_id,
            )
            logger.debug("[process_objects_pipeline] Materializing desired data for %d objects", len(source_objects))
            self._materialize_desired_data(
                rule_work_items=plan_result.rule_work_items,
                prepared_entry_by_object_id=plan_result.prepared_entry_by_object_id,
                batch_address_ids=plan_result.batch_address_ids,
            )

        with batch_metrics.time_stage("apply"):
            logger.debug("[process_objects_pipeline] Applying changes for %d objects", len(source_objects))
            apply_result = self._apply_changes(plan_result.prepared_entries)
            self._apply_successful_create_adjustments(
                prepared_entries=plan_result.prepared_entries,
                summaries=apply_result.summaries,
                successful_creates_by_object_id=apply_result.create_flush_result.successful_creates_by_object_id,
            )

        with batch_metrics.time_stage("bulk_flush"):
            logger.debug("[process_objects_pipeline] Flushing bulk rename updates for %d objects", len(source_objects))
            flush_result = self._writer.flush_bulk_rename_updates(apply_result.pending_rename_updates)
            self._apply_failed_update_adjustments(
                prepared_entries=plan_result.prepared_entries,
                summaries=apply_result.summaries,
                failed_updates_by_object_id=flush_result.failed_updates_by_object_id,
            )

        batch_metrics.stage_metrics.total = perf_counter() - total_started_at
        batch_metrics.tracking_rows = len(fetch_result.tracking_rows)
        batch_metrics.pending_rule_calculations = plan_result.pending_rule_calculations
        batch_metrics.pending_bulk_updates = sum(
            len(entries) for entries in apply_result.pending_rename_updates.values()
        )
        batch_metrics.fallback_chunk_attempt_count = flush_result.fallback_chunk_attempt_count
        batch_metrics.fallback_singleton_attempt_count = flush_result.fallback_singleton_attempt_count
        batch_metrics.fallback_singleton_failure_count = flush_result.fallback_singleton_failure_count
        batch_metrics.update_failure_recorded_count = flush_result.update_failure_recorded_count
        self._pipeline_metrics.record_batch(batch_metrics)

        return apply_result.summaries

    @staticmethod
    def _apply_failed_update_adjustments(*, prepared_entries, summaries, failed_updates_by_object_id):
        """Adjust per-object summary counters for fallback-captured update failures."""
        if not failed_updates_by_object_id:
            return

        summary_by_object_id = {
            prepared_entry.source_obj.pk: summary for prepared_entry, summary in zip(prepared_entries, summaries)
        }
        for object_id, failed_count in failed_updates_by_object_id.items():
            summary = summary_by_object_id.get(object_id)
            if summary is None:
                continue

            adjusted_failures = min(failed_count, summary.dns_record_update_count)
            summary.dns_record_update_count -= adjusted_failures
            summary.changed_record_count -= adjusted_failures

    @staticmethod
    def _apply_successful_create_adjustments(*, prepared_entries, summaries, successful_creates_by_object_id):
        """Add per-object create counters from finalized batched-create flush outcomes."""
        if not successful_creates_by_object_id:
            return

        summary_by_object_id = {
            prepared_entry.source_obj.pk: summary for prepared_entry, summary in zip(prepared_entries, summaries)
        }
        for object_id, successful_count in successful_creates_by_object_id.items():
            summary = summary_by_object_id.get(object_id)
            if summary is None:
                continue

            summary.dns_record_create_count += successful_count
            summary.changed_record_count += successful_count

    def _fetch_tracking_data(self, source_objects):
        """Stage 1: fetch and prefetch tracking rows for current object batch."""
        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [source_obj.pk for source_obj in source_objects]
        tracking_rows = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))
        self._writer.prefetch_tracking_dns_records(tracking_rows)

        tracking_by_object_id = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_object_id[tracking_row.object_id].append(tracking_row)

        return FetchTrackingDataResult(
            tracking_rows=tracking_rows,
            tracking_by_object_id=tracking_by_object_id,
        )

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
            prepared_entry = self._build_prepared_entry_for_object(
                source_obj=source_obj,
                tracking_rows=tracking_by_object_id.get(source_obj.pk, []),
                rule_work_items=rule_work_items,
                batch_address_ids=batch_address_ids,
            )
            prepared_entries.append(prepared_entry)
            prepared_entry_by_object_id[source_obj.pk] = prepared_entry

        return PlanWorkResult(
            prepared_entries=prepared_entries,
            prepared_entry_by_object_id=prepared_entry_by_object_id,
            rule_work_items=rule_work_items,
            batch_address_ids=batch_address_ids,
            pending_rule_calculations=sum(len(items) for items in rule_work_items.values()),
        )

    def _build_prepared_entry_for_object(
        self,
        *,
        source_obj,
        tracking_rows,
        rule_work_items,
        batch_address_ids,
    ):
        """Build one prepared reconcile entry and enqueue deferred rule work items."""
        rules = self._resolver.get_applicable_rules(source_obj)
        prepared_entry = PreparedReconcileEntry(
            source_obj=source_obj,
            rules=rules,
            tracking_rows=tracking_rows,
        )

        for rule in rules:
            needs_records, failed, work_item = self._build_rule_work_item(
                source_obj=source_obj,
                rule=rule,
                batch_address_ids=batch_address_ids,
            )
            if not needs_records:
                continue

            prepared_entry.needed_rule_ids.add(rule.pk)
            if failed:
                prepared_entry.failed_rule_ids.add(rule.pk)
                continue

            if work_item is not None:
                rule_work_items[rule.pk].append(work_item)

        return prepared_entry

    def _build_rule_work_item(self, *, source_obj, rule, batch_address_ids):
        """Build deferred work for one object/rule pair."""
        if not self._resolver.object_needs_dns_records_for_rule(source_obj, rule):
            return False, False, None

        try:
            base_context = {"obj": wrap_for_template(source_obj)}
            rendered_name = self._materializer.render_template(rule.name_template, base_context, "name_template")
            shared_record_data = {"name": normalize_dns_name_if_enabled(rendered_name)}
            record_variations = self._materializer.get_record_data_variations_for_rule(
                rule, base_context, shared_record_data
            )
            requires_ip_context = self._materializer.requires_ip_context(rule)
            if requires_ip_context:
                self._collect_batch_address_ids(record_variations, batch_address_ids)

            return (
                True,
                False,
                RuleWorkItem(
                    object_id=source_obj.pk,
                    rule=rule,
                    base_context=base_context,
                    record_variations=record_variations,
                    requires_ip_context=requires_ip_context,
                ),
            )
        except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
            self._engine_logger.log_rule_processing_error(
                rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True
            )
            return True, True, None

    @staticmethod
    def _collect_batch_address_ids(record_variations, batch_address_ids):
        """Collect address IDs used by IP-context record variations."""
        for record_data in record_variations:
            address_id = record_data.get("address_id")
            if address_id:
                batch_address_ids.add(address_id)

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
                prepared_entry = prepared_entry_by_object_id.get(pending.object_id)
                if prepared_entry is None:
                    continue

                rule = pending.rule
                source_obj = prepared_entry.source_obj
                base_context = pending.base_context
                record_variations = pending.record_variations
                requires_ip_context = pending.requires_ip_context
                desired_by_rule_id = prepared_entry.desired_by_rule_id
                failed_rule_ids = prepared_entry.failed_rule_ids

                if rule.pk in failed_rule_ids:
                    continue

                all_record_data = []
                for record_data in record_variations:
                    try:
                        if requires_ip_context:
                            record_context = self._materializer.build_record_context_with_preloaded_ips(
                                base_context, record_data, preloaded_ip_by_id
                            )
                        else:
                            record_context = dict(base_context)
                            record_context["record"] = record_data.copy()

                        selected_views = self._materializer.get_dns_views_for_rule(rule, record_context)
                        zones = self._materializer.get_zones_for_rule(rule, record_context, selected_views)
                        for zone in zones:
                            all_record_data.append({**record_data, "zone": zone})
                    except (
                        DNSRuleTemplateRenderedEmptyError,
                        DNSRuleRenderedValueLookupError,
                        TemplateError,
                        ValueError,
                    ) as exc:
                        self._engine_logger.log_candidate_skip(
                            rule, source_obj, record_data, exc, phase=PHASE_UPDATE_RECONCILE
                        )
                        continue

                desired_by_rule_id[rule.pk] = all_record_data

    def _apply_changes(self, prepared_entries):
        """Stage 4: apply prepared reconcile entries and queue rename updates."""
        pending_rename_updates = defaultdict(list)
        bulk_update_collector = pending_rename_updates if self._context.execution_mode == ExecutionMode.FAST else None
        pending_bulk_deletes = defaultdict(set)
        summaries = []
        create_flush_result = None
        self._batched_create_state.pending_by_record_class.clear()
        self._batched_create_state.active = True

        try:
            for entry in prepared_entries:
                summaries.append(
                    self._apply_prepared_reconcile_entry(
                        entry,
                        bulk_update_collector=bulk_update_collector,
                        bulk_delete_collector=pending_bulk_deletes,
                    )
                )

            self._writer.flush_bulk_delete_queue(pending_bulk_deletes)
            if self._batched_create_state.active:
                create_flush_result = self._writer.flush_batched_create_queue()
        finally:
            self._batched_create_state.active = False
            self._batched_create_state.pending_by_record_class.clear()

        return ApplyChangesResult(
            summaries=summaries,
            pending_rename_updates=pending_rename_updates,
            create_flush_result=create_flush_result,
        )

    def _apply_prepared_reconcile_entry(
        self,
        entry,
        bulk_update_collector=None,
        bulk_delete_collector=None,
    ):
        """Apply prepared desired/tracking data for one source object."""
        source_obj = entry.source_obj
        rules = entry.rules
        needed_rule_ids = entry.needed_rule_ids
        desired_by_rule_id = entry.desired_by_rule_id
        failed_rule_ids = entry.failed_rule_ids
        tracking_rows = entry.tracking_rows

        summary = ObjectProcessingMetrics()
        existing_count = len(tracking_rows)
        summary.existing_rule_record_count = existing_count
        summary.had_existing_rule_records = existing_count > 0

        if not rules:
            return summary

        tracking_by_rule_id = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_rule_id[tracking_row.rule_id].append(tracking_row)

        applicable_rule_ids = {rule.pk for rule in rules}
        delete_count = self._writer.cleanup_orphaned_records_prefetched(
            tracking_by_rule_id, applicable_rule_ids, bulk_delete_collector=bulk_delete_collector
        )
        create_count = 0
        update_count = 0
        unchanged_count = 0

        for rule in rules:
            if needed_rule_ids and rule.pk not in needed_rule_ids:
                delete_count += self._writer.cleanup_records_for_rule_prefetched(
                    tracking_by_rule_id, rule.pk, bulk_delete_collector=bulk_delete_collector
                )
                continue

            if rule.pk in failed_rule_ids:
                delete_count += self._writer.cleanup_records_for_rule_prefetched(
                    tracking_by_rule_id, rule.pk, bulk_delete_collector=bulk_delete_collector
                )
                continue

            reconcile_summary = self._writer.reconcile_records_for_rule(
                rule=rule,
                source_obj=source_obj,
                tracking_records=tracking_by_rule_id.get(rule.pk, []),
                desired_record_data=desired_by_rule_id.get(rule.pk, []),
                bulk_update_collector=bulk_update_collector,
            )
            create_count += reconcile_summary["create"]
            delete_count += reconcile_summary["delete"]
            update_count += reconcile_summary["update"]
            unchanged_count += reconcile_summary["unchanged"]

        summary.changed_record_count = create_count + delete_count + update_count
        summary.dns_record_create_count = create_count
        summary.dns_record_delete_count = delete_count
        summary.dns_record_update_count = update_count
        summary.dns_record_unchanged_count = unchanged_count

        return summary
