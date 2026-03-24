"""Jobs for DNS reconciliation workflows."""

from collections import defaultdict
from dataclasses import dataclass, field
from time import perf_counter

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import widgets
from nautobot.apps.jobs import (
    BooleanVar,
    DryRunVar,
    IntegerVar,
    Job,
    MultiObjectVar,
    ObjectVar,
    StringVar,
    register_jobs,
)
from nautobot.dcim.models import Location
from nautobot.tenancy.models import Tenant

from nautobot_dns_models.constants.supported_models import (
    SUPPORTED_PARENT_CHILD_MODEL_RELATIONS,
    SUPPORTED_SOURCE_MODEL_MAP,
    SUPPORTED_SOURCE_MODELS,
    get_content_type_query_params,
)
from nautobot_dns_models.exceptions import DNSRuleEngineIntegrityError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine import DNSRuleEngine
from nautobot_dns_models.rules.scope_filters import BulkScopeFilterBuilder

name = "DNS Reconciliation Jobs"  # pylint: disable=invalid-name


@dataclass
class ReconcileRunSummary:
    """Mutable accumulator for reconciliation execution and outcome counters."""

    scanned_model_labels: set[str] = field(default_factory=set)
    targets_seen: int = 0
    processed_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    skipped_scope_count: int = 0
    objects_with_existing_rule_records: int = 0
    existing_rule_record_count: int = 0
    objects_changed: int = 0
    changed_record_count: int = 0
    record_ops_create_count: int = 0
    record_ops_delete_count: int = 0

    def mark_scope_skipped(self):
        """Increment count for targets skipped by location/tenant scope filters."""
        self.skipped_scope_count += 1

    def mark_target_seen(self):
        """Increment count for in-scope targets encountered."""
        self.targets_seen += 1

    def mark_processed_failure(self):
        """Increment counters for a failed processing attempt."""
        self.processed_count += 1
        self.failure_count += 1

    def mark_processed_success(self, processing_summary):
        """Increment success counters and apply engine-provided reconciliation metrics."""
        self.processed_count += 1
        self.success_count += 1

        if processing_summary.had_existing_rule_records:
            self.objects_with_existing_rule_records += 1
            self.existing_rule_record_count += processing_summary.existing_rule_record_count

        if processing_summary.changed_record_count > 0:
            self.objects_changed += 1
            self.changed_record_count += processing_summary.changed_record_count

        self.record_ops_create_count += processing_summary.record_ops_create_count
        self.record_ops_delete_count += processing_summary.record_ops_delete_count

    def as_execution_dict(self):
        """Serialize execution counters for job result output."""
        return {
            "targets_seen": self.targets_seen,
            "processed_count": self.processed_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_scope_count": self.skipped_scope_count,
        }

    def as_reconciliation_dict(self):
        """Serialize reconciliation counters for job result output."""
        return {
            "objects_with_existing_rule_records": self.objects_with_existing_rule_records,
            "existing_rule_record_count": self.existing_rule_record_count,
            "objects_changed": self.objects_changed,
            "record_ops_create_count": self.record_ops_create_count,
            "record_ops_delete_count": self.record_ops_delete_count,
            "record_ops_total_count": self.record_ops_create_count + self.record_ops_delete_count,
            "changed_record_count": self.changed_record_count,
        }


#
# Module-level helpers shared by both job classes.
#


def _limit_reached(summary, limit):
    """Return whether in-scope processing limit has been reached."""
    return bool(limit) and summary.targets_seen >= limit


def _build_result_payload(
    summary,
    *,
    dryrun,
    single_object,
    include_children,
    selected_model_labels,
    rules=None,
    location_ids=None,
    tenant_ids=None,
    limit=None,
    batch_size=100,
):
    """Build structured job result payload from run context and accumulated counters."""
    return {
        "schema_version": 1,
        "mode": {
            "dryrun": bool(dryrun),
            "single_object": bool(single_object),
            "include_children": bool(include_children),
        },
        "scope": {
            "scanned_models": sorted(summary.scanned_model_labels),
            "filters": {
                "source_models": sorted(selected_model_labels),
                "rule_ids": sorted(str(rule.pk) for rule in (rules or [])),
                "location_ids": sorted(str(location_id) for location_id in (location_ids or set())),
                "tenant_ids": sorted(str(tenant_id) for tenant_id in (tenant_ids or set())),
                "limit": limit,
                "batch_size": batch_size,
            },
        },
        "execution": summary.as_execution_dict(),
        "reconciliation": summary.as_reconciliation_dict(),
        "errors": [],
    }


