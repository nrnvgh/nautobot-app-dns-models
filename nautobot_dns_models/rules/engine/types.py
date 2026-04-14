"""Typed internal payloads for the DNS rule engine pipeline."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class BatchedCreateState:
    """Mutable state shared by pipeline and writer for batched creates."""

    pending_by_record_class: dict = field(default_factory=lambda: defaultdict(list))
    active: bool = False


@dataclass
class FetchTrackingDataResult:
    """Stage 1 output: fetched tracking rows and object-id index."""

    tracking_rows: list
    tracking_by_object_id: dict


@dataclass
class RuleWorkItem:
    """Deferred per-rule materialization work entry."""

    object_id: object
    rule: object
    base_context: dict
    record_variations: list
    requires_ip_context: bool


@dataclass
class PreparedReconcileEntry:
    """Prepared per-object reconcile state that survives stage boundaries."""

    source_obj: object
    rules: list
    needed_rule_ids: set = field(default_factory=set)
    desired_by_rule_id: dict = field(default_factory=dict)
    failed_rule_ids: set = field(default_factory=set)
    tracking_rows: list = field(default_factory=list)


@dataclass
class PlanWorkResult:
    """Stage 2 output: prepared entries plus deferred materialization work."""

    prepared_entries: list
    prepared_entry_by_object_id: dict
    rule_work_items: dict
    batch_address_ids: set
    pending_rule_calculations: int


@dataclass
class ApplyChangesResult:
    """Stage 4 output: per-object summaries and queued rename updates."""

    summaries: list
    pending_rename_updates: dict
