"""Shared enums for DNS rule engine collaborators."""

# Prefer stdlib StrEnum when available; provide a local fallback for Python 3.10
# compatibility until this project drops 3.10 support (upstream EOL: October 2026).
from enum import Enum

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        """Compatibility fallback for Python versions without enum.StrEnum."""

        def __str__(self):
            """Return canonical serialized enum value."""
            return self.value


class EnginePhase(StrEnum):
    """Canonical phase labels used for log consistency and queryability."""

    CREATE = "create"
    UPDATE_RECONCILE = "update_reconcile"
    CANDIDATE_EXPANSION = "candidate_expansion"
    UNKNOWN = "unknown"


class EngineReason(StrEnum):
    """Stable reason tokens used for structured logging and error classification."""

    VIEW_TEMPLATE_EMPTY = "VIEW_TEMPLATE_EMPTY"
    VIEW_NOT_FOUND = "VIEW_NOT_FOUND"
    ZONE_NOT_FOUND = "ZONE_NOT_FOUND"
    CANDIDATE_TEMPLATE_ERROR = "CANDIDATE_TEMPLATE_ERROR"
    CANDIDATE_ERROR = "CANDIDATE_ERROR"
    RECORD_VALIDATION_ERROR = "RECORD_VALIDATION_ERROR"
    RECORD_INTEGRITY_ERROR = "RECORD_INTEGRITY_ERROR"
    RULE_PROCESSING_ERROR = "RULE_PROCESSING_ERROR"
    INVALID_ADDRESS_UUID = "INVALID_ADDRESS_UUID"
    INTERFACE_PARENT_FALLBACK_FAILED = "INTERFACE_PARENT_FALLBACK_FAILED"


class ExecutionMode(StrEnum):
    """Execution profile for reconcile mutations."""

    STANDARD = "standard"
    FAST = "fast"
