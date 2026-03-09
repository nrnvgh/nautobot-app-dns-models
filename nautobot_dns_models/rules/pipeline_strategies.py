"""Pluggable strategies for experimental bulk pipeline reconciliation."""

from abc import ABC, abstractmethod


class ExperimentalPipelineStrategy(ABC):
    """Strategy contract for batch reconcile execution."""

    name = "base"

    @abstractmethod
    def process_objects_pipeline(self, engine, source_objects, created=False):
        """Run reconcile pipeline for one same-model object batch."""


class PythonFirstPipelineStrategy(ExperimentalPipelineStrategy):
    """Baseline strategy: Python-native planning and apply phases."""

    name = "python_first"

    def process_objects_pipeline(self, engine, source_objects, created=False):
        """Delegate to baseline engine implementation."""
        return engine._process_objects_pipeline_python_first(source_objects=source_objects, created=created)


class HybridPipelineStrategy(ExperimentalPipelineStrategy):
    """Hybrid strategy placeholder; starts from Python-first semantics."""

    name = "hybrid"

    def process_objects_pipeline(self, engine, source_objects, created=False):
        """Delegate to hybrid implementation."""
        return engine._process_objects_pipeline_hybrid(source_objects=source_objects, created=created)


class SQLHeavyPipelineStrategy(ExperimentalPipelineStrategy):
    """SQL-heavy strategy placeholder; starts from Python-first semantics."""

    name = "sql_heavy"

    def process_objects_pipeline(self, engine, source_objects, created=False):
        """Delegate to baseline implementation until SQL-heavy path is added."""
        return engine._process_objects_pipeline_python_first(source_objects=source_objects, created=created)


class RuleDrivenPipelineStrategy(ExperimentalPipelineStrategy):
    """Rule-driven strategy prototype: group planning by rule across objects."""

    name = "rule_driven"

    def process_objects_pipeline(self, engine, source_objects, created=False):
        """Delegate to rule-grouped implementation."""
        return engine._process_objects_pipeline_rule_driven(source_objects=source_objects, created=created)
