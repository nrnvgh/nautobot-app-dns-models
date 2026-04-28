"""Update strategy implementations for DNS reconcile updates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class UpdateResult(str, Enum):
    """Outcome of a single update candidate application."""

    UPDATED = "updated"
    UNCHANGED = "unchanged"
    FAILED = "failed"


class UpdateExecutor(ABC):
    """Abstract update executor used by the writer."""

    @abstractmethod
    def apply(
        self,
        *,
        writer,
        rule,
        source_obj,
        tracking_record,
        desired_record_data,
        phase,
        bulk_update_collector,
    ):
        """Apply one update and return updated/unchanged/failed."""


class StandardUpdateExecutor(UpdateExecutor):
    """Use ORM update path for each update candidate."""

    def apply(
        self,
        *,
        writer,
        rule,
        source_obj,
        tracking_record,
        desired_record_data,
        phase,
        bulk_update_collector,
    ):
        """Apply update through writer ORM path for one tracking record."""
        _ = bulk_update_collector
        return writer._update_tracked_dns_record_name(  # pylint: disable=protected-access
            rule=rule,
            source_obj=source_obj,
            tracking_record=tracking_record,
            desired_record_data=desired_record_data,
            phase=phase,
        )


class FastUpdateExecutor(UpdateExecutor):
    """Use queued bulk-update for supported updates; fallback to standard update."""

    def apply(
        self,
        *,
        writer,
        rule,
        source_obj,
        tracking_record,
        desired_record_data,
        phase,
        bulk_update_collector,
    ):
        """Queue rename updates when possible, otherwise fallback to standard."""
        if bulk_update_collector is None:
            return StandardUpdateExecutor().apply(
                writer=writer,
                rule=rule,
                source_obj=source_obj,
                tracking_record=tracking_record,
                desired_record_data=desired_record_data,
                phase=phase,
                bulk_update_collector=None,
            )

        dns_record = writer._resolve_prefetched_dns_record(tracking_record)  # pylint: disable=protected-access
        if dns_record is None:
            return UpdateResult.FAILED

        desired_name = desired_record_data["name"]
        if dns_record.name == desired_name:
            return UpdateResult.UNCHANGED

        dns_record.name = desired_name
        bulk_update_collector[type(dns_record)].append(
            {
                "dns_record": dns_record,
                "rule": rule,
                "source_obj": source_obj,
                "phase": phase,
                "desired_name": desired_name,
                "desired_record_data": desired_record_data,
                "source_content_type_id": tracking_record.content_type_id,
                "source_object_id": tracking_record.object_id,
                "candidate_record_type": rule.record_type,
                "candidate_zone_id": getattr(dns_record, "zone_id", None),
                "candidate_address_id": getattr(dns_record, "address_id", None),
            }
        )

        return UpdateResult.UPDATED
