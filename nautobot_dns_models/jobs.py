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
from nautobot.dcim.models import Device, Interface, Location
from nautobot.ipam.models import Service
from nautobot.tenancy.models import Tenant
from nautobot.virtualization.models import VirtualMachine, VMInterface

from nautobot_dns_models.constants import SUPPORTED_SOURCE_MODELS
from nautobot_dns_models.exceptions import DNSRuleEngineIntegrityError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine import DNSRuleEngine
from nautobot_dns_models.rules.scope_filters import BulkScopeFilterBuilder
from nautobot_dns_models.source_model_support import get_supported_source_content_type_query_params

name = "DNS Reconciliation Jobs"  # pylint: disable=invalid-name


@dataclass
class ReconcileRunSummary:
    """Mutable accumulator for reconciliation execution and outcome counters."""

    scanned_model_labels: set[str] = field(default_factory=set)
    targets_selected_count: int = 0
    targets_processed_count: int = 0
    targets_succeeded_count: int = 0
    targets_failed_count: int = 0
    objects_with_existing_rule_records: int = 0
    existing_rule_record_count: int = 0
    objects_changed: int = 0
    changed_record_count: int = 0
    record_ops_create_count: int = 0
    record_ops_delete_count: int = 0
    record_ops_update_count: int = 0
    targets_noop_count: int = 0

    def mark_target_selected(self):
        """Increment count for selected targets encountered."""
        self.targets_selected_count += 1

    def mark_processed_failure(self):
        """Increment counters for a failed processing attempt."""
        self.targets_processed_count += 1
        self.targets_failed_count += 1

    def mark_processed_success(self, processing_summary):
        """Increment success counters and apply engine-provided reconciliation metrics."""
        self.targets_processed_count += 1
        self.targets_succeeded_count += 1

        if processing_summary.had_existing_rule_records:
            self.objects_with_existing_rule_records += 1
            self.existing_rule_record_count += processing_summary.existing_rule_record_count

        if processing_summary.changed_record_count > 0:
            self.objects_changed += 1
            self.changed_record_count += processing_summary.changed_record_count

        self.record_ops_create_count += processing_summary.record_ops_create_count
        self.record_ops_delete_count += processing_summary.record_ops_delete_count
        self.record_ops_update_count += processing_summary.record_ops_update_count

        if (
            processing_summary.changed_record_count == 0
            and processing_summary.record_ops_create_count == 0
            and processing_summary.record_ops_delete_count == 0
            and processing_summary.record_ops_update_count == 0
        ):
            self.targets_noop_count += 1

    def as_execution_dict(self):
        """Serialize execution counters for job result output."""
        return {
            "targets_selected_count": self.targets_selected_count,
            "targets_processed_count": self.targets_processed_count,
            "targets_succeeded_count": self.targets_succeeded_count,
            "targets_failed_count": self.targets_failed_count,
        }

    def as_reconciliation_dict(self):
        """Serialize reconciliation counters for job result output."""
        return {
            "objects_with_existing_rule_records": self.objects_with_existing_rule_records,
            "existing_rule_record_count": self.existing_rule_record_count,
            "objects_changed": self.objects_changed,
            "record_ops_create_count": self.record_ops_create_count,
            "record_ops_delete_count": self.record_ops_delete_count,
            "record_ops_update_count": self.record_ops_update_count,
            "record_ops_total_count": (
                self.record_ops_create_count + self.record_ops_delete_count + self.record_ops_update_count
            ),
            "changed_record_count": self.changed_record_count,
            "targets_noop_count": self.targets_noop_count,
        }


#
# Module-level helpers shared by both job classes.
#


def _limit_reached(summary, limit):
    """Return whether in-scope processing limit has been reached."""
    return bool(limit) and summary.targets_selected_count >= limit


def _model_label(model_class):
    """Return canonical lower-case model label for a model class."""
    return model_class._meta.label_lower


def _iter_child_devices(parent_device):
    """Return child devices installed under the parent device (deterministic order)."""
    return sorted(parent_device.get_children(), key=lambda child_device: (child_device.name, child_device.pk))


def _iter_device_include_children_targets(device, *, include_child_devices=False, include_interfaces=False):
    """Yield additional `(model_class, object)` targets for Device include-children expansion."""
    if not include_child_devices and not include_interfaces:
        return

    child_devices = _iter_child_devices(device)

    if include_child_devices:
        for child_device in child_devices:
            yield Device, child_device

    if not include_interfaces:
        return

    seen_interface_ids = set()
    devices_for_interface_expansion = [device]
    if include_child_devices:
        devices_for_interface_expansion.extend(child_devices)

    for device_in_tree in devices_for_interface_expansion:
        for interface in sorted(device_in_tree.all_interfaces, key=lambda interface: (interface.name, interface.pk)):
            if interface.pk in seen_interface_ids:
                continue
            seen_interface_ids.add(interface.pk)
            yield Interface, interface


