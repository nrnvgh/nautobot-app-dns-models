"""Jobs for DNS reconciliation workflows."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.forms import widgets
from nautobot.apps.forms import add_blank_choice, StaticSelect2, StaticSelect2Multiple
from django.db.models import Q
from nautobot.apps.jobs import (
    BooleanVar,
    ChoiceVar,
    DryRunVar,
    IntegerVar,
    Job,
    MultiChoiceVar,
    MultiObjectVar,
    StringVar,
    register_jobs,
)
from nautobot.dcim.models import Location
from nautobot.tenancy.models import Tenant

from nautobot_dns_models.constants.supported_models import (
    SUPPORTED_PARENT_CHILD_MODEL_RELATIONS,
    SUPPORTED_SOURCE_MODEL_CHOICES,
    SUPPORTED_SOURCE_MODEL_MAP,
)
from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine_selector import get_experimental_pipeline_engine, get_rule_engine

name = "DNS reconciliation jobs"


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

    def mark_scope_skipped(self) -> None:
        """Increment count for targets skipped by location/tenant scope filters."""
        self.skipped_scope_count += 1

    def mark_target_seen(self) -> None:
        """Increment count for in-scope targets encountered."""
        self.targets_seen += 1

    def mark_processed_failure(self) -> None:
        """Increment counters for a failed processing attempt."""
        self.processed_count += 1
        self.failure_count += 1

    def mark_processed_success(self, processing_summary: dict) -> None:
        """Increment success counters and apply engine-provided reconciliation metrics."""
        self.processed_count += 1
        self.success_count += 1

        if processing_summary.get("had_existing_rule_records"):
            self.objects_with_existing_rule_records += 1
            self.existing_rule_record_count += int(processing_summary.get("existing_rule_record_count", 0))

        object_changed_record_count = int(processing_summary.get("changed_record_count", 0))
        if object_changed_record_count > 0:
            self.objects_changed += 1
            self.changed_record_count += object_changed_record_count

        self.record_ops_create_count += int(processing_summary.get("record_ops_create_count", 0))
        self.record_ops_delete_count += int(processing_summary.get("record_ops_delete_count", 0))

    def as_execution_dict(self) -> dict[str, int]:
        """Serialize execution counters for job result output."""
        return {
            "targets_seen": self.targets_seen,
            "processed_count": self.processed_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_scope_count": self.skipped_scope_count,
        }

    def as_reconciliation_dict(self) -> dict[str, int]:
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


class _BaseReconcileDNSJob(Job):
    """Shared reconciliation helpers for bulk and object jobs."""

    dryrun = DryRunVar(description="Preview targets only; do not apply reconciliation updates.")
    performance_mode = ChoiceVar(
        choices=(
            ("safe", "Safe (default semantics)"),
            ("fast", "Fast (reduced safeguards)"),
            ("experimental", "Experimental (safe baseline)"),
        ),
        default="safe",
        required=False,
        description=(
            "Execution mode for reconciliation internals. "
            "'safe' preserves normal model save semantics; "
            "'fast' uses performance-oriented shortcuts; "
            "'experimental' starts from safe semantics for isolated testing."
        ),
    )

    @staticmethod
    def _normalize_model_labels(source_models) -> tuple[set[str], set[str]]:
        """Return `(valid_labels, invalid_labels)` for selected source-model labels."""
        if not source_models:
            return set(), set()

        requested_labels = set(source_models)
        valid_labels = requested_labels & set(SUPPORTED_SOURCE_MODEL_MAP.keys())
        invalid_labels = requested_labels - valid_labels
        return valid_labels, invalid_labels

    @staticmethod
    def _normalize_performance_mode(performance_mode: str | None) -> str:
        """Normalize performance mode input to supported values."""
        mode = (performance_mode or "safe").strip().lower()
        if mode not in {"safe", "fast", "experimental"}:
            return "safe"
        return mode

    def _get_rule_queryset(self, selected_rules, selected_model_labels: set[str]):
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

    def _resolve_target_models(self, selected_rules, selected_model_labels: set[str]) -> list[str]:
        """Resolve which model labels should be scanned in bulk mode."""
        filtered_rules = self._get_rule_queryset(selected_rules, selected_model_labels)
        labels = {
            f"{rule.content_type.app_label}.{rule.content_type.model}"
            for rule in filtered_rules
            if f"{rule.content_type.app_label}.{rule.content_type.model}" in SUPPORTED_SOURCE_MODEL_MAP
        }
        return sorted(labels)

    def _iter_targets(
        self,
        target_labels: list[str],
        batch_size: int,
    ):
        """Yield `(model_label, object)` pairs for reconciliation."""
        for model_label in target_labels:
            model_class = SUPPORTED_SOURCE_MODEL_MAP[model_label]
            queryset = model_class.objects.order_by("pk")
            if model_label == "dcim.interface":
                # Fast-path bulk runs repeatedly dereference device tenant/location.
                # Load them in the base interface query to reduce per-object SQL chatter.
                queryset = queryset.select_related("device", "device__tenant", "device__location").prefetch_related(
                    "ip_addresses"
                )
            for obj in queryset.iterator(chunk_size=batch_size):
                yield model_label, obj

    @staticmethod
    def _iter_single_object_targets(object_model, obj, include_children=False):
        """Yield `(model_label, object)` targets for single-object mode."""
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

    @staticmethod
    def _build_result_payload(
        summary: ReconcileRunSummary,
        *,
        dryrun: bool,
        performance_mode: str,
        single_object: bool,
        include_children: bool,
        selected_model_labels: set[str],
        rules=None,
        location_ids=None,
        tenant_ids=None,
        limit=None,
        batch_size=100,
    ) -> dict:
        """Build structured job result payload from run context and accumulated counters."""
        return {
            "schema_version": 1,
            "mode": {
                "dryrun": bool(dryrun),
                "performance_mode": performance_mode,
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

    def _process_targets(
        self, targets, *, dryrun, performance_mode, location_ids, tenant_ids, limit, batch_size
    ) -> ReconcileRunSummary:
        """Process target iterator and return aggregated execution/reconciliation summary."""
        summary = ReconcileRunSummary()
        selected_engine = get_rule_engine(performance_mode)
        selected_engine.reset_runtime_caches()

        buffered_targets = []
        for model_label, obj in targets:
            buffered_targets.append((model_label, obj))
            if len(buffered_targets) >= batch_size:
                self._process_target_batch(
                    buffered_targets,
                    summary=summary,
                    selected_engine=selected_engine,
                    dryrun=dryrun,
                    performance_mode=performance_mode,
                    location_ids=location_ids,
                    tenant_ids=tenant_ids,
                    limit=limit,
                )
                buffered_targets = []
            if limit and summary.targets_seen >= limit:
                break

        if buffered_targets and (not limit or summary.targets_seen < limit):
            self._process_target_batch(
                buffered_targets,
                summary=summary,
                selected_engine=selected_engine,
                dryrun=dryrun,
                performance_mode=performance_mode,
                location_ids=location_ids,
                tenant_ids=tenant_ids,
                limit=limit,
            )

        return summary

    def _process_target_batch(
        self,
        buffered_targets,
        *,
        summary: ReconcileRunSummary,
        selected_engine,
        dryrun,
        performance_mode,
        location_ids,
        tenant_ids,
        limit,
    ) -> None:
        """Process one buffered target batch."""
        if performance_mode == "fast":
            interface_objects = [obj for model_label, obj in buffered_targets if model_label == "dcim.interface"]
            if interface_objects:
                selected_engine.preload_tracking_records_for_objects(interface_objects)

        in_scope_targets = []
        for model_label, obj in buffered_targets:
            if limit and summary.targets_seen >= limit:
                break

            if location_ids:
                object_location = selected_engine._get_object_location(obj)  # pylint: disable=protected-access
                if object_location is None or object_location.id not in location_ids:
                    summary.mark_scope_skipped()
                    continue

            if tenant_ids:
                object_tenant = selected_engine._get_object_tenant(obj)  # pylint: disable=protected-access
                if object_tenant is None or object_tenant.id not in tenant_ids:
                    summary.mark_scope_skipped()
                    continue

            summary.mark_target_seen()
            in_scope_targets.append((model_label, obj))

            if dryrun:
                self.logger.info("dryrun target=%s:%s", model_label, obj.pk)
        if dryrun or not in_scope_targets:
            return

        if performance_mode == "experimental" and hasattr(selected_engine, "process_objects_batch"):
            targets_by_model_label = {}
            for model_label, obj in in_scope_targets:
                targets_by_model_label.setdefault(model_label, []).append(obj)

            for model_label, model_objects in targets_by_model_label.items():
                batch_summaries = selected_engine.process_objects_batch(model_objects, created=False)
                for obj, processing_summary in zip(model_objects, batch_summaries):
                    if processing_summary.get("_batch_failed"):
                        summary.mark_processed_failure()
                        self.logger.error(
                            "reconcile failure target=%s:%s error=%s",
                            model_label,
                            obj.pk,
                            processing_summary.get("_batch_error"),
                            extra={"object": obj},
                        )
                        continue
                    summary.mark_processed_success(processing_summary)
            return

        for model_label, obj in in_scope_targets:
            try:
                processing_summary = selected_engine.process_object(obj, created=False)
                summary.mark_processed_success(processing_summary)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                summary.mark_processed_failure()
                self.logger.error("reconcile failure target=%s:%s error=%s", model_label, obj.pk, exc, extra={"object": obj})

    def _log_result_summary(self, result) -> None:
        """Emit standard reconciliation summary log line."""
        execution = result["execution"]
        reconciliation = result["reconciliation"]
        mode = result["mode"]
        self.logger.info(
            (
                "Reconciliation results: "
                "mode=%s "
                "models=[%s] "
                "seen=%d processed=%d success=%d failure=%d skipped_scope=%d "
                "objects_changed=%d record_ops(create=%d delete=%d total=%d)"
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
        )


class ReconcileDNSBulkJob(_BaseReconcileDNSJob):
    """Reconcile DNS records for all or selected source objects in bulk mode."""

    class Meta:
        """Metadata for job definition."""

        name = "Reconcile DNS Records (Bulk)"
        description = "Reconcile rule-driven DNS records for all objects or a filtered subset of supported source models."
        has_sensitive_variables = False

    source_models = MultiChoiceVar(
        choices=SUPPORTED_SOURCE_MODEL_CHOICES,
        required=False,
        description="Optional source model filter for bulk runs.",
        widget=StaticSelect2Multiple(),
    )
    rules = MultiObjectVar(
        model=DNSRule,
        required=False,
        description="Optional rule filter; defaults to all enabled rules.",
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
        default=100,
        min_value=1,
        max_value=2000,
        description="Bulk queryset iterator chunk size.",
    )

    def run(
        self,
        dryrun,
        performance_mode="safe",
        source_models=None,
        rules=None,
        locations=None,
        tenants=None,
        limit=None,
        batch_size=100,
    ):  # pylint: disable=too-many-arguments,arguments-differ
        """Execute bulk DNS reconciliation."""
        performance_mode = self._normalize_performance_mode(performance_mode)
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

        target_labels = self._resolve_target_models(selected_rules=rules, selected_model_labels=selected_model_labels)
        targets = self._iter_targets(target_labels=target_labels, batch_size=batch_size)
        summary = self._process_targets(
            targets,
            dryrun=dryrun,
            performance_mode=performance_mode,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
            limit=limit,
            batch_size=batch_size,
        )
        summary.scanned_model_labels.update(target_labels)

        result = self._build_result_payload(
            summary,
            dryrun=bool(dryrun),
            performance_mode=performance_mode,
            single_object=False,
            include_children=False,
            selected_model_labels=selected_model_labels,
            rules=rules,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
            limit=limit,
            batch_size=batch_size,
        )
        self._log_result_summary(result)
        return result


class ReconcileDNSObjectJob(_BaseReconcileDNSJob):
    """Object-scoped reconciliation job with a simplified UI."""

    template_name = "nautobot_dns_models/reconcile_dns_object_job.html"

    class Meta:
        """Metadata for object-scoped job definition."""

        name = "Reconcile DNS Records (Object)"
        description = "Reconcile rule-driven DNS records for a single object"
        has_sensitive_variables = False

    # Keep only object-scoped selectors in the form.
    object_model = ChoiceVar(
        choices=add_blank_choice(SUPPORTED_SOURCE_MODEL_CHOICES),
        required=True,
        description="Object model label (for example dcim.device).",
        widget=StaticSelect2(),
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
        self, dryrun, performance_mode="safe", object_model=None, object_id=None, object_name="", include_children=False
    ):
        """Execute single-object DNS reconciliation."""
        performance_mode = self._normalize_performance_mode(performance_mode)
        del object_name  # Display-only field; not used in reconciliation logic.
        model_class = SUPPORTED_SOURCE_MODEL_MAP.get(object_model)
        if model_class is None:
            self.fail(f"Unsupported object_model '{object_model}'.")
            return {}

        try:
            obj = model_class.objects.get(pk=object_id)
        except model_class.DoesNotExist:  # pylint: disable=protected-access
            self.fail(f"Object '{object_model}:{object_id}' was not found.")
            return {}

        targets = list(
            self._iter_single_object_targets(
                object_model=object_model,
                obj=obj,
                include_children=bool(include_children),
            )
        )
        summary = self._process_targets(
            targets,
            dryrun=dryrun,
            performance_mode=performance_mode,
            location_ids=set(),
            tenant_ids=set(),
            limit=None,
            batch_size=100,
        )
        summary.scanned_model_labels.update({model_label for model_label, _ in targets})

        result = self._build_result_payload(
            summary,
            dryrun=bool(dryrun),
            performance_mode=performance_mode,
            single_object=True,
            include_children=bool(include_children),
            selected_model_labels=set(),
            rules=[],
            location_ids=set(),
            tenant_ids=set(),
            limit=None,
            batch_size=100,
        )
        self._log_result_summary(result)
        return result


class ReconcileDNSBulkPipelineExperimentalJob(_BaseReconcileDNSJob):
    """Experimental bulk job using batch-native fetch/render/delta/execute pipeline."""

    class Meta:
        """Metadata for experimental pipeline job definition."""

        name = "Reconcile DNS Records (Bulk, Experimental Pipeline)"
        description = (
            "Experimental batch-native reconciliation: batch fetch, render, delta computation, and grouped execution."
        )
        has_sensitive_variables = False

    source_models = MultiChoiceVar(
        choices=SUPPORTED_SOURCE_MODEL_CHOICES,
        required=False,
        description="Optional source model filter for bulk runs.",
        widget=StaticSelect2Multiple(),
    )
    rules = MultiObjectVar(
        model=DNSRule,
        required=False,
        description="Optional rule filter; defaults to all enabled rules.",
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
        performance_mode="experimental",
        source_models=None,
        rules=None,
        locations=None,
        tenants=None,
        limit=None,
        batch_size=500,
    ):  # pylint: disable=too-many-arguments,arguments-differ
        """Execute experimental batch-native DNS reconciliation."""
        del performance_mode
        performance_mode = "experimental"
        selected_engine = get_experimental_pipeline_engine()
        selected_engine.reset_runtime_caches()

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

        target_labels = self._resolve_target_models(selected_rules=rules, selected_model_labels=selected_model_labels)
        targets = self._iter_targets(target_labels=target_labels, batch_size=batch_size)
        summary = ReconcileRunSummary()
        summary.scanned_model_labels.update(target_labels)

        buffered_targets = []
        for model_label, obj in targets:
            buffered_targets.append((model_label, obj))
            if len(buffered_targets) >= batch_size:
                self._process_pipeline_target_batch(
                    buffered_targets,
                    summary=summary,
                    selected_engine=selected_engine,
                    dryrun=dryrun,
                    location_ids=location_ids,
                    tenant_ids=tenant_ids,
                    limit=limit,
                )
                buffered_targets = []
            if limit and summary.targets_seen >= limit:
                break

        if buffered_targets and (not limit or summary.targets_seen < limit):
            self._process_pipeline_target_batch(
                buffered_targets,
                summary=summary,
                selected_engine=selected_engine,
                dryrun=dryrun,
                location_ids=location_ids,
                tenant_ids=tenant_ids,
                limit=limit,
            )

        result = self._build_result_payload(
            summary,
            dryrun=bool(dryrun),
            performance_mode=performance_mode,
            single_object=False,
            include_children=False,
            selected_model_labels=selected_model_labels,
            rules=rules,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
            limit=limit,
            batch_size=batch_size,
        )
        self._log_result_summary(result)
        return result

    def _process_pipeline_target_batch(
        self,
        buffered_targets,
        *,
        summary: ReconcileRunSummary,
        selected_engine,
        dryrun,
        location_ids,
        tenant_ids,
        limit,
    ) -> None:
        """Process one buffered target batch via experimental pipeline engine."""
        in_scope_targets = []
        for model_label, obj in buffered_targets:
            if limit and summary.targets_seen >= limit:
                break

            if location_ids:
                object_location = selected_engine._get_object_location(obj)  # pylint: disable=protected-access
                if object_location is None or object_location.id not in location_ids:
                    summary.mark_scope_skipped()
                    continue

            if tenant_ids:
                object_tenant = selected_engine._get_object_tenant(obj)  # pylint: disable=protected-access
                if object_tenant is None or object_tenant.id not in tenant_ids:
                    summary.mark_scope_skipped()
                    continue

            summary.mark_target_seen()
            in_scope_targets.append((model_label, obj))

            if dryrun:
                self.logger.info("dryrun target=%s:%s", model_label, obj.pk)

        if dryrun or not in_scope_targets:
            return

        targets_by_model_label = {}
        for model_label, obj in in_scope_targets:
            targets_by_model_label.setdefault(model_label, []).append(obj)

        for model_label, model_objects in targets_by_model_label.items():
            try:
                batch_summaries = selected_engine.process_objects_pipeline(model_objects, created=False)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                for obj in model_objects:
                    summary.mark_processed_failure()
                    self.logger.error("reconcile failure target=%s:%s error=%s", model_label, obj.pk, exc, extra={"object": obj})
                continue

            for obj, processing_summary in zip(model_objects, batch_summaries):
                if processing_summary.get("_batch_failed"):
                    summary.mark_processed_failure()
                    self.logger.error(
                        "reconcile failure target=%s:%s error=%s",
                        model_label,
                        obj.pk,
                        processing_summary.get("_batch_error"),
                        extra={"object": obj},
                    )
                    continue
                summary.mark_processed_success(processing_summary)


jobs = (ReconcileDNSBulkJob, ReconcileDNSObjectJob, ReconcileDNSBulkPipelineExperimentalJob)
register_jobs(*jobs)
