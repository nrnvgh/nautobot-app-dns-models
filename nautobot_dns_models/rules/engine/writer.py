"""Record reconciliation and persistence collaborator."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from functools import reduce

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from jinja2 import TemplateError

from nautobot_dns_models.exceptions import DNSRecordContentTypeResolutionError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.models import DNSRule, DNSRuleFailureState, DNSRuleRecord, DNSZone
from nautobot_dns_models.record_type_mapping import get_dns_record_model_class
from nautobot_dns_models.rules.engine.constants import PHASE_CREATE, PHASE_UPDATE_RECONCILE
from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER
from nautobot_dns_models.rules.engine.reconcile import ReconcilePlanner
from nautobot_dns_models.rules.engine.strategies import UpdateResult

logger = logging.getLogger(__name__)


@dataclass
class BulkRenameFlushResult:
    """Aggregate counters and failure impacts from fast bulk-rename flush."""

    fallback_chunk_attempt_count: int = 0
    fallback_singleton_attempt_count: int = 0
    fallback_singleton_failure_count: int = 0
    update_failure_recorded_count: int = 0
    failed_updates_by_object_id: dict = field(default_factory=dict)


@dataclass
class BulkCreateFlushResult:
    """Aggregate per-object create outcomes from batched-create flush."""

    successful_creates_by_object_id: dict = field(default_factory=dict)
    failed_creates_by_object_id: dict = field(default_factory=dict)


class RecordWriter:
    """Create, reconcile, and cleanup DNS records."""

    def __init__(
        self,
        context,
        *,
        resolver,
        materializer,
        batched_create_state,
        delete_executor,
        update_executor,
    ):
        """Store collaborator references and shared runtime context.

        Args:
            context: Engine runtime context containing execution settings.
            resolver: Rule resolver collaborator used for applicability checks.
            materializer: Desired-record materialization collaborator.
            batched_create_state: Shared mutable state for batched-create queueing.
            delete_executor: Delete strategy for standard/fast execution modes.
            update_executor: Update strategy for standard/fast execution modes.
        """
        self._context = context
        self._resolver = resolver
        self._materializer = materializer
        self._batched_create_state = batched_create_state
        self._delete_executor = delete_executor
        self._update_executor = update_executor
        self._engine_logger = DEFAULT_ENGINE_LOGGER
        self._reconcile_planner = ReconcilePlanner()
        self._fast_fallback_singleton_threshold = 16

    def create_dns_records_for_object(self, source_obj, applicable_rules):
        """Create records for one source object."""
        changed_record_count = 0
        for rule in applicable_rules:
            if not self._resolver.object_needs_dns_records_for_rule(source_obj, rule):
                continue

            try:
                desired_record_data_list = self._materializer.calculate_desired_record_data(
                    rule, source_obj, phase=PHASE_CREATE
                )
                if not desired_record_data_list:
                    continue

                created_records = self._create_records_from_data(
                    source_obj, rule, desired_record_data_list, phase=PHASE_CREATE
                )
                changed_record_count += len(created_records)
            except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._engine_logger.log_rule_processing_error(rule, source_obj, exc, phase=PHASE_CREATE, cleanup=False)
                continue

        return {
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "dns_record_create_count": changed_record_count,
            "dns_record_delete_count": 0,
            "dns_record_update_count": 0,
            "dns_record_unchanged_count": 0,
        }

    def update_dns_records_for_object(self, source_obj, applicable_rules):
        """Update/reconcile records for one source object."""
        delete_count = self.cleanup_orphaned_records(source_obj, applicable_rules)
        create_count = 0
        update_count = 0
        unchanged_count = 0

        for rule in applicable_rules:
            if not self._resolver.object_needs_dns_records_for_rule(source_obj, rule):
                delete_count += self._cleanup_records_for_rule(rule, source_obj)
                continue

            try:
                reconcile_summary = self.reconcile_records_for_rule(rule, source_obj)
                create_count += reconcile_summary["create"]
                delete_count += reconcile_summary["delete"]
                update_count += reconcile_summary["update"]
                unchanged_count += reconcile_summary["unchanged"]
            except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._engine_logger.log_rule_processing_error(
                    rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True
                )
                delete_count += self._cleanup_records_for_rule(rule, source_obj)

        changed_record_count = create_count + delete_count + update_count

        return {
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "dns_record_create_count": create_count,
            "dns_record_delete_count": delete_count,
            "dns_record_update_count": update_count,
            "dns_record_unchanged_count": unchanged_count,
        }

    def reconcile_records_for_rule(
        self,
        rule,
        source_obj,
        tracking_records=None,
        desired_record_data=None,
        bulk_update_collector=None,
    ):
        """Reconcile records for one rule/object pair."""
        plan = self._build_reconcile_plan(
            rule=rule,
            source_obj=source_obj,
            tracking_records=tracking_records,
            desired_record_data=desired_record_data,
        )

        return self._apply_reconcile_plan(
            plan=plan,
            rule=rule,
            source_obj=source_obj,
            bulk_update_collector=bulk_update_collector,
        )

    def _build_reconcile_plan(self, *, rule, source_obj, tracking_records=None, desired_record_data=None):
        """Build reconcile plan from existing tracking rows and desired record data."""
        if tracking_records is None:
            tracking_records = self._get_existing_tracking_records(rule, source_obj)

        if desired_record_data is None:
            desired_record_data = self._materializer.calculate_desired_record_data(
                rule, source_obj, phase=PHASE_UPDATE_RECONCILE
            )

        existing_records_by_identity = {}
        for tracking_record in tracking_records:
            dns_record = self._resolve_prefetched_dns_record(tracking_record)
            if dns_record is None:
                continue

            identity_key = self._get_record_identity_key(dns_record)
            existing_records_by_identity[identity_key] = tracking_record

        desired_records_by_identity = {}
        for record_data in desired_record_data:
            identity_key = self._get_record_identity_key_from_data(record_data, rule.record_type)
            desired_records_by_identity[identity_key] = record_data

        plan = self._reconcile_planner.build_plan(
            existing_records_by_identity=existing_records_by_identity,
            desired_records_by_identity=desired_records_by_identity,
        )

        return plan

    def _apply_reconcile_plan(self, *, plan, rule, source_obj, bulk_update_collector=None):
        """Apply reconcile plan and return operation counts."""
        for identity_key in plan.records_to_delete:
            self.delete_tracking_and_dns_record(plan.existing_records_by_identity[identity_key])

        updated_count = 0
        unchanged_count = 0
        skipped_update = 0
        for identity_key in plan.records_to_check_for_update:
            tracking_record = plan.existing_records_by_identity[identity_key]
            desired_record = plan.desired_records_by_identity[identity_key]
            update_result = self._update_executor.apply(
                writer=self,
                rule=rule,
                source_obj=source_obj,
                tracking_record=tracking_record,
                desired_record_data=desired_record,
                phase=PHASE_UPDATE_RECONCILE,
                bulk_update_collector=bulk_update_collector,
            )
            if update_result == UpdateResult.UPDATED:
                updated_count += 1
            elif update_result == UpdateResult.UNCHANGED:
                unchanged_count += 1
            elif update_result == UpdateResult.FAILED:
                skipped_update += 1

        created_records = []
        if plan.records_to_create:
            records_to_create_data = [plan.desired_records_by_identity[key] for key in plan.records_to_create]
            created_records = self._create_records_from_data(
                source_obj, rule, records_to_create_data, phase=PHASE_UPDATE_RECONCILE
            )

        skipped_create = len(plan.records_to_create) - len(created_records)

        return {
            "create": len(created_records),
            "delete": len(plan.records_to_delete),
            "update": updated_count,
            "unchanged": unchanged_count,
            "skipped": skipped_create + skipped_update,
        }

    def prefetch_tracking_dns_records(self, tracking_rows):
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
                tracking_row._prefetched_dns_record = records_by_id.get(tracking_row.dns_record_object_id)  # pylint: disable=protected-access

    def _create_records_from_data(self, source_obj, rule, record_data_list, phase=PHASE_CREATE):
        if self._batched_create_state.active:
            return self._queue_records_for_batched_create(
                rule=rule, source_obj=source_obj, record_data_list=record_data_list, phase=phase
            )

        return self._create_records_for_object(
            rule=rule, source_obj=source_obj, record_data_list=record_data_list, phase=phase
        )

    def _create_records_for_object(self, source_obj, rule, record_data_list, phase=PHASE_CREATE):
        if not record_data_list:
            return []

        record_class = self._get_record_class(rule.record_type)
        source_content_type = ContentType.objects.get_for_model(source_obj)
        dns_record_content_type = ContentType.objects.get_for_model(record_class)

        created_records = []
        for record_data in record_data_list:
            create_entry = self._build_create_failure_state_entry(
                rule=rule,
                source_obj=source_obj,
                source_content_type_id=source_content_type.id,
                record_data=record_data,
                phase=phase,
            )
            try:
                # This nested atomic creates a savepoint per record attempt. It lets us roll back only
                # this record+tracking write on exceptions and continue processing without poisoning the
                # outer transaction.
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
                self._delete_failure_state_for_candidate(create_entry)
            except (ValidationError, IntegrityError) as exc:
                self._capture_entry_error_details(create_entry, exc)
                self._engine_logger.log_record_create_failure(rule, source_obj, record_data, exc, phase=phase)
                self._upsert_failure_state_for_candidate(create_entry)
                continue

        return created_records

    def _queue_records_for_batched_create(self, rule, source_obj, record_data_list, phase):
        """Queue candidate creates for deferred batched flush.

        This method stages create intents in `BatchedCreateState` for later
        execution by `flush_batched_create_queue()`. It does not write DNS
        records or tracking rows immediately, nor does it increment create
        counters at queue time.

        Per-object create metrics are finalized during flush, where each queued row
        is classified as successful or failed after bulk/singleton fallback logic.

        Args:
            rule: DNS rule whose desired candidates are being queued.
            source_obj: Source object associated with these create candidates.
            record_data_list: Desired DNS record payloads to enqueue.
            phase: Processing phase label used for logging and failure-state entries.
        """
        if not record_data_list:
            return []

        record_class = self._get_record_class(rule.record_type)
        source_content_type_id = ContentType.objects.get_for_model(source_obj).pk
        dns_record_content_type_id = ContentType.objects.get_for_model(record_class).pk
        queue_rows = self._batched_create_state.pending_by_record_class[record_class]
        for record_data in record_data_list:
            queue_row = self._build_create_failure_state_entry(
                rule=rule,
                source_obj=source_obj,
                source_content_type_id=source_content_type_id,
                record_data=record_data,
                phase=phase,
            )
            queue_row.update(
                {
                    "rule_id": rule.id,
                    "content_type_id": source_content_type_id,
                    "object_id": source_obj.id,
                    "dns_record_content_type_id": dns_record_content_type_id,
                    "record_data": record_data,
                }
            )
            queue_rows.append(queue_row)

        return []

    def flush_batched_create_queue(self):
        """Flush queued create rows with chunked bulk inserts."""
        result = BulkCreateFlushResult()
        if not self._batched_create_state.pending_by_record_class:
            return result

        batch_size = self._context.bulk_create_batched_pipeline_size
        for record_class, queued_rows in self._batched_create_state.pending_by_record_class.items():
            if not queued_rows:
                continue

            for offset in range(0, len(queued_rows), batch_size):
                chunk_rows = queued_rows[offset : offset + batch_size]
                try:
                    self._bulk_create_entries(record_class, chunk_rows, batch_size=batch_size)
                    self._record_bulk_create_successes(chunk_rows, result)
                    if self._batched_create_state.create_failures_recorded:
                        self._delete_failure_states_for_entries_batched(chunk_rows)
                except IntegrityError:
                    self._flush_batched_create_queue_with_fallback(record_class, chunk_rows, result)

        return result

    def _flush_batched_create_queue_with_fallback(self, record_class, queued_rows, result):
        """Recursively isolate failed batched create rows."""
        if not queued_rows:
            return

        try:
            self._bulk_create_entries(
                record_class,
                queued_rows,
                batch_size=min(len(queued_rows), self._context.bulk_create_batched_pipeline_size),
            )
            self._record_bulk_create_successes(queued_rows, result)
            if self._batched_create_state.create_failures_recorded:
                self._delete_failure_states_for_entries_batched(queued_rows)

            return
        except IntegrityError:
            if len(queued_rows) <= self._fast_fallback_singleton_threshold:
                self._flush_batched_create_queue_as_singletons(record_class, queued_rows, result)
                return

        split_index = len(queued_rows) // 2
        first_half = queued_rows[:split_index]
        second_half = queued_rows[split_index:]
        self._flush_batched_create_queue_with_fallback(record_class, first_half, result)
        self._flush_batched_create_queue_with_fallback(record_class, second_half, result)

    def _flush_batched_create_queue_as_singletons(self, record_class, queued_rows, result):
        """Retry failed batched creates one row at a time with savepoints."""
        # TODO(phase-b): Batch successful singleton cleanup per fallback run instead of
        # deleting one failure-state row per successful singleton candidate.
        for queued_row in queued_rows:
            if self._apply_singleton_create(record_class, queued_row):
                self._record_singleton_create_success(queued_row, result)
                self._delete_failure_state_for_candidate(queued_row)
                continue

            self._batched_create_state.create_failures_recorded = True
            self._record_singleton_create_failure(queued_row, result)
            self._upsert_failure_state_for_candidate(queued_row)

    @staticmethod
    def _record_bulk_create_successes(queued_rows, result):
        """Record per-object success counters for one successful bulk-create chunk."""
        for queued_row in queued_rows:
            object_id = queued_row["source_object_id"]
            result.successful_creates_by_object_id[object_id] = (
                result.successful_creates_by_object_id.get(object_id, 0) + 1
            )

    @staticmethod
    def _record_singleton_create_success(queued_row, result):
        """Record per-object success counters for one successful singleton create."""
        object_id = queued_row["source_object_id"]
        result.successful_creates_by_object_id[object_id] = result.successful_creates_by_object_id.get(object_id, 0) + 1

    @staticmethod
    def _record_singleton_create_failure(queued_row, result):
        """Record per-object failure counters for one failed singleton create."""
        object_id = queued_row["source_object_id"]
        result.failed_creates_by_object_id[object_id] = result.failed_creates_by_object_id.get(object_id, 0) + 1

    @staticmethod
    def _bulk_create_entries(record_class, queued_rows, *, batch_size):
        """Create DNS records and tracking rows in one transactional chunk."""
        with transaction.atomic():
            dns_records = [record_class(**queued_row["record_data"]) for queued_row in queued_rows]  # pylint: disable=not-callable
            created_records = record_class.objects.bulk_create(dns_records, batch_size=batch_size)
            tracking_rows = [
                DNSRuleRecord(
                    rule_id=queued_row["rule_id"],
                    content_type_id=queued_row["content_type_id"],
                    object_id=queued_row["object_id"],
                    dns_record_content_type_id=queued_row["dns_record_content_type_id"],
                    dns_record_object_id=dns_record.id,
                )
                for queued_row, dns_record in zip(queued_rows, created_records)
            ]
            DNSRuleRecord.objects.bulk_create(tracking_rows, batch_size=batch_size)

    def _apply_singleton_create(self, record_class, queued_row):
        """Apply one queued create operation in a savepoint."""
        try:
            with transaction.atomic():
                dns_record = record_class(**queued_row["record_data"])  # pylint: disable=not-callable
                dns_record.validated_save()
                DNSRuleRecord.objects.create(
                    rule_id=queued_row["rule_id"],
                    content_type_id=queued_row["content_type_id"],
                    object_id=queued_row["object_id"],
                    dns_record_content_type_id=queued_row["dns_record_content_type_id"],
                    dns_record_object_id=dns_record.id,
                )
            return True
        except (ValidationError, IntegrityError) as exc:
            self._capture_entry_error_details(queued_row, exc)
            self._engine_logger.log_record_create_failure(
                queued_row["rule"],
                queued_row["source_obj"],
                queued_row["desired_record_data"],
                exc,
                phase=queued_row["phase"],
            )
            return False

    def _update_tracked_dns_record_name(self, rule, source_obj, tracking_record, desired_record_data, phase):
        dns_record = self._resolve_prefetched_dns_record(tracking_record)
        if dns_record is None:
            return UpdateResult.FAILED

        desired_name = desired_record_data["name"]
        if dns_record.name == desired_name:
            return UpdateResult.UNCHANGED

        try:
            # Isolate per-record update failures so a single DB error does not
            # poison an outer transaction for subsequent operations.
            with transaction.atomic():
                updated = type(dns_record).objects.filter(pk=dns_record.pk).update(name=desired_name)

            if updated != 1:
                raise ValueError(f"Failed to update DNS record '{dns_record.pk}'")

            dns_record.name = desired_name
        except (ValidationError, IntegrityError, ValueError) as exc:
            self._engine_logger.log_record_update_failure(rule, source_obj, desired_record_data, exc, phase=phase)
            return UpdateResult.FAILED

        return UpdateResult.UPDATED

    def flush_bulk_rename_updates(self, bulk_update_collector):
        """Execute queued rename updates in bulk."""
        result = BulkRenameFlushResult()
        logger.info("Flushing bulk rename updates for %s", bulk_update_collector)

        for record_model, update_entries in bulk_update_collector.items():
            if not update_entries:
                continue

            batch_size = self._context.bulk_rename_update_batch_size
            for offset in range(0, len(update_entries), batch_size):
                chunk_entries = update_entries[offset : offset + batch_size]
                try:
                    self._bulk_update_entries(record_model, chunk_entries, batch_size=batch_size)
                    self._delete_failure_states_for_entries(chunk_entries)
                except IntegrityError:
                    logger.error("IntegrityError (%s); running binary search fallback", chunk_entries)
                    self._flush_bulk_rename_updates_with_fallback(record_model, chunk_entries, result)

        return result

    def _flush_bulk_rename_updates_with_fallback(self, record_model, update_entries, result):
        """Recursively split failed chunks and isolate failing updates."""
        logger.error("Binary search fallback for %s beginning", update_entries)
        if not update_entries:
            return

        result.fallback_chunk_attempt_count += 1
        try:
            logger.error("Binary search fallback for %s attempting bulk update", update_entries)
            self._bulk_update_entries(
                record_model,
                update_entries,
                batch_size=min(len(update_entries), self._context.bulk_rename_update_batch_size),
            )
            self._delete_failure_states_for_entries(update_entries)
            return
        except IntegrityError:
            logger.error("Binary search fallback for %s attempting singleton update", update_entries)
            if len(update_entries) <= self._fast_fallback_singleton_threshold:
                logger.error("Binary search fallback for %s attempting singleton update with threshold", update_entries)
                self._flush_bulk_rename_updates_as_singletons(record_model, update_entries, result)
                return

        split_index = len(update_entries) // 2
        first_half = update_entries[:split_index]
        second_half = update_entries[split_index:]
        self._flush_bulk_rename_updates_with_fallback(record_model, first_half, result)
        self._flush_bulk_rename_updates_with_fallback(record_model, second_half, result)

    def _flush_bulk_rename_updates_as_singletons(self, record_model, update_entries, result):
        """Retry failed chunk updates one row at a time with savepoints."""
        for update_entry in update_entries:
            result.fallback_singleton_attempt_count += 1
            if self._apply_singleton_rename_update(record_model, update_entry):
                self._delete_failure_state_for_candidate(update_entry)
                continue

            source_object_id = update_entry["source_object_id"]
            result.failed_updates_by_object_id[source_object_id] = (
                result.failed_updates_by_object_id.get(source_object_id, 0) + 1
            )
            result.fallback_singleton_failure_count += 1
            result.update_failure_recorded_count += self._upsert_failure_state_for_candidate(update_entry)

    @staticmethod
    def _bulk_update_entries(record_model, update_entries, *, batch_size):
        """Execute one bulk update for queued rename entries."""
        dns_records = [entry["dns_record"] for entry in update_entries]
        if not dns_records:
            return

        with transaction.atomic():
            record_model.objects.bulk_update(dns_records, ["name"], batch_size=batch_size)

    def _apply_singleton_rename_update(self, record_model, update_entry):
        """Apply one rename update in a savepoint and log any failure."""
        dns_record = update_entry["dns_record"]
        desired_name = update_entry["desired_name"]
        try:
            with transaction.atomic():
                updated = record_model.objects.filter(pk=dns_record.pk).update(name=desired_name)

            if updated != 1:
                raise ValueError(f"Failed to update DNS record '{dns_record.pk}'")

            return True
        except (ValidationError, IntegrityError, ValueError) as exc:
            pgcode = ""
            constraint = ""
            db_cause = getattr(exc, "__cause__", None)
            if db_cause is not None:
                pgcode = getattr(db_cause, "pgcode", "") or ""
                constraint = getattr(getattr(db_cause, "diag", None), "constraint_name", "") or ""

            update_entry["error_exception_type"] = type(exc).__name__
            update_entry["error_message"] = str(exc)
            update_entry["error_pgcode"] = pgcode
            update_entry["error_constraint"] = constraint
            self._engine_logger.log_record_update_failure(
                update_entry["rule"],
                update_entry["source_obj"],
                update_entry["desired_record_data"],
                exc,
                phase=update_entry["phase"],
            )

            return False

    def _delete_failure_states_for_entries(self, update_entries):
        """Delete failure-state rows for successfully applied candidate updates.

        This is called only after a chunk/singleton update operation succeeds.
        For each entry, the lookup key is `(source, rule, candidate record key)`.
        """
        for update_entry in update_entries:
            self._delete_failure_state_for_candidate(update_entry)

    def _delete_failure_states_for_entries_batched(self, update_entries):
        """Delete matching failure-state rows using grouped batched predicates.

        This path is currently used for successful create-batch chunk flushes to avoid
        one point query per candidate.
        """
        if not update_entries:
            return

        grouped_entries = defaultdict(list)
        for update_entry in update_entries:
            group_key = (
                update_entry["source_content_type_id"],
                update_entry["rule"].id if update_entry["rule"] else None,
                update_entry["candidate_record_type"],
                update_entry["candidate_zone_id"],
            )
            grouped_entries[group_key].append(update_entry)

        for group_key, group_rows in grouped_entries.items():
            source_content_type_id, rule_id, candidate_record_type, candidate_zone_id = group_key
            match_conditions = []
            for update_entry in group_rows:
                match_conditions.append(
                    Q(
                        source_object_id=update_entry["source_object_id"],
                        candidate_name=update_entry["desired_name"],
                        candidate_address_id=update_entry["candidate_address_id"],
                    )
                )

            if not match_conditions:
                continue

            combined_match = reduce(lambda left, right: left | right, match_conditions)
            DNSRuleFailureState.objects.filter(
                source_content_type_id=source_content_type_id,
                rule_id=rule_id,
                candidate_record_type=candidate_record_type,
                candidate_zone_id=candidate_zone_id,
            ).filter(combined_match).delete()

        # TODO(phase-c): Optionally replace eager cleanup with deferred/background
        # compaction for very large reconciliation runs.

    def _delete_failure_state_for_candidate(self, update_entry):
        """Delete failure-state rows for one successful candidate."""
        DNSRuleFailureState.objects.filter(
            source_content_type_id=update_entry["source_content_type_id"],
            source_object_id=update_entry["source_object_id"],
            rule_id=update_entry["rule"].id if update_entry["rule"] else None,
            candidate_record_type=update_entry["candidate_record_type"],
            candidate_name=update_entry["desired_name"],
            candidate_zone_id=update_entry["candidate_zone_id"],
            candidate_address_id=update_entry["candidate_address_id"],
        ).delete()

    def _upsert_failure_state_for_candidate(self, update_entry):
        """Upsert failure state for one failed singleton update."""
        now = timezone.now()
        state, created = DNSRuleFailureState.objects.get_or_create(
            source_content_type_id=update_entry["source_content_type_id"],
            source_object_id=update_entry["source_object_id"],
            rule_id=update_entry["rule"].id if update_entry["rule"] else None,
            candidate_record_type=update_entry["candidate_record_type"],
            candidate_name=update_entry["desired_name"],
            candidate_zone_id=update_entry["candidate_zone_id"],
            candidate_address_id=update_entry["candidate_address_id"],
            defaults={
                "first_seen": now,
                "last_seen": now,
                "attempt_count": 1,
                "consecutive_failures": 1,
                "latest_exception_type": update_entry.get("error_exception_type", ""),
                "latest_error": update_entry.get("error_message", ""),
                "latest_pgcode": update_entry.get("error_pgcode", ""),
                "latest_constraint": update_entry.get("error_constraint", ""),
            },
        )
        if created:
            return 1

        state.last_seen = now
        state.attempt_count += 1
        state.consecutive_failures += 1
        state.latest_exception_type = update_entry.get("error_exception_type", "")
        state.latest_error = update_entry.get("error_message", "")
        state.latest_pgcode = update_entry.get("error_pgcode", "")
        state.latest_constraint = update_entry.get("error_constraint", "")
        state.save(
            update_fields=[
                "last_seen",
                "attempt_count",
                "consecutive_failures",
                "latest_exception_type",
                "latest_error",
                "latest_pgcode",
                "latest_constraint",
            ]
        )
        return 1

    @staticmethod
    def _capture_entry_error_details(update_entry, exc):
        """Attach database and exception details to a failure-state entry."""
        pgcode = ""
        constraint = ""
        db_cause = getattr(exc, "__cause__", None)
        if db_cause is not None:
            pgcode = getattr(db_cause, "pgcode", "") or ""
            constraint = getattr(getattr(db_cause, "diag", None), "constraint_name", "") or ""

        update_entry["error_exception_type"] = type(exc).__name__
        update_entry["error_message"] = str(exc)
        update_entry["error_pgcode"] = pgcode
        update_entry["error_constraint"] = constraint

    @staticmethod
    def _build_create_failure_state_entry(*, rule, source_obj, source_content_type_id, record_data, phase):
        """Build a normalized failure-state entry for create-path operations."""
        return {
            "rule": rule,
            "source_obj": source_obj,
            "phase": phase,
            "desired_name": record_data["name"],
            "desired_record_data": record_data,
            "source_content_type_id": source_content_type_id,
            "source_object_id": source_obj.id,
            "candidate_record_type": rule.record_type,
            "candidate_zone_id": record_data["zone"].id,
            "candidate_address_id": record_data.get("address_id"),
        }

    def flush_bulk_delete_queue(self, bulk_delete_collector):
        """Execute queued DNS-record deletes in bulk by model/content type."""
        if not bulk_delete_collector:
            return
        batch_size = self._context.bulk_delete_batched_pipeline_size
        content_types = ContentType.objects.in_bulk(bulk_delete_collector.keys())
        for record_content_type_id, record_ids in bulk_delete_collector.items():
            if not record_ids:
                continue

            record_content_type = content_types[record_content_type_id]
            record_model = record_content_type.model_class()
            if record_model is None:
                raise DNSRecordContentTypeResolutionError(
                    "Unable to resolve DNS record content type to model class: "
                    f"id={record_content_type_id} "
                    f"label={record_content_type.app_label}.{record_content_type.model}"
                )

            record_ids_list = list(record_ids)
            for offset in range(0, len(record_ids_list), batch_size):
                chunk = record_ids_list[offset : offset + batch_size]
                self._delete_executor.delete_chunk(
                    record_model=record_model,
                    record_content_type_id=record_content_type_id,
                    record_ids=chunk,
                )

    def delete_tracking_and_dns_record(self, tracking_record):
        """Delete one DNS record for a tracking row.

        Tracking-row cleanup is expected via model-level cascade behavior.
        """
        try:
            tracking_record.dns_record.delete()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "Failed to delete DNS record '%s' and tracking record '%s': %s (%s)",
                tracking_record.dns_record,
                tracking_record,
                exc,
                type(exc).__name__,
            )
            raise

    def _cleanup_records_for_rule(self, rule, source_obj):
        tracking_records = self._get_existing_tracking_records(rule, source_obj)
        deleted_count = 0
        for tracking_record in tracking_records:
            self.delete_tracking_and_dns_record(tracking_record)
            deleted_count += 1

        return deleted_count

    def cleanup_records_for_rule_prefetched(self, tracking_by_rule_id, rule_id, bulk_delete_collector=None):
        """Delete prefetched tracking rows (and DNS records) for one rule id."""
        tracking_rows = tracking_by_rule_id.pop(rule_id, [])
        if bulk_delete_collector is not None:
            for tracking_row in tracking_rows:
                bulk_delete_collector[tracking_row.dns_record_content_type_id].add(tracking_row.dns_record_object_id)

            return len(tracking_rows)

        for tracking_row in tracking_rows:
            self.delete_tracking_and_dns_record(tracking_row)

        return len(tracking_rows)

    def cleanup_orphaned_records(self, source_obj, applicable_rules):
        """Delete tracking/DNS records for rules no longer applicable to object."""
        content_type = ContentType.objects.get_for_model(source_obj)
        existing_tracking_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.pk)
        orphaned_records = existing_tracking_records.exclude(rule__in=applicable_rules)
        deleted_count = 0
        orphaned_rule_ids = orphaned_records.values_list("rule_id", flat=True).distinct()
        for orphaned_rule in DNSRule.objects.filter(pk__in=orphaned_rule_ids):
            deleted_count += self._cleanup_records_for_rule(orphaned_rule, source_obj)

        return deleted_count

    def cleanup_orphaned_records_prefetched(self, tracking_by_rule_id, applicable_rule_ids, bulk_delete_collector=None):
        """Delete prefetched tracking rows for rule ids outside applicable set."""
        deleted_count = 0
        for rule_id in list(tracking_by_rule_id.keys()):
            if rule_id in applicable_rule_ids:
                continue
            deleted_count += self.cleanup_records_for_rule_prefetched(
                tracking_by_rule_id, rule_id, bulk_delete_collector=bulk_delete_collector
            )

        return deleted_count

    @staticmethod
    def _resolve_prefetched_dns_record(tracking_record):
        """Resolve DNS record from prefetch cache when available."""
        dns_record = getattr(tracking_record, "_prefetched_dns_record", None)
        if dns_record is None:
            dns_record = tracking_record.dns_record

        return dns_record

    @staticmethod
    def _get_record_class(record_type):
        return get_dns_record_model_class(record_type)

    def _get_record_content_key(self, dns_record):
        record_type = dns_record.__class__.__name__
        base_key = f"{record_type}:{dns_record.name}:{dns_record.zone_id}"
        suffix = "unknown"
        if hasattr(dns_record, "address_id"):
            suffix = dns_record.address_id

        return f"{base_key}:{suffix}"

    def _get_record_identity_key(self, dns_record):
        record_type = dns_record.__class__.__name__
        if hasattr(dns_record, "address_id"):
            return f"{record_type}:{dns_record.zone_id}:{dns_record.address_id}"

        return self._get_record_content_key(dns_record)

    def _get_record_identity_key_from_data(self, record_data, rule_record_type):
        zone_id = record_data["zone"].id
        record_type = f"{rule_record_type}Record"
        if rule_record_type in ("A", "AAAA"):
            return f"{record_type}:{zone_id}:{record_data['address_id']}"

        return self._get_record_content_key_from_data(record_data, rule_record_type)

    @staticmethod
    def _get_record_content_key_from_data(record_data, rule_record_type):
        zone_id = record_data["zone"].id
        name = record_data["name"]
        record_type = f"{rule_record_type}Record"
        if rule_record_type in ("A", "AAAA"):
            suffix = record_data["address_id"]
        else:
            raise ValueError(f"Unsupported record type for content key generation: {rule_record_type}")

        return f"{record_type}:{name}:{zone_id}:{suffix}"

    @staticmethod
    def _get_existing_tracking_records(rule, source_obj):
        return DNSRuleRecord.objects.filter(
            rule=rule, content_type=ContentType.objects.get_for_model(source_obj), object_id=source_obj.id
        )
