"""Record reconciliation and persistence collaborator."""

import logging
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from jinja2 import TemplateError

from nautobot_dns_models.exceptions import DNSRecordContentTypeResolutionError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.models import DNSRule, DNSRuleRecord, DNSZone
from nautobot_dns_models.record_type_mapping import get_dns_record_model_class
from nautobot_dns_models.rules.engine.constants import PHASE_CREATE, PHASE_UPDATE_RECONCILE
from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER
from nautobot_dns_models.rules.engine.reconcile import ReconcilePlanner
from nautobot_dns_models.rules.engine.update_strategies import UpdateResult

logger = logging.getLogger(__name__)


class RecordWriter:
    """Create, reconcile, and cleanup DNS records."""

    def __init__(
        self,
        cache,
        context,
        *,
        resolver,
        materializer,
        batched_create_state,
        delete_executor,
        update_executor,
        reconcile_planner=None,
    ):
        """Store collaborator references and shared runtime context.

        Args:
            cache: Shared engine cache for model/content-type memoization.
            context: Engine runtime context containing execution settings.
            resolver: Rule resolver collaborator used for applicability checks.
            materializer: Desired-record materialization collaborator.
            batched_create_state: Shared mutable state for batched-create queueing.
            delete_executor: Delete strategy for standard/fast execution modes.
            update_executor: Update strategy for standard/fast execution modes.
            reconcile_planner: Optional planner for reconcile create/delete/update diffs.
        """
        self._cache = cache
        self._context = context
        self._resolver = resolver
        self._materializer = materializer
        self._batched_create_state = batched_create_state
        self._delete_executor = delete_executor
        self._update_executor = update_executor
        self._engine_logger = DEFAULT_ENGINE_LOGGER
        self._reconcile_planner = reconcile_planner or ReconcilePlanner()

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
            "record_ops_create_count": changed_record_count,
            "record_ops_delete_count": 0,
            "record_ops_update_count": 0,
        }

    def update_dns_records_for_object(self, source_obj, applicable_rules):
        """Update/reconcile records for one source object."""
        delete_count = self.cleanup_orphaned_records(source_obj, applicable_rules)
        create_count = 0
        update_count = 0
        for rule in applicable_rules:
            if not self._resolver.object_needs_dns_records_for_rule(source_obj, rule):
                delete_count += self._cleanup_records_for_rule(rule, source_obj)
                continue
            try:
                reconcile_summary = self.reconcile_records_for_rule(rule, source_obj)
                create_count += reconcile_summary["create"]
                delete_count += reconcile_summary["delete"]
                update_count += reconcile_summary.get("update", 0)
            except (TemplateError, DNSRuleTemplateRenderedEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._engine_logger.log_rule_processing_error(
                    rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True
                )
                delete_count += self._cleanup_records_for_rule(rule, source_obj)

        changed_record_count = create_count + delete_count + update_count

        return {
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "record_ops_create_count": create_count,
            "record_ops_delete_count": delete_count,
            "record_ops_update_count": update_count,
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

        for identity_key in plan.records_to_delete:
            self.delete_tracking_and_dns_record(plan.existing_records_by_identity[identity_key])

        updated_count = 0
        keep_count = 0
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
                keep_count += 1
            else:
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
                tracking_row._prefetched_dns_record = records_by_id.get(tracking_row.dns_record_object_id)

    def _create_records_from_data(self, source_obj, rule, record_data_list, phase=PHASE_CREATE):
        if self._batched_create_state.active:
            return self._queue_records_for_batched_create(
                rule=rule, source_obj=source_obj, record_data_list=record_data_list
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
                self._engine_logger.log_record_create_failure(rule, source_obj, record_data, exc, phase=phase)
                continue

        return created_records

    def _queue_records_for_batched_create(self, rule, source_obj, record_data_list):
        if not record_data_list:
            return []
        record_class = self._get_record_class(rule.record_type)
        source_content_type_id = ContentType.objects.get_for_model(source_obj).pk
        dns_record_content_type_id = ContentType.objects.get_for_model(record_class).pk
        queue_rows = self._batched_create_state.pending_by_record_class[record_class]
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

        return [None] * len(record_data_list)

    def flush_batched_create_queue(self):
        """Flush queued create rows with chunked bulk inserts."""
        if not self._batched_create_state.pending_by_record_class:
            return
        batch_size = self._context.bulk_create_batched_pipeline_size
        with transaction.atomic():
            for record_class, queued_rows in self._batched_create_state.pending_by_record_class.items():
                if not queued_rows:
                    continue
                for offset in range(0, len(queued_rows), batch_size):
                    chunk_rows = queued_rows[offset : offset + batch_size]
                    dns_records = [record_class(**queued_row["record_data"]) for queued_row in chunk_rows]  # pylint: disable=not-callable
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

    def _update_tracking_record_dns_record(self, rule, source_obj, tracking_record, desired_record_data, phase):
        dns_record = self._resolve_prefetched_dns_record(tracking_record)
        if dns_record is None:
            return UpdateResult.FAILED
        desired_name = desired_record_data["name"]
        if dns_record.name == desired_name:
            return UpdateResult.UNCHANGED
        try:
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
        for record_model, update_entries in bulk_update_collector.items():
            if not update_entries:
                continue
            record_model.objects.bulk_update(
                update_entries, ["name"], batch_size=self._context.bulk_rename_update_batch_size
            )

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
