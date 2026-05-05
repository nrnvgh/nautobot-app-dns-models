"""Typed internal payloads for the DNS rule engine pipeline."""

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum

from nautobot_dns_models.rules.engine.enums import EnginePhase, EngineReason


@dataclass
class BatchedCreateState:
    """Mutable state shared by pipeline and writer for batched creates.

    Attributes:
        pending_by_record_class: Mapping of DNS record model class to queued
            create rows waiting for bulk flush.
        active: Whether the current pipeline batch is in batched-create mode.
        create_failures_recorded: Whether any create-path failure was recorded
            in this engine lifetime, used to decide if cleanup probes are needed.
    """

    pending_by_record_class: dict = field(default_factory=lambda: defaultdict(list))
    active: bool = False
    # Avoids unnecessary failure-state cleanup probes in happy-path create runs.
    create_failures_recorded: bool = False

    @contextmanager
    def activate(self):
        """Enable batched-create mode for the duration of a context manager."""
        self.pending_by_record_class.clear()
        self.active = True

        try:
            yield
        finally:
            self.active = False
            self.pending_by_record_class.clear()


class RulePlanningStatus(str, Enum):
    """Typed status for per-rule planning outcomes."""

    NOT_NEEDED = "not_needed"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class RuleFailureInfo:
    """Structured planning/materialization failure classification."""

    reason_code: EngineReason
    phase: EnginePhase
    message: str | None = None


@dataclass
class FetchTrackingDataResult:
    """Stage 1 output: fetched tracking rows and object-id index.

    Attributes:
        tracking_rows: Flat list of fetched `DNSRuleRecord` rows for the batch.
        tracking_by_object_id: Mapping of source object id to its tracking rows.
    """

    tracking_rows: list
    tracking_by_object_id: dict


@dataclass
class RuleWorkItem:
    """Deferred per-rule materialization work entry.

    Attributes:
        object_id: Source object primary key this work item belongs to.
        rule: DNS rule to materialize for the source object.
        base_context: Shared template context for this object/rule.
        record_variations: Candidate record variations before zone expansion.
        requires_ip_context: Whether each variation requires preloaded IP context.
    """

    object_id: object
    rule: object
    base_context: dict
    record_variations: list
    # Skips per-record IP-context construction when rule rendering does not need it.
    requires_ip_context: bool


@dataclass(frozen=True)
class RulePlanningOutcome:
    """Planning result for a single object/rule pair."""

    status: RulePlanningStatus
    work_item: RuleWorkItem | None = None
    failure: RuleFailureInfo | None = None


@dataclass
class PreparedReconcileEntry:
    """Prepared per-object reconcile state that survives stage boundaries.

    Attributes:
        source_obj: Source object being reconciled.
        rules: Applicable DNS rules selected for this object.
        needed_rule_ids: Rule ids that need candidate generation or reconciliation.
        desired_by_rule_id: Desired record payloads keyed by rule id.
        failed_rule_ids: Rule ids that failed during planning/materialization.
        tracking_rows: Existing `DNSRuleRecord` rows for the source object.
    """

    source_obj: object
    rules: list
    needed_rule_ids: set = field(default_factory=set)
    desired_by_rule_id: dict = field(default_factory=dict)
    failed_rule_ids: set = field(default_factory=set)
    failed_rule_by_id: dict = field(default_factory=dict)
    tracking_rows: list = field(default_factory=list)

    def mark_rule_needed(self, rule_id):
        """Mark a rule as needed for reconciliation work."""
        self.needed_rule_ids.add(rule_id)

    def mark_rule_failed(self, rule_id, *, failure=None):
        """Mark a rule as failed and clear any desired records for it."""
        self.needed_rule_ids.add(rule_id)
        self.failed_rule_ids.add(rule_id)
        if failure is not None:
            self.failed_rule_by_id[rule_id] = failure

        self.desired_by_rule_id.pop(rule_id, None)

    def set_desired_records(self, rule_id, records):
        """Set desired records for one non-failed, needed rule."""
        if rule_id not in self.needed_rule_ids:
            raise ValueError(f"Rule id {rule_id} is not marked as needed.")

        if rule_id in self.failed_rule_ids:
            raise ValueError(f"Rule id {rule_id} is marked as failed.")

        self.desired_by_rule_id[rule_id] = records

    def has_failed_rule(self, rule_id):
        """Return whether rule id is in failed state."""
        return rule_id in self.failed_rule_ids


@dataclass
class PlanWorkResult:
    """Stage 2 output: prepared entries plus deferred materialization work.

    Attributes:
        prepared_entries: Ordered per-object entries passed to apply stage.
        prepared_entry_by_object_id: Lookup map for prepared entries by object id.
        rule_work_items: Deferred work items keyed by rule id.
        batch_address_ids: Distinct IP address ids needed for materialization.
        pending_rule_work_items: Count of deferred rule work items queued.
    """

    prepared_entries: list
    # Avoids repeated scans by object id during materialization stage.
    prepared_entry_by_object_id: dict
    rule_work_items: dict
    # Enables one batched IP preload (`in_bulk`) instead of per-record lookups.
    batch_address_ids: set
    # Observability counter for queued per-rule work items per batch.
    pending_rule_work_items: int


@dataclass
class ApplyChangesResult:
    """Stage 4 output: per-object summaries and queued rename updates.

    Attributes:
        summaries: Per-object reconciliation summaries in batch order.
        pending_rename_updates: Pending fast-mode rename updates keyed by model.
        create_flush_result: Per-object create outcomes from batched-create flush.
    """

    summaries: list
    pending_rename_updates: dict
    create_flush_result: object
