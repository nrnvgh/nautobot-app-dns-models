"""Tests for DNS reconciliation jobs."""

import json
from pathlib import Path
from unittest.mock import call, patch

from django.contrib.contenttypes.models import ContentType
import jsonschema
from nautobot.apps.testing import TransactionTestCase, create_job_result_and_run_job
from nautobot.dcim.models import Device, Interface
from nautobot.extras.choices import JobResultStatusChoices

from nautobot_dns_models.jobs import ReconcileDNSBulkJob, ReconcileDNSObjectJob
from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.tests.mixins.rule_engine import BaseRuleEngineMixin


class ReconcileDNSJobTestCase(BaseRuleEngineMixin, TransactionTestCase):
    """Validate DNS reconciliation job behavior."""

    @classmethod
    def setUpTestData(cls):
        """Set up base fixtures and one enabled Interface rule."""
        super().setUpTestData()
        cls.interface.ip_addresses.set([cls.ip_addresses[0]])
        cls.interface_rule = DNSRule.objects.create(
            name="job-interface-reconcile",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all | ip_address }}",
        )

    def setUp(self):
        """Rebuild fixtures per test under TransactionTestCase semantics."""
        TransactionTestCase.setUp(self)
        type(self).setUpTestData()
        BaseRuleEngineMixin.setUp(self)

    @patch("nautobot_dns_models.jobs.get_rule_engine")
    def test_single_object_mode_processes_requested_object(self, get_rule_engine):
        """Single-object mode should call process_object exactly once."""
        selected_engine = get_rule_engine.return_value
        selected_engine.process_object.return_value = {}
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=False,
            object_model="dcim.interface",
            object_id=str(self.interface.id),
        )

        selected_engine.process_object.assert_called_once_with(self.interface, created=False)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["execution"]["targets_seen"], 1)
        self.assertEqual(result["execution"]["processed_count"], 1)
        self.assertEqual(result["execution"]["failure_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_with_existing_rule_records"], 0)
        self.assertEqual(result["reconciliation"]["existing_rule_record_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_changed"], 0)
        self.assertEqual(result["reconciliation"]["record_ops_total_count"], 0)

    @patch("nautobot_dns_models.jobs.get_rule_engine")
    def test_single_object_parent_mode_includes_supported_children(self, get_rule_engine):
        """Single-object parent mode should reconcile both parent and child objects when requested."""
        selected_engine = get_rule_engine.return_value
        selected_engine.process_object.return_value = {}
        DNSRule.objects.create(
            name="job-device-reconcile",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=False,
            object_model="dcim.device",
            object_id=str(self.device.id),
            include_children=True,
        )

        selected_engine.process_object.assert_has_calls(
            [
                call(self.device, created=False),
                call(self.interface, created=False),
            ],
            any_order=False,
        )
        self.assertEqual(selected_engine.process_object.call_count, 2)
        self.assertEqual(result["scope"]["scanned_models"], ["dcim.device", "dcim.interface"])
        self.assertEqual(result["execution"]["targets_seen"], 2)
        self.assertEqual(result["execution"]["processed_count"], 2)
        self.assertEqual(result["execution"]["failure_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_with_existing_rule_records"], 0)
        self.assertEqual(result["reconciliation"]["existing_rule_record_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_changed"], 0)
        self.assertEqual(result["reconciliation"]["record_ops_total_count"], 0)

    @patch("nautobot_dns_models.jobs.get_rule_engine")
    def test_job_aggregates_engine_processing_summary(self, get_rule_engine):
        """Job output should aggregate per-object processing summary counters from the rule engine."""
        selected_engine = get_rule_engine.return_value
        selected_engine.process_object.side_effect = [
            {
                "had_existing_rule_records": True,
                "existing_rule_record_count": 2,
                "changed": True,
                "changed_record_count": 1,
                "record_ops_create_count": 1,
                "record_ops_delete_count": 0,
            },
            {
                "had_existing_rule_records": True,
                "existing_rule_record_count": 3,
                "changed": True,
                "changed_record_count": 2,
                "record_ops_create_count": 1,
                "record_ops_delete_count": 1,
            },
        ]
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=False,
            object_model="dcim.device",
            object_id=str(self.device.id),
            include_children=True,
        )

        self.assertEqual(result["execution"]["processed_count"], 2)
        self.assertEqual(result["reconciliation"]["objects_with_existing_rule_records"], 2)
        self.assertEqual(result["reconciliation"]["existing_rule_record_count"], 5)
        self.assertEqual(result["reconciliation"]["objects_changed"], 2)
        self.assertEqual(result["reconciliation"]["changed_record_count"], 3)
        self.assertEqual(result["reconciliation"]["record_ops_create_count"], 2)
        self.assertEqual(result["reconciliation"]["record_ops_delete_count"], 1)
        self.assertEqual(result["reconciliation"]["record_ops_total_count"], 3)

    def test_result_matches_json_schema(self):
        """Successful job output should validate against the published JSON schema."""
        job = ReconcileDNSObjectJob()
        result = job.run(
            dryrun=True,
            object_model="dcim.interface",
            object_id=str(self.interface.id),
        )

        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "reconcile_dns_job_result.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=result, schema=schema)

    @patch("nautobot_dns_models.jobs.get_rule_engine")
    def test_dryrun_mode_does_not_apply_updates(self, get_rule_engine):
        """Dry-run should enumerate targets without calling process_object."""
        selected_engine = get_rule_engine.return_value
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=True,
            object_model="dcim.interface",
            object_id=str(self.interface.id),
        )

        selected_engine.process_object.assert_not_called()
        self.assertTrue(result["mode"]["dryrun"])
        self.assertEqual(result["execution"]["targets_seen"], 1)
        self.assertEqual(result["execution"]["processed_count"], 0)

    def test_bulk_mode_resolves_target_model_from_enabled_rule_selection(self):
        """Bulk mode should scan only models covered by selected enabled rules."""
        job = ReconcileDNSBulkJob()

        result = job.run(
            dryrun=True,
            rules=[self.interface_rule],
            batch_size=10,
            limit=1,
        )

        self.assertEqual(result["scope"]["scanned_models"], ["dcim.interface"])

    @patch("nautobot_dns_models.jobs.get_rule_engine")
    def test_invalid_source_model_marks_job_failed(self, get_rule_engine):
        """Submitting an unsupported source model should fail and skip processing."""
        selected_engine = get_rule_engine.return_value
        job_result = create_job_result_and_run_job(
            "nautobot_dns_models.jobs",
            "ReconcileDNSBulkJob",
            dryrun=True,
            source_models=["not_a_real.contenttype"],
        )

        # Invalid source model input should fail during validation before any object processing is attempted.
        selected_engine.process_object.assert_not_called()

        self.assertJobResultStatus(job_result, JobResultStatusChoices.STATUS_FAILURE)
        self.assertIn("error", job_result.result)
        self.assertEqual(job_result.result["error"], "invalid_source_models")
        self.assertEqual(job_result.result["invalid_source_models"], ["not_a_real.contenttype"])

    def test_invalid_source_model_job_run_reports_failure_status(self):
        """Job helper execution should report STATUS_FAILURE for invalid source model input."""
        job_result = create_job_result_and_run_job(
            "nautobot_dns_models.jobs",
            "ReconcileDNSBulkJob",
            dryrun=True,
            source_models=["not_a_real.contenttype"],
        )
        self.assertJobResultStatus(job_result, JobResultStatusChoices.STATUS_FAILURE)