def _log_result_summary(logger, result):
    """Emit standard reconciliation summary log line."""
    execution = result["execution"]
    reconciliation = result["reconciliation"]
    mode = result["mode"]
    runtime_seconds = execution.get("runtime_seconds")
    logger.info(
        (
            "Reconciliation results: "
            "mode=%s "
            "models=[%s] "
            "seen=%d processed=%d success=%d failure=%d skipped_scope=%d "
            "objects_changed=%d record_ops(create=%d delete=%d total=%d) "
            "runtime_s=%.3f"
        ),
        "dryrun" if mode["dryrun"] else "apply",
        ",".join(result["scope"]["scanned_models"]) or "-",
        execution["targets_seen"],
        execution["processed_count"],
        execution["success_count"],
        execution["failure_count"],
        execution["skipped_scope_count"],
        reconciliation["objects_changed"],
        reconciliation["record_ops_create_count"],
        reconciliation["record_ops_delete_count"],
        reconciliation["record_ops_total_count"],
        float(runtime_seconds) if runtime_seconds is not None else 0.0,
    )


class ReconcileDNSBulkJob(Job):
    """Reconcile DNS records for all or selected source objects in bulk mode."""

    class Meta:
        """Metadata for job definition."""

        name = "Reconcile DNS Records (Bulk)"
        description = (
            "Reconcile rule-driven DNS records for all objects or a filtered subset of supported source models."
        )
        has_sensitive_variables = False

    _bulk_scope_filter_builder = BulkScopeFilterBuilder()

    dryrun = DryRunVar(description="Preview targets only; do not apply reconciliation updates.")
    source_models = MultiObjectVar(
        model=ContentType,
        query_params=get_content_type_query_params(),
        required=False,
        description="Optional source model filter for bulk runs.",
    )
    rules = MultiObjectVar(
        model=DNSRule,
        required=False,
        description="Optional rule filter; defaults to all enabled rules.",
        query_params={"content_type": "$source_models"},
    )
    locations = MultiObjectVar(
        model=Location,
        required=False,
        description="Optional source-object location filter.",
    )
    tenants = MultiObjectVar(
        model=Tenant,
        required=False,
        description="Optional source-object tenant filter.",
    )
    limit = IntegerVar(
        required=False,
        min_value=1,
        description="Optional maximum number of in-scope objects to process.",
    )
    batch_size = IntegerVar(
        default=500,
        min_value=1,
        max_value=5000,
        description="Pipeline batch size for fetch/render/delta/execute phases.",
    )

    def run(
        self,
        dryrun,
        source_models=None,
        rules=None,
        locations=None,
        tenants=None,
        limit=None,
        batch_size=500,
    ):  # pylint: disable=too-many-arguments,arguments-differ
        """Execute bulk DNS reconciliation."""
        started_at = perf_counter()

        selected_engine = DNSRuleEngine()

        location_ids = {location.id for location in (locations or [])}
        tenant_ids = {tenant.id for tenant in (tenants or [])}

        selected_model_labels, invalid_model_labels = self._normalize_model_labels(source_models)
        if invalid_model_labels:
            self.fail(
                "Unsupported source_models: "
                f"{', '.join(sorted(invalid_model_labels))}. "
                f"Supported values: {', '.join(sorted(SUPPORTED_SOURCE_MODEL_MAP.keys()))}"
            )
            return {
                "dryrun": bool(dryrun),
                "error": "invalid_source_models",
                "invalid_source_models": sorted(invalid_model_labels),
            }

        mismatched_rules = self._get_rules_mismatched_to_source_models(rules, selected_model_labels)
        if mismatched_rules:
            mismatched_rule_ids = sorted(str(rule.pk) for rule in mismatched_rules)
            self.fail(
                "Selected rules are not valid for selected source_models. "
                f"Mismatched rule IDs: {', '.join(mismatched_rule_ids)}."
            )
            return {
                "dryrun": bool(dryrun),
                "error": "rules_source_model_mismatch",
                "invalid_rule_ids": mismatched_rule_ids,
                "selected_source_models": sorted(selected_model_labels),
            }

        target_labels = self._resolve_target_models(selected_rules=rules, selected_model_labels=selected_model_labels)
        targets = self._iter_targets(
            target_labels=target_labels,
            batch_size=batch_size,
            limit=limit,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        )
        summary = ReconcileRunSummary()
        summary.scanned_model_labels.update(target_labels)

        try:
            self._process_pipeline_targets_in_batches(
                targets,
                summary=summary,
                selected_engine=selected_engine,
                dryrun=dryrun,
                limit=limit,
                batch_size=batch_size,
            )
        except DNSRuleEngineIntegrityError as exc:
            self.fail(str(exc))
            return {
                "dryrun": bool(dryrun),
                "error": "engine_integrity_error",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }

        result = _build_result_payload(
            summary,
            dryrun=bool(dryrun),
            single_object=False,
            include_children=False,
            selected_model_labels=selected_model_labels,
            rules=rules,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
            limit=limit,
            batch_size=batch_size,
        )
        result["execution"]["runtime_seconds"] = round(perf_counter() - started_at, 3)
        result["mode"]["pipeline_stage_metrics"] = selected_engine.get_pipeline_stage_metrics()

        _log_result_summary(self.logger, result)

        return result

    #
    # Target resolution and iteration
    #

    @staticmethod
    def _normalize_model_labels(source_models):
        """Return `(valid_labels, invalid_labels)` for selected source-model content types."""
        if not source_models:
            return set(), set()

        requested_labels = set()
        invalid_labels = set()

        for content_type in source_models:
            model_class = content_type.model_class()
            model_label = f"{content_type.app_label}.{content_type.model}"
            if model_class in SUPPORTED_SOURCE_MODELS:
                requested_labels.add(model_label)
                continue

            invalid_labels.add(model_label)

        return requested_labels, invalid_labels

    def _resolve_target_models(self, selected_rules, selected_model_labels):
        """Resolve which model labels should be scanned in bulk mode."""
        filtered_rules = self._get_rule_queryset(selected_rules, selected_model_labels)
        labels = {
            f"{rule.content_type.app_label}.{rule.content_type.model}"
            for rule in filtered_rules
            if f"{rule.content_type.app_label}.{rule.content_type.model}" in SUPPORTED_SOURCE_MODEL_MAP
        }
        return sorted(labels)

    @staticmethod
    def _get_rules_mismatched_to_source_models(selected_rules, selected_model_labels):
        """Return selected rules whose content type isn't in selected source-model labels."""
        if not selected_rules or not selected_model_labels:
            return []

        return [
            rule
            for rule in selected_rules
            if f"{rule.content_type.app_label}.{rule.content_type.model}" not in selected_model_labels
        ]

    def _get_rule_queryset(self, selected_rules, selected_model_labels):
        """Build enabled-rule queryset constrained by explicit rule/model filters."""
        queryset = DNSRule.objects.filter(enabled=True).select_related("content_type")

        if selected_rules:
            queryset = queryset.filter(pk__in=[rule.pk for rule in selected_rules])

        if selected_model_labels:
            conditions = Q()
            for model_label in selected_model_labels:
                app_label, model_name = model_label.split(".", maxsplit=1)
                conditions |= Q(content_type__app_label=app_label, content_type__model=model_name)
            queryset = queryset.filter(conditions)

        return queryset

    def _iter_targets(
        self,
        target_labels,
        batch_size,
        limit=None,
        location_ids=None,
        tenant_ids=None,
    ):
        """Yield `(model_label, object)` tuples for reconciliation."""
        remaining = limit
        location_ids = location_ids or set()
        tenant_ids = tenant_ids or set()
        for model_label in target_labels:
            if remaining is not None and remaining <= 0:
                break

            queryset = self._build_target_queryset(
                model_label,
                location_ids=location_ids,
                tenant_ids=tenant_ids,
            )

            if remaining is not None:
                queryset = queryset[:remaining]

            for obj in queryset.iterator(chunk_size=batch_size):
                yield model_label, obj
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        break

    def _build_target_queryset(self, model_label, *, location_ids, tenant_ids):
        """Build scoped and optimized queryset for one target model label."""
        model_class = SUPPORTED_SOURCE_MODEL_MAP[model_label]
        queryset = model_class.objects.order_by("pk")
        queryset = self._bulk_scope_filter_builder.apply(
            model_label,
            queryset,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        )
        queryset = self._apply_target_queryset_optimizations(model_label, queryset)

        return queryset

    @staticmethod
    def _apply_target_queryset_optimizations(model_label, queryset):
        """Apply model-specific queryset eager-loading optimizations."""
        if model_label == "dcim.device":
            return queryset.select_related("location", "tenant", "primary_ip4", "primary_ip6")

        if model_label == "dcim.interface":
            return queryset.select_related("device", "device__tenant", "device__location").prefetch_related(
                "ip_addresses"
            )

        if model_label == "virtualization.virtualmachine":
            return queryset.select_related(
                "cluster", "cluster__location", "cluster__tenant", "tenant", "primary_ip4", "primary_ip6"
            )

        if model_label == "virtualization.vminterface":
            return queryset.select_related(
                "virtual_machine",
                "virtual_machine__tenant",
                "virtual_machine__cluster",
                "virtual_machine__cluster__location",
                "virtual_machine__cluster__tenant",
            ).prefetch_related("ip_addresses")

        if model_label == "ipam.service":
            return queryset.select_related(
                "device",
                "device__location",
                "device__tenant",
                "virtual_machine",
                "virtual_machine__tenant",
                "virtual_machine__cluster",
                "virtual_machine__cluster__location",
                "virtual_machine__cluster__tenant",
            )

        return queryset

    #
    # Batch processing
    #

    def _process_pipeline_targets_in_batches(
        self,
        targets,
        *,
        summary,
        selected_engine,
        dryrun,
        limit,
        batch_size,
    ):
        """Process iterator of targets as full batches plus one trailing flush."""
        object_batch = []
        for model_label, obj in targets:
            if _limit_reached(summary, limit):
                break

            object_batch.append((model_label, obj))
            if len(object_batch) >= batch_size:
                self._process_pipeline_target_batch(
                    object_batch,
                    summary=summary,
                    selected_engine=selected_engine,
                    dryrun=dryrun,
                    limit=limit,
                )
                object_batch = []

        if object_batch and not _limit_reached(summary, limit):
            self._process_pipeline_target_batch(
                object_batch,
                summary=summary,
                selected_engine=selected_engine,
                dryrun=dryrun,
                limit=limit,
            )

    def _process_pipeline_target_batch(
        self,
        object_batch,
        *,
        summary,
        selected_engine,
        dryrun,
        limit,
    ):
        """Process one target batch using pipeline batch execution."""
        targets_in_scope = self._build_limited_target_list(
            object_batch,
            summary=summary,
            dryrun=dryrun,
            limit=limit,
        )

        if dryrun or not targets_in_scope:
            return

        targets_by_model_label = defaultdict(list)
        for model_label, obj in targets_in_scope:
            targets_by_model_label[model_label].append(obj)

        for model_label, model_objects in targets_by_model_label.items():
            try:
                batch_summaries = selected_engine.process_objects_pipeline(model_objects, created=False)
            except DNSRuleEngineIntegrityError:
                raise
            except (
                DNSRuleTemplateRenderedEmptyError,
                ValidationError,
                ValueError,
            ) as exc:
                for obj in model_objects:
                    summary.mark_processed_failure()
                    self.logger.error(
                        "reconcile failure target=%s:%s error=%s", model_label, obj.pk, exc, extra={"object": obj}
                    )
                continue

            for obj, processing_summary in zip(model_objects, batch_summaries):
                summary.mark_processed_success(processing_summary)

    def _build_limited_target_list(
        self,
        object_batch,
        *,
        summary,
        dryrun,
        limit,
    ):
        """Build list of objects from batch, enforcing limit and recording each target in summary."""
        targets_in_scope = []
        for model_label, obj in object_batch:
            if _limit_reached(summary, limit):
                break

            summary.mark_target_seen()
            targets_in_scope.append((model_label, obj))

            if dryrun:
                self.logger.info("dryrun target=%s:%s", model_label, obj.pk)

        return targets_in_scope


