"""Shared constants for DNS rule engine collaborators."""

from enum import Enum


class EnginePhase(str, Enum):
    """Canonical phase labels used for log consistency and queryability."""

    CREATE = "create"
    UPDATE_RECONCILE = "update_reconcile"
    CANDIDATE_EXPANSION = "candidate_expansion"
    UNKNOWN = "unknown"

    def __str__(self):
        return self.value


# Candidate/rule processing reason codes used for warning/error logs.
REASON_VIEW_TEMPLATE_EMPTY = "VIEW_TEMPLATE_EMPTY"
REASON_VIEW_NOT_FOUND = "VIEW_NOT_FOUND"
REASON_ZONE_NOT_FOUND = "ZONE_NOT_FOUND"
REASON_CANDIDATE_TEMPLATE_ERROR = "CANDIDATE_TEMPLATE_ERROR"
REASON_CANDIDATE_ERROR = "CANDIDATE_ERROR"
REASON_RECORD_VALIDATION_ERROR = "RECORD_VALIDATION_ERROR"
REASON_RECORD_INTEGRITY_ERROR = "RECORD_INTEGRITY_ERROR"
REASON_RULE_PROCESSING_ERROR = "RULE_PROCESSING_ERROR"
REASON_INVALID_ADDRESS_UUID = "INVALID_ADDRESS_UUID"
REASON_INTERFACE_PARENT_FALLBACK_FAILED = "INTERFACE_PARENT_FALLBACK_FAILED"
