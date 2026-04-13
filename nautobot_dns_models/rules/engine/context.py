"""Shared runtime context for engine collaborators."""

from dataclasses import dataclass

from nautobot_dns_models.rules.engine.execution_mode import ExecutionMode


@dataclass(frozen=True)
class EngineContext:
    """Cross-collaborator runtime dependencies and static knobs."""

    jinja_env: object
    bulk_rename_update_batch_size: int
    bulk_create_batched_pipeline_size: int
    bulk_delete_batched_pipeline_size: int
    execution_mode: ExecutionMode
