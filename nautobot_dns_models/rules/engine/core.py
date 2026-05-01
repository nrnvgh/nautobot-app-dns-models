"""DNS Rule Processing Engine for Nautobot DNS Models."""

import logging

from django.contrib.contenttypes.models import ContentType
from django.template import engines as django_template_engines

from nautobot_dns_models.models import DNSRuleRecord
from nautobot_dns_models.rules.engine.cache import EngineCache
from nautobot_dns_models.rules.engine.context import EngineContext
from nautobot_dns_models.rules.engine.enums import ExecutionMode
from nautobot_dns_models.rules.engine.materializer import RecordMaterializer
from nautobot_dns_models.rules.engine.metrics import ObjectProcessingMetrics, PipelineMetrics
from nautobot_dns_models.rules.engine.pipeline import EnginePipeline
from nautobot_dns_models.rules.engine.resolver import RuleResolver
from nautobot_dns_models.rules.engine.strategies import (
    FastDeleteExecutor,
    FastUpdateExecutor,
    StandardDeleteExecutor,
    StandardUpdateExecutor,
)
from nautobot_dns_models.rules.engine.types import BatchedCreateState
from nautobot_dns_models.rules.engine.writer import RecordWriter

logger = logging.getLogger(__name__)


class DNSRuleEngine:
    """Primary engine that reconciles DNS records in explicit batch phases."""

    # Tuned against ~65k update benchmarks:
    # - 250: ~2572 changed/sec (avg, best)
    # - 500: ~2459 changed/sec (avg)
    # - 1000: ~2468 changed/sec (avg)
    # Keep this constant in sync with docs/dev/reconcile_greenfield_performance_tally.md.
    BULK_RENAME_UPDATE_BATCH_SIZE = 250
    BULK_CREATE_BATCHED_PIPELINE_SIZE = 1000
    BULK_DELETE_BATCHED_PIPELINE_SIZE = 1000

    def __init__(self, *, execution_mode=ExecutionMode.STANDARD, selected_rules=None):
        """Initialize DNS rule engine caches and pipeline state."""
        cache = EngineCache()
        batched_create_state = BatchedCreateState()
        self._pipeline_metrics = PipelineMetrics()
        #
        # Another way to do this would be to apply an overlay to the base environment which
        # set trim_blocks=True, lstrip_blocks=True, and possibly even undefined=StrictUndefined.
        # This could be useful, but would be different than how the nautobot core sets up its environment.
        # Currently optimizing for consistency rather than maximizing ease of use for DNS rules.
        jinja_env = django_template_engines["jinja"].env

        selected_execution_mode = ExecutionMode(execution_mode)
        context = EngineContext(
            jinja_env=jinja_env,
            bulk_rename_update_batch_size=self.BULK_RENAME_UPDATE_BATCH_SIZE,
            bulk_create_batched_pipeline_size=self.BULK_CREATE_BATCHED_PIPELINE_SIZE,
            bulk_delete_batched_pipeline_size=self.BULK_DELETE_BATCHED_PIPELINE_SIZE,
            execution_mode=selected_execution_mode,
        )

        self._resolver = RuleResolver(cache, context, selected_rules=selected_rules)
        self._materializer = RecordMaterializer(cache, context)

        if selected_execution_mode == ExecutionMode.FAST:
            delete_executor = FastDeleteExecutor()
            update_executor = FastUpdateExecutor()
        else:
            delete_executor = StandardDeleteExecutor()
            update_executor = StandardUpdateExecutor()

        self._writer = RecordWriter(
            context,
            resolver=self._resolver,
            materializer=self._materializer,
            batched_create_state=batched_create_state,
            delete_executor=delete_executor,
            update_executor=update_executor,
        )
        self._pipeline = EnginePipeline(
            writer=self._writer,
            resolver=self._resolver,
            materializer=self._materializer,
            context=context,
            pipeline_metrics=self._pipeline_metrics,
            batched_create_state=batched_create_state,
        )

    #
    # Object processing methods
    def process_object(self, source_obj, created=False):
        """Process one source object against applicable rules."""
        summary = ObjectProcessingMetrics()
        content_type = ContentType.objects.get_for_model(source_obj)
        rules = self.get_applicable_rules(source_obj)

        if not rules:
            logger.debug(
                "No DNS rules found for %s - skipping DNS record processing for %s",
                content_type,
                source_obj,
            )
            return summary

        existing_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.pk)
        existing_count = existing_records.count()
        summary.existing_rule_record_count = existing_count
        summary.had_existing_rule_records = existing_count > 0

        if created or existing_count == 0:
            change_result = self._writer.create_dns_records_for_object(source_obj, rules)
        else:
            change_result = self._writer.update_dns_records_for_object(source_obj, rules)

        summary.changed_record_count = change_result["changed_record_count"]
        summary.dns_record_create_count = change_result["dns_record_create_count"]
        summary.dns_record_delete_count = change_result["dns_record_delete_count"]
        summary.dns_record_update_count = change_result["dns_record_update_count"]
        summary.dns_record_unchanged_count = change_result["dns_record_unchanged_count"]

        return summary

    def get_applicable_rules(self, source_obj):
        """Return applicable DNS rules for a source object."""
        return self._resolver.get_applicable_rules(source_obj)

    def delete_dns_records_for_object(self, source_obj):
        """Delete all DNS records created from a source object."""
        content_type = ContentType.objects.get_for_model(source_obj)
        rule_records = DNSRuleRecord.objects.filter(content_type=content_type, object_id=source_obj.id)

        for rule_record in rule_records:
            self._writer.delete_tracking_and_dns_record(rule_record)

    #
    # Pipeline methods
    def process_objects_pipeline(self, source_objects):
        """Process one batch of source objects."""
        return self._pipeline.process_objects_pipeline(source_objects)

    def get_pipeline_metrics(self):
        """Return cumulative and per-batch stage metrics for current run."""
        return self._pipeline_metrics.as_report()