class ReconcileDNSObjectJob(Job):
    """Object-scoped reconciliation job with a simplified UI."""

    template_name = "nautobot_dns_models/reconcile_dns_object_job.html"

    class Meta:
        """Metadata for object-scoped job definition."""

        name = "Reconcile DNS Records (Object)"
        description = "Reconcile rule-driven DNS records for a single object"
        has_sensitive_variables = False

    dryrun = DryRunVar(description="Preview targets only; do not apply reconciliation updates.")
    object_model = ObjectVar(
        model=ContentType,
        query_params=get_content_type_query_params(),
        label="Object Model",
        required=True,
    )
    object_id = StringVar(
        required=True,
        label="Object UUID",
    )
    object_name = StringVar(
        required=False,
        default="",
        description="Display name of the selected object (button-launch context).",
        widget=widgets.HiddenInput,
    )
    include_children = BooleanVar(
        required=False,
        default=False,
        description="For parent models: also reconcile supported child objects.",
    )

    def run(  # pylint: disable=arguments-differ
        self,
        dryrun,
        object_model=None,
        object_id=None,
        object_name="",
        include_children=False,
    ):
        """Execute single-object DNS reconciliation."""
        started_at = perf_counter()
        del object_name  # Display-only field; not used in reconciliation logic.

        object_model_label = f"{object_model.app_label}.{object_model.model}"
        model_class = object_model.model_class()
        if model_class not in SUPPORTED_SOURCE_MODELS:
            self.fail(f"Unsupported object_model '{object_model_label}'.")
            return {}

        try:
            obj = model_class.objects.get(pk=object_id)
        except model_class.DoesNotExist:  # pylint: disable=protected-access
            self.fail(f"Object '{object_model_label}:{object_id}' was not found.")
            return {}

        targets = list(
            self._expand_object_with_children(
                object_model=object_model_label,
                obj=obj,
                include_children=bool(include_children),
            )
        )
        try:
            summary = self._process_targets(
                targets,
                dryrun=dryrun,
                limit=None,
                batch_size=100,
            )
        except DNSRuleEngineIntegrityError as exc:
            self.fail(str(exc))
            return {
                "dryrun": bool(dryrun),
                "error": "engine_integrity_error",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        summary.scanned_model_labels.update({model_label for model_label, _ in targets})

        result = _build_result_payload(
            summary,
            dryrun=bool(dryrun),
            single_object=True,
            include_children=bool(include_children),
            selected_model_labels=set(),
            rules=[],
            location_ids=set(),
            tenant_ids=set(),
            limit=None,
            batch_size=100,
        )
        result["execution"]["runtime_seconds"] = round(perf_counter() - started_at, 3)
        _log_result_summary(self.logger, result)

        return result

    #
    # Target expansion and processing
    #

    @staticmethod
    def _expand_object_with_children(object_model, obj, include_children=False):
        """Yield `(model_label, object)` targets for the source object and optional children."""
        yield object_model, obj

        if not include_children:
            return

        relation = SUPPORTED_PARENT_CHILD_MODEL_RELATIONS.get(object_model)
        if relation is None:
            return

        child_model_label, related_manager_name = relation
        child_manager = getattr(obj, related_manager_name, None)
        if child_manager is None:
            return

        for child_obj in child_manager.all():
            yield child_model_label, child_obj

    def _process_targets(self, targets, *, dryrun, limit, batch_size):
        """Process target iterator and return aggregated execution/reconciliation summary."""
        summary = ReconcileRunSummary()
        selected_engine = DNSRuleEngine()

        object_batch = []
        for model_label, obj in targets:
            if _limit_reached(summary, limit):
                break

            object_batch.append((model_label, obj))
            if len(object_batch) >= batch_size:
                self._process_target_batch(
                    object_batch,
                    summary=summary,
                    selected_engine=selected_engine,
                    dryrun=dryrun,
                    limit=limit,
                )
                object_batch = []

        if object_batch and not _limit_reached(summary, limit):
            self._process_target_batch(
                object_batch,
                summary=summary,
                selected_engine=selected_engine,
                dryrun=dryrun,
                limit=limit,
            )

        return summary

    def _process_target_batch(
        self,
        object_batch,
        *,
        summary,
        selected_engine,
        dryrun,
        limit,
    ):
        """Process one buffered target batch."""
        targets_in_scope = []
        for model_label, obj in object_batch:
            if _limit_reached(summary, limit):
                break

            summary.mark_target_seen()
            targets_in_scope.append((model_label, obj))

            if dryrun:
                self.logger.info("dryrun target=%s:%s", model_label, obj.pk)

        if dryrun or not targets_in_scope:
            return

        for model_label, obj in targets_in_scope:
            try:
                processing_summary = selected_engine.process_object(obj, created=False)
                summary.mark_processed_success(processing_summary)
            except DNSRuleEngineIntegrityError:
                raise
            except (DNSRuleTemplateRenderedEmptyError, ValidationError, ValueError) as exc:
                summary.mark_processed_failure()
                self.logger.error(
                    "reconcile failure target=%s:%s error=%s", model_label, obj.pk, exc, extra={"object": obj}
                )


jobs = (ReconcileDNSBulkJob, ReconcileDNSObjectJob)
register_jobs(*jobs)
