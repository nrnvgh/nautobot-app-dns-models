"""Fast reconciliation engine entry point."""

from __future__ import annotations

from collections import defaultdict
import re

from django.db.models import Case, CharField, Value, When
from jinja2 import Environment
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


class FastDNSRuleEngine(BaseDNSRuleEngine):
    """Performance-oriented engine using fast-mode shortcuts."""

    def __init__(self):
        """Initialize fast-path lookup caches."""
        self._default_view_cache = None
        self._zone_lookup_cache = {}
        self._applicable_rules_cache = {}
        self._prefetched_tracking_records_by_object_id = {}
        self._prefetched_tracking_content_type_id = None
        self._prefetched_dns_records_by_content_type_and_id = {}
        self._compiled_template_cache = {}
        self._jinja_env = Environment(autoescape=False)

    def reset_runtime_caches(self):
        """Clear fast-path caches between job runs to avoid stale rule/template data."""
        self._default_view_cache = None
        self._zone_lookup_cache.clear()
        self._applicable_rules_cache.clear()
        self._prefetched_tracking_records_by_object_id.clear()
        self._prefetched_tracking_content_type_id = None
        self._prefetched_dns_records_by_content_type_and_id.clear()

    def preload_tracking_records_for_objects(self, source_objects):
        """Bulk-load DNSRuleRecord rows for upcoming batch objects."""
        self._prefetched_tracking_records_by_object_id.clear()
        self._prefetched_tracking_content_type_id = None
        if not source_objects:
            return

        content_type = ContentType.objects.get_for_model(source_objects[0])
        object_ids = [str(source_obj.pk) for source_obj in source_objects]
        all_tracking_records = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id__in=object_ids))

        grouped_by_object_id = defaultdict(list)
        for tracking_record in all_tracking_records:
            grouped_by_object_id[str(tracking_record.object_id)].append(tracking_record)

        self._prefetched_tracking_records_by_object_id = dict(grouped_by_object_id)
        self._prefetched_tracking_content_type_id = content_type.pk
        self._prefetched_dns_records_by_content_type_and_id.clear()

        record_ids_by_content_type = defaultdict(list)
        for tracking_record in all_tracking_records:
            record_ids_by_content_type[int(tracking_record.dns_record_content_type_id)].append(
                tracking_record.dns_record_object_id
            )

        if not record_ids_by_content_type:
            return

        content_types_by_id = ContentType.objects.in_bulk(record_ids_by_content_type.keys())
        for dns_record_content_type_id, record_ids in record_ids_by_content_type.items():
            dns_record_content_type = content_types_by_id.get(dns_record_content_type_id)
            if dns_record_content_type is None:
                continue
            model_class = dns_record_content_type.model_class()
            if model_class is None:
                continue
            for record_id, dns_record in model_class.objects.in_bulk(record_ids).items():
                self._prefetched_dns_records_by_content_type_and_id[(dns_record_content_type_id, record_id)] = dns_record

    def process_object(self, source_obj, created=False):
        """Fast path object processing."""
        content_type = ContentType.objects.get_for_model(source_obj)
        summary = self._initialize_processing_summary()
        rules = self._get_applicable_rules(source_obj)
        rules_count = len(rules)

        if rules_count == 0:
            logger.debug(f"No DNS rules found for {content_type} - skipping DNS record processing for {source_obj}")
            return summary

        if created:
            create_summary = self._create_dns_records_for_object(source_obj, rules)
            summary["changed_record_count"] = create_summary["changed_record_count"]
            summary["changed"] = create_summary["changed"]
            summary["record_ops_create_count"] = create_summary["record_ops_create_count"]
            summary["record_ops_delete_count"] = create_summary["record_ops_delete_count"]
        else:
            update_summary = self._update_dns_records_for_object(source_obj, rules)
            summary["existing_rule_record_count"] = update_summary["existing_rule_record_count"]
            summary["had_existing_rule_records"] = update_summary["had_existing_rule_records"]
            summary["changed_record_count"] = update_summary["changed_record_count"]
            summary["changed"] = update_summary["changed"]
            summary["record_ops_create_count"] = update_summary["record_ops_create_count"]
            summary["record_ops_delete_count"] = update_summary["record_ops_delete_count"]

        return summary

    def _use_lookup_cache(self):
        """Fast mode enables lookup cache reuse within process lifetime."""
        return True

    def _use_direct_update(self):
        """Fast mode applies in-place rename updates via direct SQL update."""
        return True

    def _render_template(self, template_str, context, field_name):
        """Fast mode renders from a cached compiled Jinja template."""
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

    def _requires_ip_context(self, rule):
        """Fast mode resolves ip context only when templates reference ip."""
        template_text = " ".join([rule.view_template or "", rule.zone_template or ""])
        return bool(re.search(r"\bip\b", template_text))

    def _object_needs_dns_records_for_rule(self, source_obj, rule):
        """Fast path avoids extra preflight exists() queries for interface/service A/AAAA rules."""
        if rule.record_type in ("A", "AAAA"):
            source_type = source_obj.__class__.__name__
            if source_type in ("Interface", "VMInterface", "Service"):
                return True
        return super()._object_needs_dns_records_for_rule(source_obj, rule)

    def _get_applicable_rules(self, source_obj):
        """Fast path applicable-rule resolution with scope-key cache."""
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

    def _create_dns_records_for_object(self, source_obj, applicable_rules):
        """Fast path create behavior."""
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

    def _create_dns_record_from_rule(self, rule, source_obj):
        """Fast path create record from rule."""
        desired_record_data_list = self._calculate_desired_record_data(rule, source_obj, phase=PHASE_CREATE)
        if not desired_record_data_list:
            return []
        return self._create_records_from_data(rule, source_obj, desired_record_data_list, phase=PHASE_CREATE)

    def _update_dns_records_for_object(self, source_obj, applicable_rules):
        """Fast path update behavior."""
        content_type = ContentType.objects.get_for_model(source_obj)
        all_tracking_records = None
        if self._prefetched_tracking_content_type_id == content_type.pk:
            all_tracking_records = self._prefetched_tracking_records_by_object_id.pop(str(source_obj.pk), None)
        if all_tracking_records is None:
            all_tracking_records = list(DNSRuleRecord.objects.filter(content_type=content_type, object_id=str(source_obj.pk)))
        existing_count = len(all_tracking_records)
        tracking_records_by_rule_id = self._group_tracking_records_by_rule_id(all_tracking_records)
        applicable_rule_ids = {rule.pk for rule in applicable_rules}
        delete_count = self._cleanup_orphaned_records_prefetched(tracking_records_by_rule_id, applicable_rule_ids)
        create_count = 0
        update_count = 0

        for rule in applicable_rules:
            if not self._object_needs_dns_records_for_rule(source_obj, rule):
                delete_count += self._cleanup_records_for_rule_prefetched(tracking_records_by_rule_id, rule.pk)
                continue
            try:
                reconcile_summary = self._reconcile_records_for_rule_prefetched(
                    rule, source_obj, tracking_records_by_rule_id.get(rule.pk, [])
                )
                create_count += reconcile_summary["create"]
                delete_count += reconcile_summary["delete"]
                update_count += reconcile_summary.get("update", 0)
            except (TemplateError, DNSTemplateEmptyError, DNSZone.DoesNotExist, ValueError) as exc:
                self._log_rule_processing_error(rule, source_obj, exc, phase=PHASE_UPDATE_RECONCILE, cleanup=True)
                # Fallback to DB-backed cleanup for robustness on unexpected mid-reconcile failures.
                delete_count += self._cleanup_records_for_rule(rule, source_obj)

        changed_record_count = create_count + delete_count + update_count
        return {
            "had_existing_rule_records": existing_count > 0,
            "existing_rule_record_count": existing_count,
            "changed": changed_record_count > 0,
            "changed_record_count": changed_record_count,
            "record_ops_create_count": create_count,
            "record_ops_delete_count": delete_count,
        }

    def _reconcile_records_for_rule(self, rule, source_obj):
        """Fast path reconciliation for one rule/object."""
        tracking_records = self._get_existing_tracking_records(rule, source_obj)
        return self._reconcile_records_for_rule_prefetched(rule, source_obj, tracking_records)

    def _group_tracking_records_by_rule_id(
        self, tracking_records
    ):
        """Group pre-fetched tracking records by rule id."""
        grouped_records = defaultdict(list)
        for tracking_record in tracking_records:
            grouped_records[tracking_record.rule_id].append(tracking_record)
        return grouped_records

    def _cleanup_orphaned_records_prefetched(
        self,
        tracking_records_by_rule_id,
        applicable_rule_ids,
    ):
        """Delete records from rules that are no longer applicable, using pre-fetched data."""
        deleted_count = 0
        for rule_id, tracking_records in tracking_records_by_rule_id.items():
            if rule_id in applicable_rule_ids:
                continue
            for tracking_record in tracking_records:
                self._delete_tracking_and_dns_record(tracking_record)
                deleted_count += 1
        return deleted_count

    def _cleanup_records_for_rule_prefetched(
        self,
        tracking_records_by_rule_id,
        rule_id,
    ):
        """Delete all tracking records for one applicable rule using pre-fetched data."""
        deleted_count = 0
        for tracking_record in tracking_records_by_rule_id.get(rule_id, []):
            self._delete_tracking_and_dns_record(tracking_record)
            deleted_count += 1
        return deleted_count

    def _reconcile_records_for_rule_prefetched(
        self,
        rule,
        source_obj,
        tracking_records,
    ):
        """Fast path reconciliation for one rule/object with pre-fetched tracking records."""
        dns_records_by_object_id = self._bulk_resolve_tracking_dns_records(rule, tracking_records)
        existing_records_by_content = {}
        existing_records_by_identity = {}
        for tracking_record in tracking_records:
            dns_record = dns_records_by_object_id.get(tracking_record.dns_record_object_id)
            if dns_record is None:
                continue
            # Avoid per-record GenericFK query if downstream code dereferences dns_record.
            tracking_record._state.fields_cache["dns_record"] = dns_record
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

        rename_candidates = []
        keep_count = 0
        desired_by_tracking = {}
        for identity_key in records_to_check_for_update:
            tracking_record = existing_records_by_identity[identity_key]
            desired_record = desired_records_by_identity[identity_key]
            desired_name = desired_record["name"]
            if tracking_record.dns_record.name == desired_name:
                keep_count += 1
                continue
            rename_candidates.append((tracking_record, desired_name))
            desired_by_tracking[str(tracking_record.pk)] = desired_record

        updated_count, skipped_update = self._batch_update_tracking_record_dns_names(
            rule=rule,
            source_obj=source_obj,
            rename_candidates=rename_candidates,
            desired_by_tracking=desired_by_tracking,
            phase=PHASE_UPDATE_RECONCILE,
        )

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

    def _batch_update_tracking_record_dns_names(
        self,
        rule,
        source_obj,
        rename_candidates,
        desired_by_tracking,
        phase,
        chunk_size=500,
    ):
        """Batch in-place DNS record renames using SQL CASE updates."""
        if not rename_candidates:
            return 0, 0

        updated_count = 0
        failed_count = 0
        record_class = self._get_record_class(rule.record_type)

        for index in range(0, len(rename_candidates), chunk_size):
            chunk = rename_candidates[index : index + chunk_size]
            desired_name_by_dns_pk = {tracking_record.dns_record.pk: desired_name for tracking_record, desired_name in chunk}
            try:
                updated_rows = record_class.objects.filter(pk__in=desired_name_by_dns_pk.keys()).update(
                    name=Case(
                        *[
                            When(pk=dns_pk, then=Value(desired_name))
                            for dns_pk, desired_name in desired_name_by_dns_pk.items()
                        ],
                        output_field=CharField(),
                    )
                )
                if updated_rows != len(desired_name_by_dns_pk):
                    raise ValueError(
                        f"Batch update touched {updated_rows} rows, expected {len(desired_name_by_dns_pk)}"
                    )
                updated_count += len(desired_name_by_dns_pk)
                for tracking_record, desired_name in chunk:
                    tracking_record.dns_record.name = desired_name
            except Exception:  # pylint: disable=broad-exception-caught
                for tracking_record, _desired_name in chunk:
                    desired_record_data = desired_by_tracking.get(str(tracking_record.pk))
                    if desired_record_data is None:
                        failed_count += 1
                        continue
                    update_result = self._update_tracking_record_dns_record(
                        rule=rule,
                        source_obj=source_obj,
                        tracking_record=tracking_record,
                        desired_record_data=desired_record_data,
                        phase=phase,
                    )
                    if update_result == "updated":
                        updated_count += 1
                    elif update_result != "unchanged":
                        failed_count += 1

        return updated_count, failed_count

    def _bulk_resolve_tracking_dns_records(
        self,
        rule,
        tracking_records,
    ):
        """Resolve DNS records for tracking rows in one bulk query."""
        if not tracking_records:
            return {}

        resolved_records = {}
        missing_record_ids = []
        for tracking_record in tracking_records:
            cache_key = (int(tracking_record.dns_record_content_type_id), tracking_record.dns_record_object_id)
            cached_dns_record = self._prefetched_dns_records_by_content_type_and_id.get(cache_key)
            if cached_dns_record is None:
                missing_record_ids.append(tracking_record.dns_record_object_id)
                continue
            resolved_records[tracking_record.dns_record_object_id] = cached_dns_record

        if not missing_record_ids:
            return resolved_records

        record_class = self._get_record_class(rule.record_type)
        resolved_records.update(record_class.objects.in_bulk(missing_record_ids))
        return resolved_records

    def _calculate_desired_record_data(
        self, rule, source_obj, phase=PHASE_UNKNOWN
    ):
        """Fast path desired-data calculation."""
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
                for zone in zones:
                    all_record_data.append({**record_data, "zone": zone})
            except (ValidationError, DNSTemplateEmptyError, TemplateError, ValueError) as exc:
                self._log_candidate_skip(rule, source_obj, record_data, exc, phase=phase)
                continue
        return all_record_data

    def _get_zones_for_rule(
        self, rule, context, selected_views
    ):
        """Fast path zone resolution (cache-enabled)."""
        if rule.zone_template:
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

    def _get_dns_views_for_rule(self, rule, context):
        """Fast path view resolution (cache-enabled default view)."""
        if not rule.view_template:
            if self._default_view_cache is None:
                self._default_view_cache = models.DNSView.objects.get(pk=models.get_default_view_pk())
            return [self._default_view_cache]
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
        rule,
        source_obj,
        tracking_record,
        desired_record_data,
        phase,
    ):
        """Fast path in-place update using direct SQL update."""
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