def _expand_object_with_children_targets(
    object_model_class,
    obj,
    *,
    include_child_devices=False,
    include_interfaces=False,
):
    """Yield `(model_class, object)` targets for the source object and optional children."""
    yield object_model_class, obj

    if not include_child_devices and not include_interfaces:
        return

    if object_model_class is Device:
        for expanded_model_class, expanded_obj in _iter_device_include_children_targets(
            obj,
            include_child_devices=include_child_devices,
            include_interfaces=include_interfaces,
        ):
            yield expanded_model_class, expanded_obj
        return

    if not include_interfaces:
        return

    child_manager = getattr(obj, "interfaces", None)
    if child_manager is None:
        return

    child_model_class = child_manager.model
    for child_obj in child_manager.all():
        yield child_model_class, child_obj


def _build_result_payload(
    summary,
    *,
    dryrun,
    single_object,
    include_child_devices,
    include_interfaces,
    selected_model_classes,
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
            "include_child_devices": bool(include_child_devices),
            "include_interfaces": bool(include_interfaces),
        },
        "scope": {
            "scanned_models": sorted(summary.scanned_model_labels),
            "filters": {
                "source_models": sorted(_model_label(model_class) for model_class in selected_model_classes),
                "rule_ids": sorted(str(rule.pk) for rule in (rules or [])),
                "location_ids": sorted(str(location_id) for location_id in (location_ids or set())),
                "tenant_ids": sorted(str(tenant_id) for tenant_id in (tenant_ids or set())),
                "limit": limit,
                "batch_size": batch_size,
            },
        },
        "execution": summary.as_execution_dict(),
        "reconciliation": summary.as_reconciliation_dict(),
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
            "seen=%d processed=%d success=%d failure=%d "
            "objects_changed=%d record_ops(create=%d delete=%d update=%d total=%d) "
            "runtime_s=%.3f"
        ),
        "dryrun" if mode["dryrun"] else "apply",
        ",".join(result["scope"]["scanned_models"]) or "-",
        execution["targets_selected_count"],
        execution["targets_processed_count"],
        execution["targets_succeeded_count"],
        execution["targets_failed_count"],
        reconciliation["objects_changed"],
        reconciliation["record_ops_create_count"],
        reconciliation["record_ops_delete_count"],
        reconciliation["record_ops_update_count"],
        reconciliation["record_ops_total_count"],
        float(runtime_seconds) if runtime_seconds is not None else 0.0,
    )


