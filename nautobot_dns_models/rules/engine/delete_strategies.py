"""Delete strategy implementations for DNS reconcile cleanup."""

from __future__ import annotations

from abc import ABC, abstractmethod

from django.db import transaction
from nautobot.extras.models import ContactAssociation, Note, TaggedItem

from nautobot_dns_models.models import DNSRuleRecord


class DeleteExecutor(ABC):
    """Abstract delete executor used by the writer."""

    @abstractmethod
    def delete_chunk(self, *, record_model, record_content_type_id, record_ids):
        """Delete one chunk of records and return deleted DNS-record count."""


class StandardDeleteExecutor(DeleteExecutor):
    """Delete using Django ORM collector semantics and signals."""

    def delete_chunk(self, *, record_model, record_content_type_id, record_ids):
        """Delete via ORM and return deleted DNS record-model count."""
        _ = record_content_type_id
        _, deleted_per_model = record_model.objects.filter(pk__in=list(record_ids)).delete()

        return deleted_per_model.get(record_model._meta.label, 0)


class FastDeleteExecutor(DeleteExecutor):
    """Delete using direct SQL deletes for speed and explicit cleanup."""

    def delete_chunk(self, *, record_model, record_content_type_id, record_ids):
        """Delete via raw SQL and return deleted DNS record-model count."""
        db_alias = record_model.objects.db
        record_ids_list = list(record_ids)
        with transaction.atomic(using=db_alias):
            DNSRuleRecord.objects.filter(
                dns_record_content_type_id=record_content_type_id,
                dns_record_object_id__in=record_ids_list,
            )._raw_delete(using=db_alias)

            Note.objects.filter(
                assigned_object_type_id=record_content_type_id,
                assigned_object_id__in=record_ids_list,
            )._raw_delete(using=db_alias)

            ContactAssociation.objects.filter(
                associated_object_type_id=record_content_type_id,
                associated_object_id__in=record_ids_list,
            )._raw_delete(using=db_alias)

            TaggedItem.objects.filter(
                content_type_id=record_content_type_id,
                object_id__in=record_ids_list,
            )._raw_delete(using=db_alias)

            return record_model.objects.filter(pk__in=record_ids_list)._raw_delete(using=db_alias)
