"""DNS Rule Processing Engine for Nautobot DNS Models."""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db import models as django_models
from django.template import engines as django_template_engines
from jinja2 import TemplateError
from nautobot.dcim import models as dcim_models
from nautobot.ipam import models as ipam_models
from nautobot.virtualization import models as virtualization_models

from nautobot_dns_models import models as dns_models
from nautobot_dns_models.exceptions import (
    DNSRecordContentTypeResolutionError,
    DNSRuleRenderedValueLookupError,
    DNSRuleTemplateRenderedEmptyError,
)
from nautobot_dns_models.models import (
    DNSRecord,
    DNSRule,
    DNSRuleRecord,
    DNSZone,
)
from nautobot_dns_models.normalization import normalize_dns_name_if_enabled
from nautobot_dns_models.rules.template_proxies import wrap_for_template

logger = logging.getLogger(__name__)

# Candidate/rule processing reason codes used for warning/error logs.
REASON_VIEW_TEMPLATE_EMPTY = "VIEW_TEMPLATE_EMPTY"
REASON_VIEW_NOT_FOUND = "VIEW_NOT_FOUND"
REASON_ZONE_NOT_FOUND = "ZONE_NOT_FOUND"
REASON_CANDIDATE_TEMPLATE_ERROR = "CANDIDATE_TEMPLATE_ERROR"
REASON_CANDIDATE_ERROR = "CANDIDATE_ERROR"
REASON_RECORD_VALIDATION_ERROR = "RECORD_VALIDATION_ERROR"
REASON_RECORD_INTEGRITY_ERROR = "RECORD_INTEGRITY_ERROR"
REASON_RULE_PROCESSING_ERROR = "RULE_PROCESSING_ERROR"
REASON_INVALID_ADDRESS_UUID = "INVALID_ADDRESS_UUID"
REASON_INTERFACE_PARENT_FALLBACK_FAILED = "INTERFACE_PARENT_FALLBACK_FAILED"

# Phase labels used for log consistency and queryability.
PHASE_CREATE = "create"
PHASE_UPDATE_RECONCILE = "update_reconcile"
PHASE_CANDIDATE_EXPANSION = "candidate_expansion"
PHASE_UNKNOWN = "unknown"


@dataclass
class ObjectProcessingSummary:
    """Per-object result returned by the engine's processing paths."""

    had_existing_rule_records: bool = False
    existing_rule_record_count: int = 0
    changed_record_count: int = 0
    record_ops_create_count: int = 0
    record_ops_delete_count: int = 0
    record_ops_update_count: int = 0


@dataclass
class PipelineStageMetrics:
    """Accumulate elapsed seconds for each pipeline stage."""

    fetch: float = 0.0
    planning: float = 0.0
    apply: float = 0.0
    bulk_flush: float = 0.0
    total: float = 0.0

    def add(self, stage_name, seconds):
        """Add elapsed seconds to one named stage."""
        if not hasattr(self, stage_name):
            raise ValueError(f"Unknown pipeline stage '{stage_name}'.")
        setattr(self, stage_name, getattr(self, stage_name) + seconds)

    def as_dict(self, rounded=False):
        """Return stage seconds as a plain dictionary."""
        data = {
            "fetch": self.fetch,
            "planning": self.planning,
            "apply": self.apply,
            "bulk_flush": self.bulk_flush,
            "total": self.total,
        }
        if not rounded:
            return data
        return {stage_name: round(value, 3) for stage_name, value in data.items()}


@dataclass
class PipelineBatchMetrics:
    """Per-batch counters and stage timing prior to accumulation."""

    objects: int = 0
    tracking_rows: int = 0
    pending_rule_calculations: int = 0
    pending_bulk_updates: int = 0
    stage_metrics: PipelineStageMetrics = field(default_factory=PipelineStageMetrics)

    @contextmanager
    def time_stage(self, stage_name):
        """Context manager that accumulates stage elapsed time."""
        started_at = perf_counter()
        try:
            yield
        finally:
            self.stage_metrics.add(stage_name, perf_counter() - started_at)


