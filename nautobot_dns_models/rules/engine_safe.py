"""Safe reconciliation engine entry point."""

from __future__ import annotations

import re
from typing import Any

from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine import (
    BaseDNSRuleEngine,
    ContentType,
    DNSTemplateEmptyError,
    DNSRuleRecord,
    DNSZone,
    IntegrityError,
    PHASE_CREATE,
    PHASE_UNKNOWN,
    PHASE_UPDATE_RECONCILE,
    TemplateError,
    ValidationError,
    logger,
    models,
    normalize_dns_name,
    wrap_for_template,
)


class SafeDNSRuleEngine(BaseDNSRuleEngine):
    """Default engine preserving normal model-save semantics."""

    def process_object(self, source_obj: Any, created: bool = False) -> dict[str, int | bool]:
        """Safe path object processing."""
        summary = self._initialize_processing_summary()
        content_type = ContentType.objects.get_for_model(source_obj)
        rules = self._get_applicable_rules(source_obj)
        rules_count = len(rules)

        if rules_count == 0:
            logger.debug(f"No DNS rules found for {content_type} - skipping DNS record processing for {source_obj}")
            return summary

        existing_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=str(source_obj.pk))
        existing_count = existing_records.count()
        summary["existing_rule_record_count"] = existing_count
        summary["had_existing_rule_records"] = existing_count > 0
        logger.debug(
            f'DNS record lookup for {source_obj} (pk={source_obj.pk}, name="{getattr(source_obj, "name", "N/A")}"): found {existing_count} existing records'
        )

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

    def _use_lookup_cache(self) -> bool:
        """Safe mode disables lookup caches for strict behavior parity."""
        return False

    def _use_direct_update(self) -> bool:
        """Safe mode updates records via validated_save()."""
        return False

    def _requires_ip_context(self, rule: DNSRule) -> bool:
        """Safe mode always resolves ip context for template rendering."""
        del rule
        return True

    def _create_dns_records_for_object(self, source_obj: Any, applicable_rules: list[DNSRule]) -> dict[str, int | bool]:
        """Safe path create behavior."""
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

    def _create_dns_record_from_rule(self, rule: DNSRule, source_obj: Any) -> list[Any]:
        """Safe path create record from rule."""
        desired_record_data_list = self._calculate_desired_record_data(rule, source_obj, phase=PHASE_CREATE)
        if not desired_record_data_list:
            return []
        return self._create_records_from_data(rule, source_obj, desired_record_data_list, phase=PHASE_CREATE)

    def _update_dns_records_for_object(self, source_obj: Any, applicable_rules: list[DNSRule]) -> dict[str, int | bool]:
        """Safe path update behavior."""
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

    def _reconcile_records_for_rule(self, rule: DNSRule, source_obj: Any) -> dict[str, int]:
        """Safe path reconciliation for one rule/object."""
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

    def _calculate_desired_record_data(
        self, rule: DNSRule, source_obj: Any, phase: str = PHASE_UNKNOWN
    ) -> list[dict[str, Any]]:
        """Safe path desired-data calculation."""
        base_context = {"obj": wrap_for_template(source_obj)}
        requires_ip_context = self._requires_ip_context(rule)
        rendered_name = self._render_template(rule.name_template, base_context, "name_template")
        shared_record_data = {"name": normalize_dns_name(rendered_name)}

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
                logger.debug(f"Zones for rule {rule.name}: {zones} (selected views: {selected_views})")
                for zone in zones:
                    all_record_data.append({**record_data, "zone": zone})
            except (ValidationError, DNSTemplateEmptyError, TemplateError, ValueError) as exc:
                self._log_candidate_skip(rule, source_obj, record_data, exc, phase=phase)
                continue
        return all_record_data

    def _get_zones_for_rule(
        self, rule: DNSRule, context: dict[str, Any], selected_views: list[models.DNSView]
    ) -> list[DNSZone]:
        """Safe path zone resolution (no cache)."""
        if rule.zone_template:
            zone_name = self._render_template(rule.zone_template, context, "zone_template")
            view_ids = [view.id for view in selected_views]
            zones = list(DNSZone.objects.filter(name=zone_name, dns_view_id__in=view_ids))
            found_view_ids = {zone.dns_view_id for zone in zones}
            missing_view_ids = set(view_ids) - found_view_ids
            if missing_view_ids:
                missing_view_names = list(models.DNSView.objects.filter(id__in=missing_view_ids).values_list("name", flat=True))
                raise ValidationError(
                    {
                        "zone_template": (
                            f"Zone '{zone_name}' does not exist in selected DNS view(s): "
                            f"{', '.join(sorted(missing_view_names))}"
                        )
                    }
                )
            return zones
        raise ValidationError({"zone_template": "DNS rule must define a zone_template."})

    def _get_dns_views_for_rule(self, rule: DNSRule, context: dict[str, Any]) -> list[models.DNSView]:
        """Safe path view resolution (no cache)."""
        if not rule.view_template:
            return [models.DNSView.objects.get(pk=models.get_default_view_pk())]
        rendered = self._render_template(rule.view_template, context, "view_template")
        raw_names = [token.strip() for token in re.split(r"[\s,]+", rendered) if token.strip()]
        if not raw_names:
            raise ValidationError({"view_template": "view_template rendered no DNS view names."})
        requested_names = list(dict.fromkeys(raw_names))
        matched_views = list(models.DNSView.objects.filter(name__in=requested_names))
        matched_by_name = {view.name: view for view in matched_views}
        missing_names = [name for name in raw_names if name not in matched_by_name]
        if missing_names:
            raise ValidationError(
                {"view_template": "DNS view(s) not found from view_template: " f"{', '.join(sorted(set(missing_names)))}"}
            )
        ordered_views = []
        seen_ids = set()
        for name in raw_names:
            view = matched_by_name[name]
            if view.id in seen_ids:
                continue
            ordered_views.append(view)
            seen_ids.add(view.id)
        return ordered_views

    def _update_tracking_record_dns_record(
        self,
        rule: DNSRule,
        source_obj: Any,
        tracking_record,
        desired_record_data: dict[str, Any],
        phase: str,
    ) -> str:
        """Safe path in-place update using validated_save()."""
        dns_record = tracking_record.dns_record
        desired_name = desired_record_data["name"]
        if dns_record.name == desired_name:
            return "unchanged"
        try:
            dns_record.name = desired_name
            dns_record.validated_save()
        except (ValidationError, IntegrityError, ValueError) as exc:
            self._log_record_update_failure(rule, source_obj, desired_record_data, exc, phase=phase)
            return "failed"
        return "updated"