class ReconcileDNSBulkJob(Job):
    """Reconcile DNS records for all or selected source objects in bulk mode."""

    template_name = "nautobot_dns_models/reconcile_dns_bulk_job.html"

    class Meta:
        """Metadata for job definition."""

        name = "Reconcile DNS Records (Bulk)"
        description = (
            "Reconcile rule-driven DNS records for all objects or a filtered subset of supported source models."
        )
        has_sensitive_variables = False

    _bulk_scope_filter_builder = BulkScopeFilterBuilder()

    source_models = MultiObjectVar(
        model=ContentType,
        query_params=get_supported_source_content_type_query_params(),
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
    include_child_devices = BooleanVar(
        required=False,
        default=False,
        description="Reconcile child devices in populated device bays.",
    )
    include_interfaces = BooleanVar(
        required=False,
        default=False,
        description="Reconcile interfaces.",
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
    dryrun = DryRunVar(description="Preview targets only; do not apply reconciliation updates.")

    def run(
        self,
        dryrun,
        source_models=None,
        rules=None,
        locations=None,
        tenants=None,
        include_child_devices=False,
        include_interfaces=False,
        limit=None,
        batch_size=500,
    ):  # pylint: disable=too-many-arguments,arguments-differ
        """Execute bulk DNS reconciliation."""
        started_at = perf_counter()

        selected_engine = DNSRuleEngine()

        location_ids = {location.id for location in (locations or [])}
        tenant_ids = {tenant.id for tenant in (tenants or [])}

        selected_model_classes, invalid_model_labels = self._normalize_model_classes(source_models)
        if invalid_model_labels:
            supported_model_labels = sorted(_model_label(model_class) for model_class in SUPPORTED_SOURCE_MODELS)
            self.fail(
                "Unsupported source_models: "
                f"{', '.join(sorted(invalid_model_labels))}. "
                f"Supported values: {', '.join(supported_model_labels)}"
            )
            return {
                "dryrun": bool(dryrun),
                "error": "invalid_source_models",
                "invalid_source_models": sorted(invalid_model_labels),
            }

        mismatched_rules = self._get_rules_mismatched_to_source_models(rules, selected_model_classes)
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
                "selected_source_models": sorted(_model_label(model_class) for model_class in selected_model_classes),
            }

        target_model_classes = self._resolve_target_models(
            selected_rules=rules, selected_model_classes=selected_model_classes
        )
        targets = self._iter_targets(
            target_models=target_model_classes,
            batch_size=batch_size,
            limit=limit,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
            include_child_devices=bool(include_child_devices),
            include_interfaces=bool(include_interfaces),
        )
        summary = ReconcileRunSummary()
        summary.scanned_model_labels.update(_model_label(model_class) for model_class in target_model_classes)

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
            include_child_devices=bool(include_child_devices),
            include_interfaces=bool(include_interfaces),
            selected_model_classes=selected_model_classes,
            rules=rules,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
            limit=limit,
            batch_size=batch_size,
        )
        result["execution"]["runtime_seconds"] = round(perf_counter() - started_at, 3)
        result["mode"]["pipeline_stage_metrics"] = selected_engine.get_pipeline_metrics()

        _log_result_summary(self.logger, result)

        return result

    #
    # Target resolution and iteration
    #

    @staticmethod
    def _normalize_model_classes(source_models):
        """Return `(valid_model_classes, invalid_labels)` for selected source-model content types."""
        if not source_models:
            return set(), set()

        selected_model_classes = set()
        invalid_labels = set()

        for content_type in source_models:
            model_class = content_type.model_class()
            model_label = f"{content_type.app_label}.{content_type.model}"
            if model_class in SUPPORTED_SOURCE_MODELS:
                selected_model_classes.add(model_class)
                continue

            invalid_labels.add(model_label)

        return selected_model_classes, invalid_labels

    def _resolve_target_models(self, selected_rules, selected_model_classes):
        """Resolve which model classes should be scanned in bulk mode."""
        filtered_rules = self._get_rule_queryset(selected_rules, selected_model_classes)

        model_classes = set()
        for rule in filtered_rules:
            model_class = rule.content_type.model_class()
            if model_class not in SUPPORTED_SOURCE_MODELS:
                continue
            model_classes.add(model_class)

        return sorted(model_classes, key=_model_label)

    @staticmethod
    def _get_rules_mismatched_to_source_models(selected_rules, selected_model_classes):
        """Return selected rules whose content type isn't in selected source-model classes."""
        if not selected_rules or not selected_model_classes:
            return []

        return [rule for rule in selected_rules if rule.content_type.model_class() not in selected_model_classes]

    def _get_rule_queryset(self, selected_rules, selected_model_classes):
        """Build enabled-rule queryset constrained by explicit rule/model filters."""
        queryset = DNSRule.objects.filter(enabled=True).select_related("content_type")

        if selected_rules:
            queryset = queryset.filter(pk__in=[rule.pk for rule in selected_rules])

        if selected_model_classes:
            conditions = Q()
            for model_class in selected_model_classes:
                conditions |= Q(
                    content_type__app_label=model_class._meta.app_label,
                    content_type__model=model_class._meta.model_name,
                )
            queryset = queryset.filter(conditions)

        return queryset

    def _iter_targets(
        self,
        target_models,
        batch_size,
        limit=None,
        location_ids=None,
        tenant_ids=None,
        include_child_devices=False,
        include_interfaces=False,
    ):
        """Iterate reconciliation targets across selected models.

        Args:
            target_models (Iterable[type]): Source model classes to scan.
            batch_size (int): Chunk size used for queryset iterator() pagination.
            limit (int | None): Optional cap on total yielded objects.
            location_ids (set | None): Optional source-object location IDs to scope by.
            tenant_ids (set | None): Optional source-object tenant IDs to scope by.
            include_child_devices (bool): Expand Device targets to include child devices.
            include_interfaces (bool): Expand parent targets to include interface children.

        Yields:
            tuple[type, object]: `(model_class, obj)` for each in-scope target object.
        """
        remaining = limit
        location_ids = location_ids or set()
        tenant_ids = tenant_ids or set()
        seen_targets = set()
        for model_class in target_models:
            if remaining is not None and remaining <= 0:
                break

            queryset = self._build_target_queryset(
                model_class,
                location_ids=location_ids,
                tenant_ids=tenant_ids,
            )

            if remaining is not None and not (include_child_devices or include_interfaces):
                queryset = queryset[:remaining]

            for obj in queryset.iterator(chunk_size=batch_size):
                if include_child_devices or include_interfaces:
                    expanded_targets = _expand_object_with_children_targets(
                        object_model_class=model_class,
                        obj=obj,
                        include_child_devices=include_child_devices,
                        include_interfaces=include_interfaces,
                    )
                else:
                    expanded_targets = ((model_class, obj),)

                for expanded_model_class, expanded_obj in expanded_targets:
                    target_key = (expanded_model_class, expanded_obj.pk)
                    if target_key in seen_targets:
                        continue

                    seen_targets.add(target_key)
                    yield expanded_model_class, expanded_obj
                    if remaining is not None:
                        remaining -= 1
                        if remaining <= 0:
                            break

                if remaining is not None and remaining <= 0:
                    break

    def _build_target_queryset(self, model_class, *, location_ids, tenant_ids):
        """Build scoped and optimized queryset for one target model class."""
        queryset = model_class.objects.order_by("pk")
        queryset = self._bulk_scope_filter_builder.apply(
            model_class,
            queryset,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        )
        queryset = self._apply_target_queryset_optimizations(model_class, queryset)

        return queryset

    @staticmethod
    def _apply_target_queryset_optimizations(model_class, queryset):
        """Apply model-specific queryset eager-loading optimizations."""
        if model_class is Device:
            return queryset.select_related("location", "tenant", "primary_ip4", "primary_ip6")

        if model_class is Interface:
            return queryset.select_related("device", "device__tenant", "device__location").prefetch_related(
                "ip_addresses"
            )

        if model_class is VirtualMachine:
            return queryset.select_related(
                "cluster", "cluster__location", "cluster__tenant", "tenant", "primary_ip4", "primary_ip6"
            )

        if model_class is VMInterface:
            return queryset.select_related(
                "virtual_machine",
                "virtual_machine__tenant",
                "virtual_machine__cluster",
                "virtual_machine__cluster__location",
                "virtual_machine__cluster__tenant",
            ).prefetch_related("ip_addresses")

        if model_class is Service:
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
        for model_class, obj in targets:
            if _limit_reached(summary, limit):
                break

            object_batch.append((model_class, obj))
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

        targets_by_model_class = defaultdict(list)
        for model_class, obj in targets_in_scope:
            targets_by_model_class[model_class].append(obj)

        for model_class, model_objects in targets_by_model_class.items():
            model_label = _model_label(model_class)
            try:
                batch_summaries = selected_engine.process_objects_pipeline(model_objects)
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
        for model_class, obj in object_batch:
            if _limit_reached(summary, limit):
                break

            summary.mark_target_selected()
            summary.scanned_model_labels.add(_model_label(model_class))
            targets_in_scope.append((model_class, obj))

            if dryrun:
                model_label = _model_label(model_class)
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
        hidden = True

    object_model = ObjectVar(
        model=ContentType,
        query_params=get_supported_source_content_type_query_params(),
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
    object_has_populated_device_bays = BooleanVar(
        required=False,
        default=False,
        description="Display-only UI hint indicating whether selected Device has child devices.",
        widget=widgets.HiddenInput,
    )
    include_child_devices = BooleanVar(
        required=False,
        default=False,
        description="Reconcile child devices in populated device bays.",
    )
    include_interfaces = BooleanVar(
        required=False,
        default=False,
        description="Reconcile interfaces.",
    )
    dryrun = DryRunVar(description="Preview targets only; do not apply reconciliation updates.")

    def run(  # pylint: disable=arguments-differ
        self,
        dryrun,
        object_model=None,
        object_id=None,
        object_name="",
        object_has_populated_device_bays=False,  # noqa: ARG002 - display-only hidden form value
        include_child_devices=False,
        include_interfaces=False,
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
                object_model_class=model_class,
                obj=obj,
                include_child_devices=bool(include_child_devices),
                include_interfaces=bool(include_interfaces),
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
        summary.scanned_model_labels.update({_model_label(model_class) for model_class, _ in targets})

        result = _build_result_payload(
            summary,
            dryrun=bool(dryrun),
            single_object=True,
            include_child_devices=bool(include_child_devices),
            include_interfaces=bool(include_interfaces),
            selected_model_classes=set(),
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
    def _expand_object_with_children(object_model_class, obj, *, include_child_devices=False, include_interfaces=False):
        """Yield `(model_class, object)` targets for the source object and optional children."""
        yield from _expand_object_with_children_targets(
            object_model_class=object_model_class,
            obj=obj,
            include_child_devices=include_child_devices,
            include_interfaces=include_interfaces,
        )

    def _process_targets(self, targets, *, dryrun, limit, batch_size):
        """Process target iterator and return aggregated execution/reconciliation summary."""
        summary = ReconcileRunSummary()
        selected_engine = DNSRuleEngine()

        object_batch = []
        for model_class, obj in targets:
            if _limit_reached(summary, limit):
                break

            object_batch.append((model_class, obj))
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
        for model_class, obj in object_batch:
            if _limit_reached(summary, limit):
                break

            summary.mark_target_selected()
            targets_in_scope.append((model_class, obj))

            if dryrun:
                model_label = _model_label(model_class)
                self.logger.info("dryrun target=%s:%s", model_label, obj.pk)

        if dryrun or not targets_in_scope:
            return

        for model_class, obj in targets_in_scope:
            model_label = _model_label(model_class)
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