@dataclass
class PipelineMetrics:
    """Cumulative pipeline metrics across all processed batches."""

    batches: int = 0
    objects_total: int = 0
    tracking_rows_total: int = 0
    pending_rule_calculations_total: int = 0
    pending_bulk_updates_total: int = 0
    stage_metrics: PipelineStageMetrics = field(default_factory=PipelineStageMetrics)

    def record_batch(self, batch_metrics):
        """Accumulate one batch into running totals."""
        self.batches += 1
        self.objects_total += batch_metrics.objects
        self.tracking_rows_total += batch_metrics.tracking_rows
        self.pending_rule_calculations_total += batch_metrics.pending_rule_calculations
        self.pending_bulk_updates_total += batch_metrics.pending_bulk_updates
        for stage_name, value in batch_metrics.stage_metrics.as_dict().items():
            self.stage_metrics.add(stage_name, value)

    def as_report(self):
        """Serialize cumulative totals and per-batch averages."""
        stage_metrics = self.stage_metrics.as_dict(rounded=True)
        metrics = {
            "batches": self.batches,
            "objects_total": self.objects_total,
            "tracking_rows_total": self.tracking_rows_total,
            "pending_rule_calculations_total": self.pending_rule_calculations_total,
            "pending_bulk_updates_total": self.pending_bulk_updates_total,
            "stage_metrics": stage_metrics,
        }
        batches = metrics["batches"] or 1
        metrics["avg_per_batch"] = {
            "objects": round(metrics["objects_total"] / batches, 3),
            "tracking_rows": round(metrics["tracking_rows_total"] / batches, 3),
            "pending_rule_calculations": round(metrics["pending_rule_calculations_total"] / batches, 3),
            "pending_bulk_updates": round(metrics["pending_bulk_updates_total"] / batches, 3),
            "stage_metrics": {k: round(v / batches, 3) for k, v in stage_metrics.items()},
        }
        return metrics


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
        self._default_view_cache = None
        self._view_lookup_cache = {}
        self._zone_lookup_cache = {}
        self._applicable_rules_cache = {}

        self._compiled_template_cache = {}
        self._jinja_env = django_template_engines["jinja"].env
        self._pending_batched_creates = defaultdict(list)
        self._batched_create_queue_active = False
        self._pipeline_stage_metrics = PipelineMetrics()

    #
    # Public API
    #

    def process_object(self, source_obj, created=False):
        """Process one source object against applicable rules."""
        summary = ObjectProcessingSummary()
        content_type = ContentType.objects.get_for_model(source_obj)
        rules = self.get_applicable_rules(source_obj)

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
            change_result = self._create_dns_records_for_object(source_obj, rules)
        else:
            change_result = self._update_dns_records_for_object(source_obj, rules)

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
            A list of ObjectProcessingSummary objects, one per source object in the batch.
        """
        if not source_objects:
            return []

        batch_metrics = PipelineBatchMetrics(objects=len(source_objects))
        total_started_at = perf_counter()

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
            self._flush_bulk_rename_updates(apply_result["pending_rename_updates"])

        batch_metrics.stage_metrics.total = perf_counter() - total_started_at
        batch_metrics.tracking_rows = len(fetch_result["tracking_rows"])
        batch_metrics.pending_rule_calculations = plan_result["pending_rule_calculations"]
        batch_metrics.pending_bulk_updates = sum(
            len(entries) for entries in apply_result["pending_rename_updates"].values()
        )
        self._pipeline_stage_metrics.record_batch(batch_metrics)

        return apply_result["summaries"]

    def delete_dns_records_for_object(self, source_obj):
        """Delete all DNS records created from a source object."""
        content_type = ContentType.objects.get_for_model(source_obj)
        rule_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.id)

        for rule_record in rule_records:
            self._delete_tracking_and_dns_record(rule_record)

    def get_pipeline_stage_metrics(self):
        """Return cumulative and per-batch stage metrics for current run."""
        return self._pipeline_stage_metrics.as_report()

    #
    # Pipeline internals
    #

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
            rules = self.get_applicable_rules(source_obj)
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
                    shared_record_data = {"name": normalize_dns_name_if_enabled(rendered_name)}
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
                except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
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
                        DNSRuleTemplateRenderedEmptyError,
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
        self._pending_batched_creates.clear()
        self._batched_create_queue_active = True

        try:
            for entry in prepared_entries:
                summaries.append(
                    self._apply_prepared_reconcile_entry(entry, bulk_update_collector=pending_rename_updates)
                )

            if self._batched_create_queue_active:
                self._flush_batched_create_queue()
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

        summary = ObjectProcessingSummary()
        existing_count = len(tracking_rows)
        summary.existing_rule_record_count = existing_count
        summary.had_existing_rule_records = existing_count > 0

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

            reconcile_summary = self._reconcile_records_for_rule(
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

    #
    # Per-object reconciliation
    #

    def _create_dns_records_for_object(self, source_obj, applicable_rules):
        """Create records for one source object."""
        changed_record_count = 0
        for rule in applicable_rules:
            if not self._object_needs_dns_records_for_rule(source_obj, rule):
                continue

            try:
                desired_record_data_list = self._calculate_desired_record_data(rule, source_obj, phase=PHASE_CREATE)
                if not desired_record_data_list:
                    continue

                created_records = self._create_records_from_data(source_obj, rule, desired_record_data_list, phase=PHASE_CREATE)

                changed_record_count += len(created_records)
            except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._log_rule_processing_error(rule, source_obj, exc, phase=PHASE_CREATE, cleanup=False)
                continue

        return {
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "record_ops_create_count": changed_record_count,
            "record_ops_delete_count": 0,
            "record_ops_update_count": 0,
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
            except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._log_rule_processing_error(rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True)
                delete_count += self._cleanup_records_for_rule(rule, source_obj)

        changed_record_count = create_count + delete_count + update_count

        return {
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "record_ops_create_count": create_count,
            "record_ops_delete_count": delete_count,
            "record_ops_update_count": update_count,
        }

    def _reconcile_records_for_rule(
        self,
        rule,
        source_obj,
        tracking_records=None,
        desired_record_data=None,
        bulk_update_collector=None,
    ):
        """Reconcile records for one rule/object pair.

        When tracking_records and desired_record_data are None, fetches them
        from the database (per-object path).  When provided, uses the
        caller-supplied data (pipeline path).
        """
        if tracking_records is None:
            tracking_records = self._get_existing_tracking_records(rule, source_obj)
        if desired_record_data is None:
            desired_record_data = self._calculate_desired_record_data(rule, source_obj, phase=PHASE_UPDATE_RECONCILE)

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

        records_to_delete = existing_identity_keys - desired_identity_keys
        records_to_create = desired_identity_keys - existing_identity_keys
        records_to_check_for_update = existing_identity_keys & desired_identity_keys

        for identity_key in records_to_delete:
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
        if records_to_create:
            records_to_create_data = [desired_records_by_identity[key] for key in records_to_create]
            created_records = self._create_records_from_data(
                source_obj, rule, records_to_create_data, phase=PHASE_UPDATE_RECONCILE
            )

        skipped_create = len(records_to_create) - len(created_records)
        return {
            "create": len(created_records),
            "delete": len(records_to_delete),
            "update": updated_count,
            "skipped": skipped_create + skipped_update,
        }

    #
    # Record creation / update / delete
    #

    def _create_records_from_data(self, source_obj, rule, record_data_list, phase=PHASE_CREATE):
        """Dispatch create work to either batched queueing or immediate persistence."""
        if self._batched_create_queue_active:
            return self._queue_records_for_batched_create(
                rule=rule,
                source_obj=source_obj,
                record_data_list=record_data_list,
            )

        return self._create_records_for_object(
            rule=rule,
            source_obj=source_obj,
            record_data_list=record_data_list,
            phase=phase,
        )

    def _create_records_for_object(self, source_obj, rule, record_data_list, phase=PHASE_CREATE):
        """Singleton create path using per-record inserts (no bulk_create)."""
        if not record_data_list:
            return []

        record_class = self._get_record_class(rule.record_type)
        source_content_type = ContentType.objects.get_for_model(source_obj)
        dns_record_content_type = ContentType.objects.get_for_model(record_class)
        created_records = []

        # Best-effort behavior: one invalid candidate should not block other
        # valid candidates for the same rule/object evaluation.
        for record_data in record_data_list:
            try:
                with transaction.atomic():
                    dns_record = record_class(**record_data)  # pylint: disable=not-callable
                    dns_record.validated_save()

                    DNSRuleRecord.objects.create(
                        rule=rule,
                        content_type=source_content_type,
                        object_id=source_obj.id,
                        dns_record_content_type=dns_record_content_type,
                        dns_record_object_id=dns_record.id,
                    )
                    created_records.append(dns_record)
            except (ValidationError, IntegrityError) as exc:
                self._log_record_create_failure(rule, source_obj, record_data, exc, phase=phase)
                continue

        return created_records

    def _queue_records_for_batched_create(self, rule, source_obj, record_data_list):
        """Queue create rows for one pipeline-level bulk flush."""
        if not record_data_list:
            return []

        record_class = self._get_record_class(rule.record_type)
        source_content_type_id = ContentType.objects.get_for_model(source_obj).pk
        dns_record_content_type_id = ContentType.objects.get_for_model(record_class).pk
        queue_rows = self._pending_batched_creates[record_class]
        for record_data in record_data_list:
            queue_rows.append(
                {
                    "rule_id": rule.id,
                    "content_type_id": source_content_type_id,
                    "object_id": source_obj.id,
                    "dns_record_content_type_id": dns_record_content_type_id,
                    "record_data": record_data,
                }
            )

        # Reconcile summaries only use len(created_records), so lightweight sentinels are sufficient.
        return [None] * len(record_data_list)

    def _flush_batched_create_queue(self):
        """Flush queued create rows with chunked bulk inserts."""
        if not self._pending_batched_creates:
            return

        batch_size = self.BULK_CREATE_BATCHED_PIPELINE_SIZE
        with transaction.atomic():
            for record_class, queued_rows in self._pending_batched_creates.items():
                if not queued_rows:
                    continue
                for offset in range(0, len(queued_rows), batch_size):
                    chunk_rows = queued_rows[offset : offset + batch_size]
                    dns_records = [
                        record_class(**queued_row["record_data"])  # pylint: disable=not-callable
                        for queued_row in chunk_rows
                    ]
                    created_records = record_class.objects.bulk_create(dns_records, batch_size=batch_size)
                    tracking_rows = [
                        DNSRuleRecord(
                            rule_id=queued_row["rule_id"],
                            content_type_id=queued_row["content_type_id"],
                            object_id=queued_row["object_id"],
                            dns_record_content_type_id=queued_row["dns_record_content_type_id"],
                            dns_record_object_id=dns_record.id,
                        )
                        for queued_row, dns_record in zip(chunk_rows, created_records)
                    ]
                    DNSRuleRecord.objects.bulk_create(tracking_rows, batch_size=batch_size)

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

    def _flush_bulk_rename_updates(
        self,
        bulk_update_collector,
    ):
        """Execute queued rename updates in bulk."""
        for record_model, update_entries in bulk_update_collector.items():
            if not update_entries:
                continue
            record_model.objects.bulk_update(update_entries, ["name"], batch_size=self.BULK_RENAME_UPDATE_BATCH_SIZE)

    def _delete_tracking_and_dns_record(self, tracking_record):
        """Delete both the DNS record and its tracking record."""
        # logger.debug(f"Deleting DNS record {tracking_record.dns_record} and tracking record {tracking_record}")

        try:
            #
            # Just delete the DNS record; the associated tracking record is cascade-deleted
            # via the GenericRelation on the DNSRecord model.
            tracking_record.dns_record.delete()
        except Exception as exc:
            logger.error(
                "Failed to delete DNS record '%s' and tracking record '%s': %s (%s)",
                tracking_record.dns_record,
                tracking_record,
                exc,
                type(exc).__name__,
            )
            raise

    #
    # Record cleanup
    #

    def _cleanup_records_for_rule(self, rule, source_obj):
        """Clean up all DNS records for a specific rule+object combination."""
        tracking_records = self._get_existing_tracking_records(rule, source_obj)
        deleted_count = 0

        for tracking_record in tracking_records:
            self._delete_tracking_and_dns_record(tracking_record)
            deleted_count += 1

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

    def _cleanup_orphaned_records(self, source_obj, applicable_rules):
        """Clean up DNS records from rules that are no longer applicable to the source object."""
        content_type = ContentType.objects.get_for_model(source_obj)
        existing_tracking_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.pk)

        orphaned_records = existing_tracking_records.exclude(rule__in=applicable_rules)
        deleted_count = 0
        orphaned_rule_ids = orphaned_records.values_list("rule_id", flat=True).distinct()
        for orphaned_rule in DNSRule.objects.filter(pk__in=orphaned_rule_ids):
            # logger.debug(f"Cleaning up orphaned record from rule {orphaned_rule.name} for {source_obj}")
            deleted_count += self._cleanup_records_for_rule(orphaned_rule, source_obj)

        return deleted_count

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

    #
    # Rule resolution
    #

    def get_applicable_rules(self, source_obj):
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

    def _resolve_applicable_rules_for_scope(
        self,
        content_type,
        object_location,
        object_tenant,
    ):
        """Resolve rules for a specific content-type/location/tenant scope."""
        if object_location is None and object_tenant is None:
            # logger.debug(f"Using global rules for {source_obj} (no location, no tenant)")
            return list(
                DNSRule.objects.filter(
                    content_type=content_type, location__isnull=True, tenant__isnull=True, enabled=True
                )
            )

        base_query = DNSRule.objects.filter(content_type=content_type, enabled=True)

        location_conditions = django_models.Q(location=object_location) | django_models.Q(location__isnull=True)
        tenant_conditions = django_models.Q(tenant=object_tenant) | django_models.Q(tenant__isnull=True)

        all_rules = list(base_query.filter(location_conditions & tenant_conditions))

        rules_by_type = defaultdict(
            lambda: {
                "location_tenant": [],  # Most specific
                "location": [],  # Location-wide
                "tenant": [],  # Tenant-wide
                "global": [],  # Least specific
            }
        )

        for rule in all_rules:
            record_type = rule.record_type

            if rule.location == object_location and rule.tenant == object_tenant:
                rules_by_type[record_type]["location_tenant"].append(rule)
            elif rule.location == object_location and rule.tenant is None:
                rules_by_type[record_type]["location"].append(rule)
            elif rule.location is None and rule.tenant == object_tenant:
                rules_by_type[record_type]["tenant"].append(rule)
            else:  # rule.location is None and rule.tenant is None
                rules_by_type[record_type]["global"].append(rule)

        final_rule_pks = []
        for record_type, rules in rules_by_type.items():
            if rules["location_tenant"]:
                final_rule_pks.extend([r.pk for r in rules["location_tenant"]])
                # logger.debug(f"Using location+tenant rule for {source_obj} record type {record_type}")
            elif rules["location"]:
                final_rule_pks.extend([r.pk for r in rules["location"]])
                # logger.debug(f"Using location rule for {source_obj} record type {record_type}")
            elif rules["tenant"]:
                final_rule_pks.extend([r.pk for r in rules["tenant"]])
                # logger.debug(f"Using tenant rule for {source_obj} record type {record_type}")
            elif rules["global"]:
                final_rule_pks.extend([r.pk for r in rules["global"]])
                # logger.debug(f"Using global rule for {source_obj} record type {record_type}")

        final_rule_pk_set = set(final_rule_pks)

        return [rule for rule in all_rules if rule.pk in final_rule_pk_set]

    def _object_needs_dns_records_for_rule(self, source_obj, rule):
        """Hybrid fast-path: avoid per-object SQL checks when prefetch cache is present."""
        if rule.record_type not in ("A", "AAAA"):
            return True

        target_ip_version = 4 if rule.record_type == "A" else 6

        prefetched = getattr(source_obj, "_prefetched_objects_cache", {}).get("ip_addresses")
        if prefetched is not None:
            return any(ip_obj.ip_version == target_ip_version for ip_obj in prefetched)

        if isinstance(source_obj, (dcim_models.Interface, virtualization_models.VMInterface)):
            return source_obj.ip_addresses.filter(ip_version=target_ip_version).exists()

        if isinstance(source_obj, (dcim_models.Device, virtualization_models.VirtualMachine)):
            return (rule.record_type == "A" and source_obj.primary_ip4 is not None) or (
                rule.record_type == "AAAA" and source_obj.primary_ip6 is not None
            )

        if isinstance(source_obj, ipam_models.Service):
            return source_obj.ip_addresses.filter(ip_version=target_ip_version).exists()

        return False

    #
    # Object attribute extraction
    #

    def _get_object_location(self, source_obj):
        """
        Extract location from source object for location-scoped rule resolution.

        Location extraction logic:
        - Device: device.location (required field in Nautobot)
        - Interface: interface.device.location, with module-backed fallback via interface.parent
        - Service: service.device.location OR service.virtual_machine.location (which is just a proxy for cluster.location)
        - VirtualMachine: vm.cluster.location
        - VMInterface: vminterface.virtual_machine.location (which is just a proxy for cluster.location)
        - InterfaceRedundancyGroup: None (complex multi-location) (future)
        """
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.location

            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.location

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "location",
                self._safe_model_label(source_obj),
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._safe_model_label(source_obj),
                    "source_id": str(source_obj.pk),
                    "source_repr": str(source_obj),
                    "resolution_field": "location",
                    "parent_type": type(parent).__name__,
                },
            )
            return None

        if isinstance(source_obj, virtualization_models.VMInterface):
            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.location

            return None

        if isinstance(source_obj, dcim_models.Device):
            return source_obj.location

        if isinstance(source_obj, virtualization_models.VirtualMachine):
            return source_obj.location

        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.location

            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.location

            return None

        return None

    def _get_object_tenant(self, source_obj):
        """
        Extract tenant from source object for tenant-scoped rule resolution.

        Tenant extraction logic:
        - Device: device.tenant (optional field in Nautobot)
        - Interface: interface.device.tenant, with module-backed fallback via interface.parent
        - Service: service.device.tenant OR service.virtual_machine.tenant (with cluster.tenant fallback)
        - VirtualMachine: vm.tenant (with cluster.tenant fallback)
        - VMInterface: vminterface.virtual_machine.tenant (with cluster.tenant fallback)
        - Other objects: None (no tenant awareness)
        """
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.tenant

            module = source_obj.module
            # NOTE: This currently checks only the directly attached module tenant.
            # NOTE: It does not walk ancestor modules/module-bays to discover tenant.
            if module and module.tenant:
                return module.tenant

            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.tenant

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "tenant",
                self._safe_model_label(source_obj),
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._safe_model_label(source_obj),
                    "source_id": str(source_obj.pk),
                    "source_repr": str(source_obj),
                    "resolution_field": "tenant",
                    "parent_type": type(parent).__name__,
                },
            )
            return None

        if isinstance(source_obj, virtualization_models.VMInterface):
            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.tenant or vm.cluster.tenant

            return None

        if isinstance(source_obj, dcim_models.Device):
            return source_obj.tenant

        if isinstance(source_obj, virtualization_models.VirtualMachine):
            return source_obj.tenant or source_obj.cluster.tenant

        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.tenant

            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.tenant or vm.cluster.tenant

            return None

        return None

    #
    # Template rendering
    #

    def _render_template(self, template_str, context, field_name):
        """Render from cached compiled Jinja templates."""
        if "{{" not in template_str and "{%" not in template_str and "{#" not in template_str:
            result = template_str.strip()
            if not result:
                raise DNSRuleTemplateRenderedEmptyError(field_name, template_str, list(context.keys()))

            return result

        compiled_template = self._compiled_template_cache.get(template_str)
        if compiled_template is None:
            if len(self._compiled_template_cache) >= 1024:
                self._compiled_template_cache.clear()
            compiled_template = self._jinja_env.from_string(template_str)
            self._compiled_template_cache[template_str] = compiled_template

        result = compiled_template.render(context)

        if not result:
            raise DNSRuleTemplateRenderedEmptyError(field_name, template_str, list(context.keys()))

        # This should only happen when DEBUG=True and Django uses jinja2.runtime.DebugUndefined.
        if "{{ no such element:" in result:
            raise DNSRuleTemplateRenderedEmptyError(field_name, f"{template_str} → {result}", list(context.keys()))

        return result

    def _requires_ip_context(self, rule):
        """Production tuning: only resolve ip context when templates reference ip."""
        template_text = " ".join([rule.view_template or "", rule.zone_template or ""])
        return bool(re.search(r"\bip\b", template_text))

    def _calculate_desired_record_data(self, rule, source_obj, phase=PHASE_UNKNOWN):
        """Calculate desired DNS record data for one rule/object pair."""
        base_context = {"obj": wrap_for_template(source_obj)}
        rendered_name = self._render_template(rule.name_template, base_context, "name_template")
        shared_record_data = {"name": normalize_dns_name_if_enabled(rendered_name)}
        requires_ip_context = self._requires_ip_context(rule)

        all_record_data = []
        record_variations = self._get_record_data_variations_for_rule(rule, base_context, shared_record_data)
        for record_data in record_variations:
            try:
                if requires_ip_context:
                    record_context = self._build_record_context(base_context, record_data)
                else:
                    record_context = dict(base_context)
                    record_context["record"] = record_data.copy()
                selected_views = self._get_dns_views_for_rule(rule, record_context)
                zones = self._get_zones_for_rule(rule, record_context, selected_views)
                for zone in zones:
                    all_record_data.append({**record_data, "zone": zone})
            except (
                DNSRuleTemplateRenderedEmptyError,
                DNSRuleRenderedValueLookupError,
                TemplateError,
                ValueError,
            ) as exc:
                self._log_candidate_skip(rule, source_obj, record_data, exc, phase=phase)
                continue

        return all_record_data

    def _get_record_data_variations_for_rule(self, rule, context, base_record_data):
        """Build list of record data dictionaries (1 for single, N for multiple records)."""
        record_type = rule.record_type

        if record_type in ("A", "AAAA"):
            # logger.debug(f"Building A/AAAA record data variations from rule {rule.name}")
            if rule.value_template:
                address_result = self._render_template(rule.value_template, context, "value_template")
                # logger.debug(f"A/AAAA record data variations from rule {rule.name} - address result: {address_result}")

                address_ids = address_result.split()
                record_variations = self._build_record_variations(rule, base_record_data, address_ids)
                return self._filter_record_variations_by_ip_version(rule, context, record_variations)

            raise DNSRuleTemplateRenderedEmptyError("value_template", "missing", [])

        record_data = base_record_data.copy()
        self._add_record_type_fields_single(rule, context, record_data)
        return [record_data]

    def _build_record_variations(self, rule, base_record_data, address_ids):
        """Build list of record data dictionaries for a given list of address IDs."""
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
        """Return the record data for the DNS record type associated with the rule."""

        # This code filters records to only return those IPs which match the record type for the rule.
        # Benchmarks showed it the performance of doing it this was was on par with doing SQL-level filtering
        # in template_proxies.py, but the code for doing it this way was simpler.
        if rule.record_type not in ("A", "AAAA"):
            return record_variations

        if not record_variations:
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
                ipam_models.IPAddress.objects.filter(id__in=candidate_address_ids, ip_version=target_ip_version).values_list(
                    "id", flat=True
                )
            )

        return [record_data for record_data in record_variations if record_data["address_id"] in allowed_ids]

    def _add_record_type_fields_single(self, rule, context, record_data):
        """Add record-type specific fields to the record data."""
        if record_type_method := getattr(self, f"_add_record_type_fields_{rule.record_type}", None):
            record_type_method(rule, context, record_data)  # pylint: disable=not-callable

    #
    # DNS view / zone resolution
    #

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

    #
    # Context building
    #

    def _build_record_context(self, base_context, record_data):
        """Build per-record template context, including selected IP when available."""
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

    #
    # Record key / identity helpers
    #

    def _get_record_class(self, record_type):
        """Get the DNS record model class for a given record type."""
        record_type_name = f"{record_type}Record"
        record_class = getattr(dns_models, record_type_name, None)

        if not record_class:
            raise ValueError(f'Unknown record type "{record_type}"')

        if not issubclass(record_class, DNSRecord):
            raise ValueError(f"Record type '{record_type}' is not a valid DNS record type")

        return record_class

    def _get_record_content_key(self, dns_record):
        """Generate a content-based key for record comparison."""
        record_type = dns_record.__class__.__name__
        base_key = f"{record_type}:{dns_record.name}:{dns_record.zone_id}"

        suffix = "unknown"
        if hasattr(dns_record, "address_id"):  # A/AAAA
            suffix = dns_record.address_id

        return f"{base_key}:{suffix}"

    def _get_record_identity_key(self, dns_record):
        """Generate an identity key that excludes mutable fields such as rendered name."""
        record_type = dns_record.__class__.__name__

        if hasattr(dns_record, "address_id"):  # A/AAAA
            return f"{record_type}:{dns_record.zone_id}:{dns_record.address_id}"

        return self._get_record_content_key(dns_record)

    def _get_record_content_key_from_data(self, record_data, rule_record_type):
        """Generate content key from record data dict."""
        zone_id = record_data["zone"].id
        name = record_data["name"]

        record_type = f"{rule_record_type}Record"
        if rule_record_type in ("A", "AAAA"):
            suffix = record_data["address_id"]
        else:
            raise ValueError(f"Unsupported record type for content key generation: {rule_record_type}")

        return f"{record_type}:{name}:{zone_id}:{suffix}"

    def _get_record_identity_key_from_data(self, record_data, rule_record_type):
        """Generate identity key from record data dict."""
        zone_id = record_data["zone"].id
        record_type = f"{rule_record_type}Record"

        if rule_record_type in ("A", "AAAA"):
            return f"{record_type}:{zone_id}:{record_data['address_id']}"

        return self._get_record_content_key_from_data(record_data, rule_record_type)

    #
    # Tracking record helpers
    #

    def _get_existing_tracking_records(self, rule, source_obj):
        """Get existing tracking records for a rule+object combination."""
        return DNSRuleRecord.objects.filter(
            rule=rule, content_type=ContentType.objects.get_for_model(source_obj), object_id=source_obj.id
        )

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

    #
    # Summary / logging
    #

    @staticmethod
    def _safe_model_label(obj):
        """Return model label if available, else object type name."""
        meta = getattr(obj, "_meta", None)
        return getattr(meta, "label_lower", obj.__class__.__name__)

    @staticmethod
    def _infer_reason_code(exc, default_reason):
        """Infer stable reason code from known exception shapes."""
        if isinstance(exc, DNSRuleRenderedValueLookupError):
            if exc.reason_code:
                return exc.reason_code
            return default_reason

        if isinstance(exc, DNSRuleTemplateRenderedEmptyError):
            message = str(exc)
            if "view_template" in message:
                return REASON_VIEW_TEMPLATE_EMPTY

            return REASON_CANDIDATE_TEMPLATE_ERROR

        if isinstance(exc, TemplateError):
            return REASON_CANDIDATE_TEMPLATE_ERROR

        if isinstance(exc, ValidationError):
            message_dict = getattr(exc, "message_dict", {})
            view_errors = " ".join(message_dict.get("view_template", []))

            if "rendered no DNS view names" in view_errors:
                return REASON_VIEW_TEMPLATE_EMPTY

            if "not found from view_template" in view_errors:
                return REASON_VIEW_NOT_FOUND

            zone_errors = " ".join(message_dict.get("zone_template", []))
            if "does not exist in selected DNS view" in zone_errors:
                return REASON_ZONE_NOT_FOUND

        return default_reason

    def _build_log_extra(
        self,
        rule,
        source_obj,
        reason_code,
        phase,
        exc=None,
        record_data=None,
        cleanup=None,
    ):
        """Build structured logging context for hybrid log output."""
        extra = {
            "event": "dnsrule_engine",
            "reason_code": reason_code,
            "phase": phase,
            "rule_id": str(rule.pk),
            "rule_name": rule.name,
            "record_type": rule.record_type,
            "source_ct": self._safe_model_label(source_obj),
            "source_id": str(source_obj.pk),
            "source_repr": str(source_obj),
        }

        if exc is not None:
            extra["exception_type"] = type(exc).__name__
            extra["error"] = str(exc)

        if cleanup is not None:
            extra["cleanup"] = cleanup

        if record_data is not None:
            extra["candidate_address_id"] = str(record_data.get("address_id", ""))
            extra["candidate_name"] = record_data.get("name")
            zone = record_data.get("zone")
            extra["candidate_zone_id"] = str(zone.id) if zone is not None else ""

        return extra

    def _log_rule_processing_error(self, rule, source_obj, exc, phase, cleanup=False):
        """Emit hybrid warning for top-level rule processing failures."""
        reason_code = self._infer_reason_code(exc, REASON_RULE_PROCESSING_ERROR)
        logger.warning(
            "dnsrule_rule_failed reason=%s rule=%s source=%s:%s cleanup=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            cleanup,
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                cleanup=cleanup,
            ),
        )

    def _log_candidate_skip(self, rule, source_obj, record_data, exc, phase):
        """Emit hybrid warning for per-candidate skip decisions."""
        reason_code = self._infer_reason_code(exc, REASON_CANDIDATE_ERROR)
        logger.warning(
            "dnsrule_candidate_skipped reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    def _log_record_create_failure(self, rule, source_obj, record_data, exc, phase):
        """Emit hybrid warning for record creation failures."""
        reason_code = (
            REASON_RECORD_INTEGRITY_ERROR if isinstance(exc, IntegrityError) else REASON_RECORD_VALIDATION_ERROR
        )
        logger.warning(
            "dnsrule_record_create_failed reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    def _log_record_update_failure(self, rule, source_obj, record_data, exc, phase):
        """Emit hybrid warning for record update failures."""
        reason_code = (
            REASON_RECORD_INTEGRITY_ERROR if isinstance(exc, IntegrityError) else REASON_RECORD_VALIDATION_ERROR
        )
        logger.warning(
            "dnsrule_record_update_failed reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )
