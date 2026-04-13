"""DNS Rule Processing Engine for Nautobot DNS Models."""

from __future__ import annotations

import logging
from collections import defaultdict
from time import perf_counter

from django.contrib.contenttypes.models import ContentType
from django.template import engines as django_template_engines
from jinja2 import TemplateError
from nautobot.ipam import models as ipam_models

from nautobot_dns_models.exceptions import (
    DNSRuleRenderedValueLookupError,
    DNSRuleTemplateRenderedEmptyError,
)
from nautobot_dns_models.models import (
    DNSRuleRecord,
    DNSZone,
)
from nautobot_dns_models.normalization import normalize_dns_name_if_enabled
from nautobot_dns_models.rules.engine.cache import EngineCache
from nautobot_dns_models.rules.engine.constants import PHASE_UPDATE_RECONCILE
from nautobot_dns_models.rules.engine.context import EngineContext
from nautobot_dns_models.rules.engine.logging import EngineLogger
from nautobot_dns_models.rules.engine.materializer import RecordMaterializer
from nautobot_dns_models.rules.engine.metrics import (
    ObjectProcessingMetrics,
    PipelineBatchMetrics,
    PipelineMetrics,
)
from nautobot_dns_models.rules.engine.resolver import RuleResolver
from nautobot_dns_models.rules.engine.template_proxies import wrap_for_template
from nautobot_dns_models.rules.engine.writer import RecordWriter

logger = logging.getLogger(__name__)


