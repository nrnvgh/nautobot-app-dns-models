"""Pipeline orchestration for batched DNS reconciliation."""

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
from nautobot_dns_models.rules.engine.enums import EnginePhase, EngineReason, ExecutionMode
from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER
from nautobot_dns_models.rules.engine.metrics import ObjectProcessingMetrics, PipelineBatchMetrics
from nautobot_dns_models.rules.engine.template_proxies import wrap_for_template
from nautobot_dns_models.rules.engine.types import (
    ApplyChangesResult,
    FetchTrackingDataResult,
    PlanWorkResult,
    PreparedReconcileEntry,
    RuleFailureInfo,
    RulePlanningOutcome,
    RulePlanningStatus,
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

    # Orchestration entrypoint.
    def process_objects_pipeline(self, source_objects):
        """Process one batch of source objects."""
        logger.debug("[process_objects_pipeline] Processing batch of %d objects", len(source_objects))
        if not source_objects:
            return []

        batch_metrics = PipelineBatchMetrics(source_object_count=len(source_objects))
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
            update_flush_result = self._writer.flush_bulk_rename_updates(apply_result.pending_rename_updates)
            self._apply_failed_update_adjustments(
                prepared_entries=plan_result.prepared_entries,
                summaries=apply_result.summaries,
                failed_updates_by_object_id=update_flush_result.failed_updates_by_object_id,
            )

        batch_metrics.finalize_total(total_started_at)
        batch_metrics.apply_pipeline_outputs(
            tracking_row_count=len(fetch_result.tracking_rows),
            pending_rule_work_items=plan_result.pending_rule_work_items,
            pending_rename_updates=apply_result.pending_rename_updates,
            create_flush_result=apply_result.create_flush_result,
            update_flush_result=update_flush_result,
        )
        self._pipeline_metrics.record_batch(batch_metrics)

        return apply_result.summaries

    # Stage 1: Fetch tracking rows.
    def _fetch_tracking_data(self, source_objects):
        """Stage 1: Fetch and prefetch tracking rows for current object batch."""
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

    # Stage 2: Planning and work-item preparation.
    def _plan_work(
        self,
        source_objects,
        tracking_by_object_id,
    ):
        """Stage 2: Build per-object prepared entries and per-rule work items."""
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
            pending_rule_work_items=sum(len(items) for items in rule_work_items.values()),
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
            outcome = self._build_rule_work_item(
                source_obj=source_obj,
                rule=rule,
                batch_address_ids=batch_address_ids,
            )
            if outcome.status == RulePlanningStatus.NOT_NEEDED:
                continue

            if outcome.status == RulePlanningStatus.FAILED:
                prepared_entry.mark_rule_failed(rule.pk, failure=outcome.failure)
                continue

            prepared_entry.mark_rule_needed(rule.pk)
            if outcome.work_item is not None:
                rule_work_items[rule.pk].append(outcome.work_item)

        return prepared_entry

    def _build_rule_work_item(self, *, source_obj, rule, batch_address_ids):
        """Build deferred work for one object/rule pair."""
        if not self._resolver.object_needs_dns_records_for_rule(source_obj, rule):
            return RulePlanningOutcome(status=RulePlanningStatus.NOT_NEEDED)

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

            return RulePlanningOutcome(
                status=RulePlanningStatus.READY,
                work_item=RuleWorkItem(
                    object_id=source_obj.pk,
                    rule=rule,
                    base_context=base_context,
                    record_variations=record_variations,
                    requires_ip_context=requires_ip_context,
                ),
            )
        except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
            self._engine_logger.log_rule_processing_error(
                rule, source_obj, exc, phase=EnginePhase.UPDATE_RECONCILE, cleanup=True
            )
            return RulePlanningOutcome(
                status=RulePlanningStatus.FAILED,
                failure=self._build_rule_failure_info(exc, phase=EnginePhase.UPDATE_RECONCILE),
            )

    def _build_rule_failure_info(self, exc, *, phase):
        """Build structured failure info from one planning/materialization exception."""
        reason_code = EngineReason.RULE_PROCESSING_ERROR
        if isinstance(exc, DNSRuleTemplateRenderedEmptyError):
            if "view_template" in str(exc):
                reason_code = EngineReason.VIEW_TEMPLATE_EMPTY
            else:
                reason_code = EngineReason.CANDIDATE_TEMPLATE_ERROR
        elif isinstance(exc, TemplateError):
            reason_code = EngineReason.CANDIDATE_TEMPLATE_ERROR

        return RuleFailureInfo(
            reason_code=reason_code,
            phase=phase,
            message=str(exc),
        )

    @staticmethod
    def _collect_batch_address_ids(record_variations, batch_address_ids):
        """Collect address IDs used by IP-context record variations."""
        for record_data in record_variations:
            address_id = record_data.get("address_id")
            if address_id:
                batch_address_ids.add(address_id)

    # Stage 3: Materialization.
    def _materialize_desired_data(
        self,
        rule_work_items,
        prepared_entry_by_object_id,
        batch_address_ids,
    ):
        """Stage 3: Materialize desired record data into prepared entries."""
        preloaded_ip_by_id = self._preload_batch_ip_addresses(batch_address_ids)

        for work_items in rule_work_items.values():
            for pending in work_items:
                prepared_entry = prepared_entry_by_object_id.get(pending.object_id)
                if prepared_entry is None:
                    continue

                if prepared_entry.has_failed_rule(pending.rule.pk):
                    continue

                desired_records = self._materialize_work_item_records(
                    pending=pending,
                    source_obj=prepared_entry.source_obj,
                    preloaded_ip_by_id=preloaded_ip_by_id,
                )
                prepared_entry.set_desired_records(pending.rule.pk, desired_records)

    @staticmethod
    def _preload_batch_ip_addresses(batch_address_ids):
        """Preload batch IP objects for record-context expansion."""
        if not batch_address_ids:
            return {}

        return ipam_models.IPAddress.objects.in_bulk(batch_address_ids)

    def _materialize_work_item_records(self, *, pending, source_obj, preloaded_ip_by_id):
        """Materialize one deferred work item into desired record rows."""
        all_record_data = []
        for record_data in pending.record_variations:
            try:
                record_context = self._build_materialization_context(
                    base_context=pending.base_context,
                    record_data=record_data,
                    requires_ip_context=pending.requires_ip_context,
                    preloaded_ip_by_id=preloaded_ip_by_id,
                )
                selected_views = self._materializer.get_dns_views_for_rule(pending.rule, record_context)
                zones = self._materializer.get_zones_for_rule(pending.rule, record_context, selected_views)
                for zone in zones:
                    all_record_data.append({**record_data, "zone": zone})
            except (
                DNSRuleTemplateRenderedEmptyError,
                DNSRuleRenderedValueLookupError,
                TemplateError,
                ValueError,
            ) as exc:
                self._engine_logger.log_candidate_skip(
                    pending.rule, source_obj, record_data, exc, phase=EnginePhase.UPDATE_RECONCILE
                )
                continue

        return all_record_data

    def _build_materialization_context(self, *, base_context, record_data, requires_ip_context, preloaded_ip_by_id):
        """Build per-record materialization context with optional preloaded IP data."""
        if requires_ip_context:
            return self._materializer.build_record_context_with_preloaded_ips(
                base_context, record_data, preloaded_ip_by_id
            )

        return {
            **base_context,
            "record": record_data.copy(),
        }

    # Stage 4: Apply and persistence flushes.
    def _apply_changes(self, prepared_entries):
        """Stage 4: Apply prepared reconcile entries and queue rename updates."""
        pending_rename_updates = defaultdict(list)
        bulk_update_collector = pending_rename_updates if self._context.execution_mode == ExecutionMode.FAST else None
        pending_bulk_deletes = defaultdict(set)
        summaries = []
        with self._batched_create_state.activate():
            for prepared_entry in prepared_entries:
                summaries.append(
                    self._apply_prepared_reconcile_entry(
                        prepared_entry,
                        bulk_update_collector=bulk_update_collector,
                        bulk_delete_collector=pending_bulk_deletes,
                    )
                )

            self._writer.flush_bulk_delete_queue(pending_bulk_deletes)
            create_flush_result = self._writer.flush_batched_create_queue()

        return ApplyChangesResult(
            summaries=summaries,
            pending_rename_updates=pending_rename_updates,
            create_flush_result=create_flush_result,
        )

    def _apply_prepared_reconcile_entry(
        self,
        prepared_entry,
        bulk_update_collector=None,
        bulk_delete_collector=None,
    ):
        """Apply prepared desired/tracking data for one source object."""
        source_obj = prepared_entry.source_obj
        rules = prepared_entry.rules
        needed_rule_ids = prepared_entry.needed_rule_ids
        desired_by_rule_id = prepared_entry.desired_by_rule_id
        failed_rule_ids = prepared_entry.failed_rule_ids
        tracking_rows = prepared_entry.tracking_rows

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

    # Post-apply summary adjustments.
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
