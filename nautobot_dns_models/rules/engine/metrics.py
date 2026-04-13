"""Metrics dataclasses for DNS rule engine processing."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class ObjectProcessingMetrics:
    """Per-object result returned by the engine's processing paths."""

    had_existing_rule_records: bool = False
    existing_rule_record_count: int = 0
    changed_record_count: int = 0
    record_ops_create_count: int = 0
    record_ops_delete_count: int = 0
    record_ops_update_count: int = 0


@dataclass
class PipelineStageMetrics:
    """Accumulate elapsed seconds for each pipeline stage."""

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

    def as_dict(self, rounded=False):
        """Return stage seconds as a plain dictionary."""
        data = {
            "fetch": self.fetch,
            "planning": self.planning,
            "apply": self.apply,
            "bulk_flush": self.bulk_flush,
            "total": self.total,
        }
        if not rounded:
            return data

        return {stage_name: round(value, 3) for stage_name, value in data.items()}


@dataclass
class PipelineBatchMetrics:
    """Per-batch counters and stage timing prior to accumulation."""

    objects: int = 0
    tracking_rows: int = 0
    pending_rule_calculations: int = 0
    pending_bulk_updates: int = 0
    stage_metrics: PipelineStageMetrics = field(default_factory=PipelineStageMetrics)

    @contextmanager
    def time_stage(self, stage_name):
        """Context manager that accumulates stage elapsed time."""
        started_at = perf_counter()
        try:
            yield
        finally:
            self.stage_metrics.add(stage_name, perf_counter() - started_at)


@dataclass
class PipelineMetrics:
    """Cumulative pipeline metrics across all processed batches."""

    batches: int = 0
    objects_total: int = 0
    tracking_rows_total: int = 0
    pending_rule_calculations_total: int = 0
    pending_bulk_updates_total: int = 0
    stage_metrics: PipelineStageMetrics = field(default_factory=PipelineStageMetrics)

    def record_batch(self, batch_metrics):
        """Accumulate one batch into running totals."""
        self.batches += 1
        self.objects_total += batch_metrics.objects
        self.tracking_rows_total += batch_metrics.tracking_rows
        self.pending_rule_calculations_total += batch_metrics.pending_rule_calculations
        self.pending_bulk_updates_total += batch_metrics.pending_bulk_updates
        for stage_name, value in batch_metrics.stage_metrics.as_dict().items():
            self.stage_metrics.add(stage_name, value)

    def as_report(self):
        """Serialize cumulative totals and per-batch averages."""
        stage_metrics = self.stage_metrics.as_dict(rounded=True)
        metrics = {
            "batches": self.batches,
            "objects_total": self.objects_total,
            "tracking_rows_total": self.tracking_rows_total,
            "pending_rule_calculations_total": self.pending_rule_calculations_total,
            "pending_bulk_updates_total": self.pending_bulk_updates_total,
            "stage_metrics": stage_metrics,
        }
        batches = metrics["batches"] or 1
        metrics["avg_per_batch"] = {
            "objects": round(metrics["objects_total"] / batches, 3),
            "tracking_rows": round(metrics["tracking_rows_total"] / batches, 3),
            "pending_rule_calculations": round(metrics["pending_rule_calculations_total"] / batches, 3),
            "pending_bulk_updates": round(metrics["pending_bulk_updates_total"] / batches, 3),
            "stage_metrics": {k: round(v / batches, 3) for k, v in stage_metrics.items()},
        }

        return metrics
