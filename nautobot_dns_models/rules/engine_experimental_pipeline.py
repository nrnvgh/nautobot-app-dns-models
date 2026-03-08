"""Experimental batch-native reconciliation engine."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine import (
    ContentType,
    DNSRuleRecord,
    DNSTemplateEmptyError,
    DNSZone,
    PHASE_UPDATE_RECONCILE,
    TemplateError,
    logger,
)
from nautobot_dns_models.rules.engine_experimental import ExperimentalDNSRuleEngine


class ExperimentalPipelineDNSRuleEngine(ExperimentalDNSRuleEngine):
    """Experimental engine that reconciles in explicit batch phases."""

    def process_objects_pipeline(self, source_objects: list[Any], created: bool = False) -> list[dict[str, Any]]:
        """Run a four-phase pipeline for a same-model object batch."""
        if not source_objects:
            return []
        if created:
            return [self.process_object(source_obj, created=True) for source_obj in source_objects]

        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [str(source_obj.pk) for source_obj in source_objects]
        tracking_rows = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))

        tracking_by_object_id: dict[str, list[DNSRuleRecord]] = defaultdict(list)
        for tracking_row in tracking_rows:
            tracking_by_object_id[str(tracking_row.object_id)].append(tracking_row)

        prepared_entries = []
        for source_obj in source_objects:
            rules = self._get_applicable_rules(source_obj)
            desired_by_rule_id: dict[Any, list[dict[str, Any]]] = {}
            failed_rule_ids: set[Any] = set()
            for rule in rules:
                if not self._object_needs_dns_records_for_rule(source_obj, rule):
                    continue
                try:
                    desired_by_rule_id[rule.pk] = self._calculate_desired_record_data(
                        rule, source_obj, phase=PHASE_UPDATE_RECONCILE
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
                    "tracking_rows": tracking_by_object_id.get(str(source_obj.pk), []),
                }
            )

        summaries: list[dict[str, Any]] = []
        for entry in prepared_entries:
            summaries.append(self._apply_prepared_reconcile_entry(entry))
        return summaries

    def _apply_prepared_reconcile_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Apply prepared desired/tracking data for one source object."""
        source_obj = entry["source_obj"]
        rules: list[DNSRule] = entry["rules"]
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
            if not self._object_needs_dns_records_for_rule(source_obj, rule):
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
    ) -> dict[str, int]:
        """Reconcile one rule using caller-provided tracking rows and desired rows."""
        existing_records_by_identity = {}
        for tracking_record in tracking_records:
            identity_key = self._get_record_identity_key(tracking_record.dns_record)
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
