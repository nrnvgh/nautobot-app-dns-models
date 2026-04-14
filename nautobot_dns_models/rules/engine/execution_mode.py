"""Shared execution mode enum for reconcile strategies."""

from enum import Enum


class ExecutionMode(str, Enum):
    """Execution profile for reconcile mutations."""

    STANDARD = "standard"
    FAST = "fast"
