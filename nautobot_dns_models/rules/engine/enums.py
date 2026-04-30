"""Shared enums for DNS rule engine collaborators."""

from enum import Enum


class EnginePhase(str, Enum):
    """Canonical phase labels used for log consistency and queryability."""

    CREATE = "create"
    UPDATE_RECONCILE = "update_reconcile"
    CANDIDATE_EXPANSION = "candidate_expansion"
    UNKNOWN = "unknown"

    def __str__(self):
        """Return canonical serialized phase value."""
        return self.value


class EngineReason(str, Enum):
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

    def __str__(self):
        """Return canonical serialized reason value."""
        return self.value
