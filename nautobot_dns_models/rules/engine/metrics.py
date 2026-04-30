"""Metrics dataclasses for DNS rule engine processing."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class ObjectProcessingMetrics:
    """Per-object result returned by the engine's processing paths.

    Attributes:
        had_existing_rule_records: True when the source object had at least one
            pre-existing `DNSRuleRecord` before reconciliation.
        existing_rule_record_count: Number of pre-existing `DNSRuleRecord` rows
            found for the source object at processing start.
        changed_record_count: Total number of create, delete, and update
            operations applied for the source object.
        dns_record_create_count: Number of DNS records created for the source
            object during reconciliation.
        dns_record_delete_count: Number of DNS records deleted for the source
            object during reconciliation.
        dns_record_update_count: Number of DNS records updated in place for the
            source object during reconciliation.
        dns_record_unchanged_count: Number of existing DNS records evaluated
            and left unchanged for the source object.
    """

    had_existing_rule_records: bool = False
    existing_rule_record_count: int = 0
    changed_record_count: int = 0
    dns_record_create_count: int = 0
    dns_record_delete_count: int = 0
    dns_record_update_count: int = 0
    dns_record_unchanged_count: int = 0


@dataclass
class PipelineStageMetrics:
    """Accumulate elapsed seconds for each pipeline stage.

    Attributes:
        fetch: Cumulative seconds spent loading tracking rows and related DNS
            record objects.
        planning: Cumulative seconds spent resolving rules and materializing
            desired candidate data.
        apply: Cumulative seconds spent reconciling desired vs existing state
            and queueing writes.
        bulk_flush: Cumulative seconds spent flushing queued bulk updates.
        total: End-to-end cumulative seconds spent across complete pipeline
            batch executions.
    """

    fetch: float = 0.0
    planning: float = 0.0
    apply: float = 0.0
    bulk_flush: float = 0.0
    total: float = 0.0

    def add(self, stage_name, seconds):
        """Add elapsed seconds to one named stage."""
        if not hasattr(self, stage_name):
            raise ValueError(f"Unknown pipeline stage '{stage_name}'.")

        setattr(self, stage_name, getattr(self, stage_name) + seconds)

    def as_dict(self):
        """Return unrounded stage seconds as a plain dictionary."""
        return {
            "fetch": self.fetch,
            "planning": self.planning,
            "apply": self.apply,
            "bulk_flush": self.bulk_flush,
            "total": self.total,
        }

    def as_rounded_dict(self):
        """Return stage seconds rounded for reporting output."""
        return {stage_name: round(value, 3) for stage_name, value in self.as_dict().items()}


@dataclass
class PipelineBatchMetrics:
    """Per-batch counters and stage timing prior to accumulation.

    Attributes:
        source_object_count: Number of source objects included in this pipeline batch.
        tracking_rows: Number of `DNSRuleRecord` rows fetched for this batch.
        pending_rule_calculations: Number of deferred rule work items generated
            during planning for this batch.
        pending_bulk_updates: Number of queued rename updates prepared for bulk
            flush in this batch.
        fallback_chunk_attempt_count: Number of fallback chunk-level retry
            attempts executed after fast bulk-update failures in this batch.
        fallback_singleton_attempt_count: Number of singleton savepoint retries
            executed while isolating failed fast updates in this batch.
        fallback_singleton_failure_count: Number of singleton retries that still
            failed in this batch.
        update_failure_recorded_count: Number of singleton failures recorded to
            failure-state storage in this batch.
        stage_metrics: Per-stage elapsed time accumulator for this batch.
    """

    source_object_count: int = 0
    tracking_rows: int = 0
    pending_rule_calculations: int = 0
    pending_bulk_updates: int = 0
    fallback_chunk_attempt_count: int = 0
    fallback_singleton_attempt_count: int = 0
    fallback_singleton_failure_count: int = 0
    update_failure_recorded_count: int = 0
    stage_metrics: PipelineStageMetrics = field(default_factory=PipelineStageMetrics)

    @contextmanager
    def time_stage(self, stage_name):
        """Context manager that accumulates stage elapsed time."""
        started_at = perf_counter()
        try:
            yield
        finally:
            self.stage_metrics.add(stage_name, perf_counter() - started_at)

    def finalize_total(self, started_at):
        """Finalize batch total time from a start timestamp."""
        self.stage_metrics.total = perf_counter() - started_at

    def apply_pipeline_outputs(
        self,
        *,
        tracking_rows,
        pending_rule_calculations,
        pending_rename_updates,
        flush_result,
    ):
        """Apply post-stage pipeline counters computed from stage outputs."""
        self.tracking_rows = tracking_rows
        self.pending_rule_calculations = pending_rule_calculations
        self.pending_bulk_updates = sum(len(entries) for entries in pending_rename_updates.values())

        self.fallback_chunk_attempt_count = flush_result.fallback_chunk_attempt_count
        self.fallback_singleton_attempt_count = flush_result.fallback_singleton_attempt_count
        self.fallback_singleton_failure_count = flush_result.fallback_singleton_failure_count
        self.update_failure_recorded_count = flush_result.update_failure_recorded_count


@dataclass
class PipelineMetrics:
    """Cumulative pipeline metrics across all processed batches.

    Attributes:
        batches: Number of processed pipeline batches accumulated in this
            metrics instance.
        source_object_count_total: Total number of source objects processed across all
            recorded batches.
        tracking_rows_total: Total number of fetched tracking rows across all
            recorded batches.
        pending_rule_calculations_total: Total number of deferred rule work
            items generated across all recorded batches.
        pending_bulk_updates_total: Total number of queued bulk rename updates
            accumulated across all recorded batches.
        fallback_chunk_attempt_count_total: Total number of fallback chunk
            attempts across all recorded batches.
        fallback_singleton_attempt_count_total: Total number of fallback
            singleton retry attempts across all recorded batches.
        fallback_singleton_failure_count_total: Total number of fallback
            singleton failures across all recorded batches.
        update_failure_recorded_count_total: Total number of update failures
            persisted to failure-state storage across all recorded batches.
        stage_metrics: Cumulative per-stage elapsed-time totals across all
            recorded batches.
    """

    batches: int = 0
    source_object_count_total: int = 0
    tracking_rows_total: int = 0
    pending_rule_calculations_total: int = 0
    pending_bulk_updates_total: int = 0
    fallback_chunk_attempt_count_total: int = 0
    fallback_singleton_attempt_count_total: int = 0
    fallback_singleton_failure_count_total: int = 0
    update_failure_recorded_count_total: int = 0
    stage_metrics: PipelineStageMetrics = field(default_factory=PipelineStageMetrics)

    @staticmethod
    def _avg(value, batches):
        """Return rounded per-batch average for one total counter."""
        return round(value / batches, 3)

    def record_batch(self, batch_metrics):
        """Accumulate one batch into running totals."""
        self.batches += 1
        self.source_object_count_total += batch_metrics.source_object_count
        self.tracking_rows_total += batch_metrics.tracking_rows
        self.pending_rule_calculations_total += batch_metrics.pending_rule_calculations
        self.pending_bulk_updates_total += batch_metrics.pending_bulk_updates
        self.fallback_chunk_attempt_count_total += batch_metrics.fallback_chunk_attempt_count
        self.fallback_singleton_attempt_count_total += batch_metrics.fallback_singleton_attempt_count
        self.fallback_singleton_failure_count_total += batch_metrics.fallback_singleton_failure_count
        self.update_failure_recorded_count_total += batch_metrics.update_failure_recorded_count
        for stage_name, value in batch_metrics.stage_metrics.as_dict().items():
            self.stage_metrics.add(stage_name, value)

    def as_report(self):
        """Serialize cumulative totals and per-batch averages."""
        stage_totals = self.stage_metrics.as_dict()
        metrics = {
            "batches": self.batches,
            "source_object_count_total": self.source_object_count_total,
            "tracking_rows_total": self.tracking_rows_total,
            "pending_rule_calculations_total": self.pending_rule_calculations_total,
            "pending_bulk_updates_total": self.pending_bulk_updates_total,
            "fallback_chunk_attempt_count_total": self.fallback_chunk_attempt_count_total,
            "fallback_singleton_attempt_count_total": self.fallback_singleton_attempt_count_total,
            "fallback_singleton_failure_count_total": self.fallback_singleton_failure_count_total,
            "update_failure_recorded_count_total": self.update_failure_recorded_count_total,
            "stage_metrics": self.stage_metrics.as_rounded_dict(),
        }
        batches = metrics["batches"] or 1
        metrics["avg_per_batch"] = {
            "source_object_count": self._avg(metrics["source_object_count_total"], batches),
            "tracking_rows": self._avg(metrics["tracking_rows_total"], batches),
            "pending_rule_calculations": self._avg(metrics["pending_rule_calculations_total"], batches),
            "pending_bulk_updates": self._avg(metrics["pending_bulk_updates_total"], batches),
            "fallback_chunk_attempt_count": self._avg(metrics["fallback_chunk_attempt_count_total"], batches),
            "fallback_singleton_attempt_count": self._avg(metrics["fallback_singleton_attempt_count_total"], batches),
            "fallback_singleton_failure_count": self._avg(metrics["fallback_singleton_failure_count_total"], batches),
            "update_failure_recorded_count": self._avg(metrics["update_failure_recorded_count_total"], batches),
            "stage_metrics": {k: self._avg(v, batches) for k, v in stage_totals.items()},
        }

        return metrics