class DNSRuleEngine:
    """Primary engine that reconciles DNS records in explicit batch phases."""

    # Tuned against ~65k update benchmarks:
    # - 250: ~2572 changed/sec (avg, best)
    # - 500: ~2459 changed/sec (avg)
    # - 1000: ~2468 changed/sec (avg)
    # Keep this constant in sync with docs/dev/reconcile_greenfield_performance_tally.md.
    BULK_RENAME_UPDATE_BATCH_SIZE = 250
    BULK_CREATE_BATCHED_PIPELINE_SIZE = 1000

    def __init__(self):
        """Initialize DNS rule engine caches and pipeline state."""
        self._cache = EngineCache()
        self._pending_batched_creates = defaultdict(list)
        self._batched_create_queue_active = False
        self._pipeline_metrics = PipelineMetrics()
        #
        # Another way to do this would be to apply an overlay to the base environment which
        # set trim_blocks=True, lstrip_blocks=True, and possibly even undefined=StrictUndefined.
        # This could be useful, but would be different than how the nautobot core sets up its environment.
        # Currently optimizing for consistency rather than maximizing ease of use for DNS rules.
        self._jinja_env = django_template_engines["jinja"].env
        self._context = EngineContext(
            jinja_env=self._jinja_env,
            bulk_rename_update_batch_size=self.BULK_RENAME_UPDATE_BATCH_SIZE,
            bulk_create_batched_pipeline_size=self.BULK_CREATE_BATCHED_PIPELINE_SIZE,
        )

        self._engine_logger = EngineLogger()
        self._resolver = RuleResolver(self, self._cache, self._context)
        self._materializer = RecordMaterializer(self, self._cache, self._context)
        self._writer = RecordWriter(self, self._cache, self._context)

    #
    # Public API
    #

    def process_object(self, source_obj, created=False):
        """Process one source object against applicable rules."""
        summary = ObjectProcessingMetrics()
        content_type = ContentType.objects.get_for_model(source_obj)
        rules = self._resolver.get_applicable_rules(source_obj)

        if not rules:
            logger.debug(
                "No DNS rules found for %s - skipping DNS record processing for %s",
                content_type,
                source_obj,
            )
            return summary

        existing_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.pk)
        existing_count = existing_records.count()
        summary.existing_rule_record_count = existing_count
        summary.had_existing_rule_records = existing_count > 0

        if created or existing_count == 0:
            change_result = self._writer.create_dns_records_for_object(source_obj, rules)
        else:
            change_result = self._writer.update_dns_records_for_object(source_obj, rules)

        summary.changed_record_count = change_result["changed_record_count"]
        summary.record_ops_create_count = change_result["record_ops_create_count"]
        summary.record_ops_delete_count = change_result["record_ops_delete_count"]
        summary.record_ops_update_count = change_result.get("record_ops_update_count", 0)

        return summary

    def process_objects_pipeline(self, source_objects):
        """Process one batch of source objects.

        Args:
            source_objects: A list of source objects to process.

        Returns:
            A list of ObjectProcessingMetrics objects, one per source object in the batch.
        """
        if not source_objects:
            return []

        batch_metrics = PipelineBatchMetrics(objects=len(source_objects))
        total_started_at = perf_counter()
        logger.info(f"[process_objects_pipeline] Starting batch of {len(source_objects)} objects")
        # Stage 1: Fetch tracking rows
        with batch_metrics.time_stage("fetch"):
            fetch_result = self._fetch_tracking_data(source_objects)

        # Stage 2: Build work plan
        with batch_metrics.time_stage("planning"):
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

        # Stage 4: Apply reconciled changes
        with batch_metrics.time_stage("apply"):
            apply_result = self._apply_changes(plan_result["prepared_entries"])

        # Stage 5: Flush queued rename updates
        with batch_metrics.time_stage("bulk_flush"):
            self._writer.flush_bulk_rename_updates(apply_result["pending_rename_updates"])

        batch_metrics.stage_metrics.total = perf_counter() - total_started_at
        batch_metrics.tracking_rows = len(fetch_result["tracking_rows"])
        batch_metrics.pending_rule_calculations = plan_result["pending_rule_calculations"]
        batch_metrics.pending_bulk_updates = sum(
            len(entries) for entries in apply_result["pending_rename_updates"].values()
        )
        self._pipeline_metrics.record_batch(batch_metrics)

        return apply_result["summaries"]

    def delete_dns_records_for_object(self, source_obj):
        """Delete all DNS records created from a source object."""
        content_type = ContentType.objects.get_for_model(source_obj)
        rule_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.id)

        for rule_record in rule_records:
            self._writer.delete_tracking_and_dns_record(rule_record)

    def get_pipeline_metrics(self):
        """Return cumulative and per-batch stage metrics for current run."""
        return self._pipeline_metrics.as_report()

    #
    # Pipeline internals
    #

    def _fetch_tracking_data(self, source_objects):
        """Stage 1: fetch and prefetch tracking rows for the current object batch."""
        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [source_obj.pk for source_obj in source_objects]
        tracking_rows = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))
        self._writer.prefetch_tracking_dns_records(tracking_rows)

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
            rules = self._resolver.get_applicable_rules(source_obj)
            desired_by_rule_id = {}
            failed_rule_ids = set()
            needed_rule_ids = set()

            for rule in rules:
                needs_records = self._resolver.object_needs_dns_records_for_rule(source_obj, rule)
                if not needs_records:
                    continue

                needed_rule_ids.add(rule.pk)
                try:
                    base_context = {"obj": wrap_for_template(source_obj)}
                    rendered_name = self._materializer.render_template(
                        rule.name_template, base_context, "name_template"
                    )
                    shared_record_data = {"name": normalize_dns_name_if_enabled(rendered_name)}
                    record_variations = self._materializer.get_record_data_variations_for_rule(
                        rule, base_context, shared_record_data
                    )
                    requires_ip_context = self._materializer._requires_ip_context(rule)
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
                except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                    self._engine_logger.log_rule_processing_error(
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
        summaries = []
        self._pending_batched_creates.clear()
        self._batched_create_queue_active = True

        try:
            for entry in prepared_entries:
                summaries.append(
                    self._apply_prepared_reconcile_entry(entry, bulk_update_collector=pending_rename_updates)
                )

            if self._batched_create_queue_active:
                self._writer.flush_batched_create_queue()
        finally:
            self._batched_create_queue_active = False
            self._pending_batched_creates.clear()

        return {
            "summaries": summaries,
            "pending_rename_updates": pending_rename_updates,
        }

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
        delete_count = self._writer.cleanup_orphaned_records_prefetched(tracking_by_rule_id, applicable_rule_ids)
        create_count = 0
        update_count = 0

        for rule in rules:
            if needed_rule_ids and rule.pk not in needed_rule_ids:
                delete_count += self._writer.cleanup_records_for_rule_prefetched(tracking_by_rule_id, rule.pk)
                continue

            if rule.pk in failed_rule_ids:
                delete_count += self._writer.cleanup_records_for_rule_prefetched(tracking_by_rule_id, rule.pk)
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
            update_count += reconcile_summary.get("update", 0)

        summary.changed_record_count = create_count + delete_count + update_count
        summary.record_ops_create_count = create_count
        summary.record_ops_delete_count = delete_count
        summary.record_ops_update_count = update_count

        return summary

    def get_applicable_rules(self, source_obj):
        """Return applicable DNS rules for a source object."""
        return self._resolver.get_applicable_rules(source_obj)
