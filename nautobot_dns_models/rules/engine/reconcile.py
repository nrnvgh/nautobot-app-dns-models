"""Diff planning helpers for record reconciliation."""

from dataclasses import dataclass


@dataclass
class ReconcilePlan:
    """Identity-based reconcile plan for one rule/object pair."""

    existing_records_by_identity: dict
    desired_records_by_identity: dict
    records_to_delete: set
    records_to_create: set
    records_to_check_for_update: set


class ReconcilePlanner:
    """Build reconcile plans from existing tracking rows and desired data."""

    @staticmethod
    def build_plan(*, existing_records_by_identity, desired_records_by_identity):
        """Return identity-diff plan for create/update/delete operations."""
        existing_identity_keys = set(existing_records_by_identity.keys())
        desired_identity_keys = set(desired_records_by_identity.keys())
        records_to_delete = existing_identity_keys - desired_identity_keys
        records_to_create = desired_identity_keys - existing_identity_keys
        records_to_check_for_update = existing_identity_keys & desired_identity_keys

        return ReconcilePlan(
            existing_records_by_identity=existing_records_by_identity,
            desired_records_by_identity=desired_records_by_identity,
            records_to_delete=records_to_delete,
            records_to_create=records_to_create,
            records_to_check_for_update=records_to_check_for_update,
        )
