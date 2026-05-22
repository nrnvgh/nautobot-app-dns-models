"""Shared runtime context for engine collaborators."""

from dataclasses import dataclass

from jinja2 import Environment

from nautobot_dns_models.rules.engine.enums import ExecutionMode


@dataclass(frozen=True)
class EngineContext:
    """Cross-collaborator runtime dependencies and static knobs."""

    jinja_env: Environment
    bulk_rename_update_batch_size: int
    bulk_create_batched_pipeline_size: int
    bulk_delete_batched_pipeline_size: int
    execution_mode: ExecutionMode

    def __post_init__(self):
        """Sanity-check in case the caller passes in an invalid value."""
        object.__setattr__(
            self,
            "execution_mode",
            ExecutionMode(self.execution_mode),
        )
