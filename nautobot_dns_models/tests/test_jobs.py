"""Tests for DNS reconciliation jobs."""

import json
from pathlib import Path
from unittest.mock import call, patch

import jsonschema
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from nautobot.apps.testing import TransactionTestCase, create_job_result_and_run_job
from nautobot.dcim.models import Device, DeviceBay, Interface, Location, Module, ModuleBay, ModuleType
from nautobot.extras.choices import JobResultStatusChoices
from nautobot.extras.models import Status
from nautobot.ipam.models import IPAddress, Prefix, Service
from nautobot.tenancy.models import Tenant
from nautobot.virtualization.models import Cluster, VirtualMachine, VMInterface

from nautobot_dns_models.jobs import ReconcileDNSBulkJob, ReconcileDNSObjectJob, ReconcileRunSummary
from nautobot_dns_models.models import ARecord, DNSRule, DNSRuleRecord
from nautobot_dns_models.rules.engine import DNSRuleEngine
from nautobot_dns_models.rules.engine.execution_mode import ExecutionMode
from nautobot_dns_models.rules.engine.metrics import ObjectProcessingMetrics
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
            value_template="{{ obj.ip_addresses.all() }}",
        )

    def setUp(self):
        """Rebuild fixtures per test under TransactionTestCase semantics."""
        # Keep ContentType cache aligned with recreated test DB state.
        ContentType.objects.clear_cache()
        TransactionTestCase.setUp(self)
        type(self).setUpTestData()
        BaseRuleEngineMixin.setUp(self)

    def _create_module_bay_interface_for_device(self, *, name_prefix, parent_device):
        """Create one module-bay-backed interface associated with a parent device."""
        module_status = Status.objects.get_for_model(Module).first()
        module_type = ModuleType.objects.create(
            manufacturer=self.manufacturer,
            model=f"{name_prefix}-module-type",
        )
        parent_bay = ModuleBay.objects.create(
            parent_device=parent_device,
            name=f"{name_prefix}-module-bay0",
        )
        module = Module.objects.create(
            module_type=module_type,
            parent_module_bay=parent_bay,
            status=module_status,
        )
        return Interface.objects.create(
            name=f"{name_prefix}-module-eth0",
            module=module,
            device=None,
            type=self.interface.type,
            status=self.interface_status,
        )

    def _create_child_device_with_interface(self, *, name_prefix, parent_device, location):
        """Create one child device installed in parent device bay and one child interface."""
        child_device = Device.objects.create(
            name=f"{name_prefix}-child-device",
            device_type=self.device_type,
            location=location,
            role=self.device_role,
            status=self.device_status,
        )
        DeviceBay.objects.create(
            device=parent_device,
            name=f"{name_prefix}-child-bay0",
            installed_device=child_device,
        )
        child_interface = Interface.objects.create(
            name=f"{name_prefix}-child-eth0",
            device=child_device,
            type=self.interface.type,
            status=self.interface_status,
        )
        return child_device, child_interface

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_single_object_mode_processes_requested_object(self, mock_dns_rule_engine_class):
        """Single-object mode should call process_object exactly once."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_object.return_value = ObjectProcessingMetrics()
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Interface),
            object_id=str(self.interface.id),
        )

        rule_engine.process_object.assert_called_once_with(self.interface, created=False)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["execution"]["targets_selected_count"], 1)
        self.assertEqual(result["execution"]["targets_processed_count"], 1)
        self.assertEqual(result["execution"]["targets_failed_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_with_existing_rule_records"], 0)
        self.assertEqual(result["reconciliation"]["existing_rule_record_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_changed"], 0)
        self.assertEqual(result["reconciliation"]["dns_record_total_count"], 0)
        self.assertEqual(result["reconciliation"]["targets_noop_count"], 1)

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_single_object_parent_mode_includes_supported_children(self, mock_dns_rule_engine_class):
        """Single-object parent mode should reconcile both parent and child objects when requested."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_object.return_value = ObjectProcessingMetrics()
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
            object_model=ContentType.objects.get_for_model(Device),
            object_id=str(self.device.id),
            include_child_devices=True,
            include_interfaces=True,
        )

        rule_engine.process_object.assert_has_calls(
            [
                call(self.device, created=False),
                call(self.interface, created=False),
            ],
            any_order=False,
        )
        self.assertEqual(rule_engine.process_object.call_count, 2)
        self.assertEqual(result["scope"]["scanned_models"], ["dcim.device", "dcim.interface"])
        self.assertEqual(result["execution"]["targets_selected_count"], 2)
        self.assertEqual(result["execution"]["targets_processed_count"], 2)
        self.assertEqual(result["execution"]["targets_failed_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_with_existing_rule_records"], 0)
        self.assertEqual(result["reconciliation"]["existing_rule_record_count"], 0)
        self.assertEqual(result["reconciliation"]["objects_changed"], 0)
        self.assertEqual(result["reconciliation"]["dns_record_total_count"], 0)
        self.assertEqual(result["reconciliation"]["targets_noop_count"], 2)

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_single_object_parent_mode_includes_module_bay_interfaces(self, mock_dns_rule_engine_class):
        """Single-object parent mode should include interfaces installed on modules in module bays."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_object.return_value = ObjectProcessingMetrics()

        module_interface = self._create_module_bay_interface_for_device(
            name_prefix="object-include-children",
            parent_device=self.device,
        )

        job = ReconcileDNSObjectJob()
        result = job.run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Device),
            object_id=str(self.device.id),
            include_child_devices=True,
            include_interfaces=True,
        )

        processed_objects = [call_args.args[0] for call_args in rule_engine.process_object.call_args_list]
        self.assertIn(module_interface, processed_objects)
        self.assertIn("dcim.interface", result["scope"]["scanned_models"])

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_single_object_parent_mode_includes_child_devices_and_interfaces(self, mock_dns_rule_engine_class):
        """Single-object parent mode should include child devices and their interfaces."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_object.return_value = ObjectProcessingMetrics()
        DNSRule.objects.create(
            name="job-device-ip-child-reconcile",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )
        child_device, child_interface = self._create_child_device_with_interface(
            name_prefix="object-child-device",
            parent_device=self.device,
            location=self.location,
        )
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Device),
            object_id=str(self.device.id),
            include_child_devices=True,
            include_interfaces=True,
        )

        processed_objects = [call_args.args[0] for call_args in rule_engine.process_object.call_args_list]
        self.assertIn(child_device, processed_objects)
        self.assertIn(child_interface, processed_objects)
        self.assertIn("dcim.device", result["scope"]["scanned_models"])
        self.assertIn("dcim.interface", result["scope"]["scanned_models"])

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_job_aggregates_engine_processing_summary(self, mock_dns_rule_engine_class):
        """Job output should aggregate per-object processing summary counters from the rule engine."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_object.side_effect = [
            ObjectProcessingMetrics(
                had_existing_rule_records=True,
                existing_rule_record_count=2,
                changed_record_count=1,
                dns_record_create_count=1,
                dns_record_delete_count=0,
            ),
            ObjectProcessingMetrics(
                had_existing_rule_records=True,
                existing_rule_record_count=3,
                changed_record_count=2,
                dns_record_create_count=1,
                dns_record_delete_count=1,
            ),
        ]
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Device),
            object_id=str(self.device.id),
            include_child_devices=True,
            include_interfaces=True,
        )

        self.assertEqual(result["execution"]["targets_processed_count"], 2)
        self.assertEqual(result["reconciliation"]["objects_with_existing_rule_records"], 2)
        self.assertEqual(result["reconciliation"]["existing_rule_record_count"], 5)
        self.assertEqual(result["reconciliation"]["objects_changed"], 2)
        self.assertEqual(result["reconciliation"]["changed_record_count"], 3)
        self.assertEqual(result["reconciliation"]["dns_record_create_count"], 2)
        self.assertEqual(result["reconciliation"]["dns_record_delete_count"], 1)
        self.assertEqual(result["reconciliation"]["dns_record_update_count"], 0)
        self.assertEqual(result["reconciliation"]["dns_record_total_count"], 3)
        self.assertEqual(result["reconciliation"]["targets_noop_count"], 0)

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_object_job_path_uses_process_object_not_pipeline(self, mock_dns_rule_engine_class):
        """Object reconcile job flow should call process_object and not process_objects_pipeline."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_object.return_value = ObjectProcessingMetrics()
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Interface),
            object_id=str(self.interface.id),
        )

        rule_engine.process_object.assert_called_once_with(self.interface, created=False)
        rule_engine.process_objects_pipeline.assert_not_called()
        self.assertEqual(result["execution"]["targets_processed_count"], 1)
        self.assertEqual(result["execution"]["targets_failed_count"], 0)

    def test_single_object_parent_include_child_devices_creates_parent_and_child_device_records(self):
        """Single-object Device run with child-device expansion should create DNS records for parent and child devices."""
        DNSRule.objects.create(
            name="object-device-primary-ip-both",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            zone_template="example.com",
            name_template="objjob-{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )
        child_device, _child_interface = self._create_child_device_with_interface(
            name_prefix="object-device-both",
            parent_device=self.device,
            location=self.location,
        )

        parent_ip = self.ip_addresses[1]
        child_ip = IPAddress.objects.create(
            address="192.168.1.99/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=self.prefix,
        )
        self.device.primary_ip4 = parent_ip
        self.device.save(update_fields=["primary_ip4"])
        child_device.primary_ip4 = child_ip
        child_device.save(update_fields=["primary_ip4"])

        parent_record_name = f"objjob-{self.device.name}"
        child_record_name = f"objjob-{child_device.name}"
        ARecord.objects.filter(name__in=[parent_record_name, child_record_name], zone=self.dns_zone).delete()

        result = ReconcileDNSObjectJob().run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Device),
            object_id=str(self.device.id),
            include_child_devices=True,
            include_interfaces=False,
        )

        self.assertTrue(ARecord.objects.filter(name=parent_record_name, zone=self.dns_zone).exists())
        self.assertTrue(ARecord.objects.filter(name=child_record_name, zone=self.dns_zone).exists())
        self.assertEqual(result["execution"]["targets_processed_count"], 2)

    def test_single_object_child_device_creates_dns_record(self):
        """Single-object Device run should reconcile a child device directly and create DNS record."""
        DNSRule.objects.create(
            name="object-child-device-primary-ip",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            zone_template="example.com",
            name_template="child-only-{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )
        child_device, _child_interface = self._create_child_device_with_interface(
            name_prefix="object-child-direct",
            parent_device=self.device,
            location=self.location,
        )
        child_ip = IPAddress.objects.create(
            address="192.168.1.98/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=self.prefix,
        )
        child_device.primary_ip4 = child_ip
        child_device.save(update_fields=["primary_ip4"])

        record_name = f"child-only-{child_device.name}"
        ARecord.objects.filter(name=record_name, zone=self.dns_zone).delete()

        result = ReconcileDNSObjectJob().run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Device),
            object_id=str(child_device.id),
            include_child_devices=False,
            include_interfaces=False,
        )

        self.assertTrue(ARecord.objects.filter(name=record_name, zone=self.dns_zone).exists())
        self.assertEqual(result["execution"]["targets_processed_count"], 1)

    def test_single_object_parent_without_include_children_does_not_reconcile_child_device(self):
        """Single-object Device run without child expansion should not create child-device DNS records."""
        DNSRule.objects.create(
            name="object-parent-no-childs",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            zone_template="example.com",
            name_template="no-child-{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )
        child_device, _child_interface = self._create_child_device_with_interface(
            name_prefix="object-parent-no-children",
            parent_device=self.device,
            location=self.location,
        )
        parent_ip = self.ip_addresses[2]
        child_ip = IPAddress.objects.create(
            address="192.168.1.97/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=self.prefix,
        )
        self.device.primary_ip4 = parent_ip
        self.device.save(update_fields=["primary_ip4"])
        child_device.primary_ip4 = child_ip
        child_device.save(update_fields=["primary_ip4"])

        parent_record_name = f"no-child-{self.device.name}"
        child_record_name = f"no-child-{child_device.name}"
        ARecord.objects.filter(name__in=[parent_record_name, child_record_name], zone=self.dns_zone).delete()

        result = ReconcileDNSObjectJob().run(
            dryrun=False,
            object_model=ContentType.objects.get_for_model(Device),
            object_id=str(self.device.id),
            include_child_devices=False,
            include_interfaces=False,
        )

        self.assertTrue(ARecord.objects.filter(name=parent_record_name, zone=self.dns_zone).exists())
        self.assertFalse(ARecord.objects.filter(name=child_record_name, zone=self.dns_zone).exists())
        self.assertEqual(result["execution"]["targets_processed_count"], 1)

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_dryrun_mode_does_not_apply_updates(self, mock_dns_rule_engine_class):
        """Dry-run should enumerate targets without calling process_object."""
        rule_engine = mock_dns_rule_engine_class.return_value
        job = ReconcileDNSObjectJob()

        result = job.run(
            dryrun=True,
            object_model=ContentType.objects.get_for_model(Interface),
            object_id=str(self.interface.id),
        )

        rule_engine.process_object.assert_not_called()
        self.assertTrue(result["mode"]["dryrun"])
        self.assertEqual(result["execution"]["targets_selected_count"], 1)
        self.assertEqual(result["execution"]["targets_processed_count"], 0)

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

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_bulk_mode_uses_standard_execution_mode_by_default(self, mock_dns_rule_engine_class):
        """Bulk mode should default to standard execution mode."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_objects_pipeline.return_value = []
        rule_engine.get_pipeline_metrics.return_value = {
            "batches": 0,
            "source_object_count_total": 0,
            "tracking_row_count_total": 0,
            "pending_rule_work_items_total": 0,
            "pending_bulk_updates_total": 0,
            "update_fallback_chunk_attempt_count_total": 0,
            "update_fallback_singleton_attempt_count_total": 0,
            "update_fallback_singleton_failure_count_total": 0,
            "create_fallback_chunk_attempt_count_total": 0,
            "create_fallback_singleton_attempt_count_total": 0,
            "create_fallback_singleton_failure_count_total": 0,
            "new_update_failure_state_count_total": 0,
            "existing_update_failure_state_count_total": 0,
            "stage_metrics": {"fetch": 0, "planning": 0, "apply": 0, "bulk_flush": 0, "total": 0},
            "avg_per_batch": {
                "source_object_count": 0,
                "tracking_row_count": 0,
                "pending_rule_work_items": 0,
                "pending_bulk_updates": 0,
                "update_fallback_chunk_attempt_count": 0,
                "update_fallback_singleton_attempt_count": 0,
                "update_fallback_singleton_failure_count": 0,
                "create_fallback_chunk_attempt_count": 0,
                "create_fallback_singleton_attempt_count": 0,
                "create_fallback_singleton_failure_count": 0,
                "new_update_failure_state_count": 0,
                "existing_update_failure_state_count": 0,
                "stage_metrics": {"fetch": 0, "planning": 0, "apply": 0, "bulk_flush": 0, "total": 0},
            },
        }

        result = ReconcileDNSBulkJob().run(dryrun=False, rules=[self.interface_rule], limit=1, batch_size=1)

        mock_dns_rule_engine_class.assert_called_once_with(
            execution_mode=ExecutionMode.STANDARD,
            selected_rules=[self.interface_rule],
        )
        self.assertEqual(result["mode"]["execution_mode"], ExecutionMode.STANDARD.value)

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_bulk_mode_accepts_fast_mode(self, mock_dns_rule_engine_class):
        """Bulk mode should map fast_mode flag to fast execution mode."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_objects_pipeline.return_value = []
        rule_engine.get_pipeline_metrics.return_value = {
            "batches": 0,
            "source_object_count_total": 0,
            "tracking_row_count_total": 0,
            "pending_rule_work_items_total": 0,
            "pending_bulk_updates_total": 0,
            "update_fallback_chunk_attempt_count_total": 0,
            "update_fallback_singleton_attempt_count_total": 0,
            "update_fallback_singleton_failure_count_total": 0,
            "create_fallback_chunk_attempt_count_total": 0,
            "create_fallback_singleton_attempt_count_total": 0,
            "create_fallback_singleton_failure_count_total": 0,
            "new_update_failure_state_count_total": 0,
            "existing_update_failure_state_count_total": 0,
            "stage_metrics": {"fetch": 0, "planning": 0, "apply": 0, "bulk_flush": 0, "total": 0},
            "avg_per_batch": {
                "source_object_count": 0,
                "tracking_row_count": 0,
                "pending_rule_work_items": 0,
                "pending_bulk_updates": 0,
                "update_fallback_chunk_attempt_count": 0,
                "update_fallback_singleton_attempt_count": 0,
                "update_fallback_singleton_failure_count": 0,
                "create_fallback_chunk_attempt_count": 0,
                "create_fallback_singleton_attempt_count": 0,
                "create_fallback_singleton_failure_count": 0,
                "new_update_failure_state_count": 0,
                "existing_update_failure_state_count": 0,
                "stage_metrics": {"fetch": 0, "planning": 0, "apply": 0, "bulk_flush": 0, "total": 0},
            },
        }

        result = ReconcileDNSBulkJob().run(
            dryrun=False,
            rules=[self.interface_rule],
            limit=1,
            batch_size=1,
            fast_mode=True,
        )

        mock_dns_rule_engine_class.assert_called_once_with(
            execution_mode=ExecutionMode.FAST,
            selected_rules=[self.interface_rule],
        )
        self.assertEqual(result["mode"]["execution_mode"], ExecutionMode.FAST.value)

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_bulk_mode_surfaces_fast_fallback_counters(self, mock_dns_rule_engine_class):
        """Bulk result should expose fast fallback counters from pipeline metrics."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_objects_pipeline.return_value = [ObjectProcessingMetrics()]
        rule_engine.get_pipeline_metrics.return_value = {
            "batches": 1,
            "source_object_count_total": 1,
            "tracking_row_count_total": 1,
            "pending_rule_work_items_total": 1,
            "pending_bulk_updates_total": 1,
            "update_fallback_chunk_attempt_count_total": 3,
            "update_fallback_singleton_attempt_count_total": 7,
            "update_fallback_singleton_failure_count_total": 2,
            "create_fallback_chunk_attempt_count_total": 5,
            "create_fallback_singleton_attempt_count_total": 11,
            "create_fallback_singleton_failure_count_total": 4,
            "new_update_failure_state_count_total": 2,
            "existing_update_failure_state_count_total": 1,
            "stage_metrics": {"fetch": 0, "planning": 0, "apply": 0, "bulk_flush": 0, "total": 0},
            "avg_per_batch": {
                "source_object_count": 1,
                "tracking_row_count": 1,
                "pending_rule_work_items": 1,
                "pending_bulk_updates": 1,
                "update_fallback_chunk_attempt_count": 3,
                "update_fallback_singleton_attempt_count": 7,
                "update_fallback_singleton_failure_count": 2,
                "create_fallback_chunk_attempt_count": 5,
                "create_fallback_singleton_attempt_count": 11,
                "create_fallback_singleton_failure_count": 4,
                "new_update_failure_state_count": 2,
                "existing_update_failure_state_count": 1,
                "stage_metrics": {"fetch": 0, "planning": 0, "apply": 0, "bulk_flush": 0, "total": 0},
            },
        }

        result = ReconcileDNSBulkJob().run(
            dryrun=False,
            source_models=[ContentType.objects.get_for_model(Interface)],
            rules=[self.interface_rule],
            limit=1,
            batch_size=100,
            fast_mode=True,
        )

        self.assertEqual(result["reconciliation"]["update_fallback_chunk_attempt_count"], 3)
        self.assertEqual(result["reconciliation"]["update_fallback_singleton_attempt_count"], 7)
        self.assertEqual(result["reconciliation"]["update_fallback_singleton_failure_count"], 2)
        self.assertEqual(result["reconciliation"]["create_fallback_chunk_attempt_count"], 5)
        self.assertEqual(result["reconciliation"]["create_fallback_singleton_attempt_count"], 11)
        self.assertEqual(result["reconciliation"]["create_fallback_singleton_failure_count"], 4)
        self.assertEqual(result["reconciliation"]["new_update_failure_state_count"], 2)
        self.assertEqual(result["reconciliation"]["existing_update_failure_state_count"], 1)

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_bulk_mode_include_children_includes_child_devices_and_interfaces(self, mock_dns_rule_engine_class):
        """Bulk mode include-children should process child devices and their interfaces from in-scope parents."""
        rule_engine = mock_dns_rule_engine_class.return_value
        rule_engine.process_objects_pipeline.side_effect = lambda model_objects: [
            ObjectProcessingMetrics() for _ in model_objects
        ]
        out_of_scope_location = Location.objects.create(
            name="Bulk Child Device Out-of-Scope",
            location_type=self.location_type,
            status=self.location.status,
        )
        child_device, child_interface = self._create_child_device_with_interface(
            name_prefix="bulk-child-device",
            parent_device=self.device,
            location=out_of_scope_location,
        )
        device_rule = DNSRule.objects.create(
            name="bulk-device-ip-child-reconcile",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )

        result = ReconcileDNSBulkJob().run(
            dryrun=False,
            source_models=[ContentType.objects.get_for_model(Device)],
            rules=[device_rule],
            locations=[self.location],
            include_child_devices=True,
            include_interfaces=True,
            limit=25,
            batch_size=100,
        )

        processed_objects = []
        for call_args in rule_engine.process_objects_pipeline.call_args_list:
            processed_objects.extend(call_args.args[0])

        self.assertIn(child_device, processed_objects)
        self.assertIn(child_interface, processed_objects)
        self.assertTrue(result["mode"]["include_child_devices"])
        self.assertTrue(result["mode"]["include_interfaces"])
        self.assertIn("dcim.device", result["scope"]["scanned_models"])
        self.assertIn("dcim.interface", result["scope"]["scanned_models"])

    @patch("nautobot_dns_models.jobs.DNSRuleEngine")
    def test_invalid_source_model_marks_job_failed(self, mock_dns_rule_engine_class):
        """Submitting an unsupported source model should fail and skip processing."""
        rule_engine = mock_dns_rule_engine_class.return_value
        unsupported_content_type = ContentType.objects.get_for_model(Location)
        unsupported_label = f"{unsupported_content_type.app_label}.{unsupported_content_type.model}"
        result = ReconcileDNSBulkJob().run(
            dryrun=True,
            source_models=[unsupported_content_type],
        )

        # Invalid source model input should fail during validation before any object processing is attempted.
        rule_engine.process_object.assert_not_called()

        self.assertIn("error", result)
        self.assertEqual(result["error"], "invalid_source_models")
        self.assertEqual(result["invalid_source_models"], [unsupported_label])

    def test_invalid_source_model_job_run_reports_failure_status(self):
        """Job helper execution should report STATUS_FAILURE for invalid source model input."""
        unsupported_content_type = ContentType.objects.get_for_model(Location)
        unsupported_label = f"{unsupported_content_type.app_label}.{unsupported_content_type.model}"
        job_result = create_job_result_and_run_job(
            "nautobot_dns_models.jobs",
            "ReconcileDNSBulkJob",
            dryrun=True,
            source_models=[str(unsupported_content_type.pk)],
        )
        self.assertJobResultStatus(job_result, JobResultStatusChoices.STATUS_FAILURE)
        self.assertEqual(job_result.result["error"], "invalid_source_models")
        self.assertEqual(job_result.result["invalid_source_models"], [unsupported_label])

    def test_bulk_rule_source_model_mismatch_fails_fast(self):
        """Bulk mode should fail when selected rules don't match selected source models."""
        result = ReconcileDNSBulkJob().run(
            dryrun=True,
            source_models=[ContentType.objects.get_for_model(Device)],
            rules=[self.interface_rule],
            batch_size=10,
            limit=1,
        )

        self.assertEqual(result["error"], "rules_source_model_mismatch")
        self.assertEqual(result["invalid_rule_ids"], [str(self.interface_rule.pk)])
        self.assertEqual(result["selected_source_models"], ["dcim.device"])

    def test_bulk_location_scope_updates_all_interfaces_in_scoped_location(self):
        """Location-scoped reconcile should update all matching interfaces, not only early PK window rows."""
        self.interface_rule.enabled = False
        self.interface_rule.save(update_fields=["enabled"])

        scoped_location = Location.objects.create(
            name="Scoped Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        benchmark_prefix = Prefix.objects.create(
            network="10.200.0.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )

        all_interfaces = []
        for device_index in range(3):
            device_location = scoped_location if device_index == 2 else self.location
            device = Device.objects.create(
                name=f"scope-device-{device_index}",
                device_type=self.device_type,
                location=device_location,
                role=self.device_role,
                status=self.device_status,
            )
            for interface_index in range(8):
                interface = Interface.objects.create(
                    name=f"eth{interface_index}",
                    device=device,
                    type=self.interface.type,
                    status=self.interface_status,
                )
                all_interfaces.append(interface)

        for address_host, interface in enumerate(all_interfaces, start=1):
            ip_address = IPAddress.objects.create(
                address=f"10.200.0.{address_host}/24",
                status=self.ip_status,
                namespace=self.namespace,
                parent=benchmark_prefix,
            )
            interface.ip_addresses.set([ip_address])

        scoped_rule = DNSRule.objects.create(
            name="scope-arecord-rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}-base",
            value_template="{{ obj.ip_addresses.first() }}",
        )
        scoped_interfaces = Interface.objects.filter(device__location=scoped_location).order_by("pk")
        self.assertEqual(scoped_interfaces.count(), 8)

        # Prime DNSRuleRecord rows so the second run is a true update-path reconcile.
        primer = ReconcileDNSBulkJob().run(
            dryrun=False,
            source_models=[ContentType.objects.get_for_model(Interface)],
            rules=[scoped_rule],
            locations=[scoped_location],
            limit=None,
            batch_size=1000,
        )
        self.assertEqual(primer["execution"]["targets_selected_count"], 8)

        scoped_rule.name_template = "{{ obj.device.name }}-{{ obj.name }}-updated"
        scoped_rule.save()

        # Limit is intentionally smaller than total interfaces so this exercises in-scope limit semantics.
        result = ReconcileDNSBulkJob().run(
            dryrun=False,
            source_models=[ContentType.objects.get_for_model(Interface)],
            rules=[scoped_rule],
            locations=[scoped_location],
            limit=20,
            batch_size=1000,
        )
        self.assertEqual(result["execution"]["targets_selected_count"], 8)
        self.assertEqual(result["execution"]["targets_processed_count"], 8)
        self.assertEqual(result["reconciliation"]["objects_changed"], 8)

    def test_bulk_location_same_device_name_diff_tenant_only_fails_on_true_arecord_key_collision(self):
        """Bulk create should only fail when A-record key collides on name+zone+address."""
        scoped_location = Location.objects.create(
            name="Bulk Conflict Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        tenant_b = Tenant.objects.create(name="Bulk Conflict Tenant B", tenant_group=self.tenant_group)

        shared_device_name = "bulk-conflict-device"
        interface_name = "eth-collision"
        shared_ip = self.ip_addresses[0]
        candidate_record_name = f"{shared_device_name}-{interface_name}"

        collision_rule = DNSRule.objects.create(
            name="bulk-location-collision-create-test",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=False,
        )

        device_a = Device.objects.create(
            name=shared_device_name,
            device_type=self.device_type,
            location=scoped_location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        device_b = Device.objects.create(
            name=shared_device_name,
            device_type=self.device_type,
            location=scoped_location,
            tenant=tenant_b,
            role=self.device_role,
            status=self.device_status,
        )

        interface_a = Interface.objects.create(
            name=interface_name,
            device=device_a,
            type=self.interface.type,
            status=self.interface_status,
        )
        interface_b = Interface.objects.create(
            name=interface_name,
            device=device_b,
            type=self.interface.type,
            status=self.interface_status,
        )
        interface_a.ip_addresses.add(shared_ip)
        interface_b.ip_addresses.add(shared_ip)

        ARecord.objects.filter(name=candidate_record_name, zone=self.dns_zone, address=shared_ip).delete()
        collision_rule.enabled = True
        collision_rule.save(update_fields=["enabled"])

        result = ReconcileDNSBulkJob().run(
            dryrun=False,
            source_models=[ContentType.objects.get_for_model(Interface)],
            rules=[collision_rule],
            locations=[scoped_location],
            limit=None,
            batch_size=100,
            fast_mode=False,
        )

        self.assertEqual(result["execution"]["targets_selected_count"], 2)
        self.assertEqual(result["execution"]["targets_processed_count"], 2)
        # One create succeeds, second collides on (name, address, zone) and is skipped.
        self.assertEqual(result["reconciliation"]["dns_record_create_count"], 1)
        self.assertEqual(
            ARecord.objects.filter(name=candidate_record_name, zone=self.dns_zone, address=shared_ip).count(),
            1,
        )
        self.assertEqual(
            DNSRuleRecord.objects.filter(
                rule=collision_rule,
                object_id__in=[interface_a.id, interface_b.id],
            ).count(),
            1,
        )
        # Ensure unselected enabled rules are not executed for this bulk run.
        self.assertEqual(
            DNSRuleRecord.objects.filter(
                rule=self.interface_rule,
                object_id__in=[interface_a.id, interface_b.id],
            ).count(),
            0,
        )

    def test_bulk_rule_filter_excludes_unselected_enabled_rules_end_to_end(self):
        """Bulk run should execute only explicitly selected rules."""
        scoped_location = Location.objects.create(
            name="Rule Filter Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        target_device_name = "rule-filter-device"
        target_interface_name = "eth-filter"
        target_ip = self.ip_addresses[0]

        target_device = Device.objects.create(
            name=target_device_name,
            device_type=self.device_type,
            location=scoped_location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        target_interface = Interface.objects.create(
            name=target_interface_name,
            device=target_device,
            type=self.interface.type,
            status=self.interface_status,
        )
        target_interface.ip_addresses.add(target_ip)

        selected_rule = DNSRule.objects.create(
            name="bulk-selected-only-rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}-selected",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )
        unselected_rule = DNSRule.objects.create(
            name="bulk-unselected-enabled-rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}-unselected",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

        selected_name = f"{target_device_name}-{target_interface_name}-selected"
        unselected_name = f"{target_device_name}-{target_interface_name}-unselected"
        ARecord.objects.filter(
            name__in=[selected_name, unselected_name], zone=self.dns_zone, address=target_ip
        ).delete()
        DNSRuleRecord.objects.filter(rule__in=[selected_rule, unselected_rule], object_id=target_interface.id).delete()

        result = ReconcileDNSBulkJob().run(
            dryrun=False,
            source_models=[ContentType.objects.get_for_model(Interface)],
            rules=[selected_rule],
            locations=[scoped_location],
            limit=None,
            batch_size=100,
            fast_mode=False,
        )

        self.assertEqual(result["execution"]["targets_selected_count"], 1)
        self.assertEqual(result["execution"]["targets_processed_count"], 1)
        self.assertEqual(result["reconciliation"]["dns_record_create_count"], 1)
        self.assertTrue(ARecord.objects.filter(name=selected_name, zone=self.dns_zone, address=target_ip).exists())
        self.assertFalse(ARecord.objects.filter(name=unselected_name, zone=self.dns_zone, address=target_ip).exists())
        self.assertEqual(DNSRuleRecord.objects.filter(rule=selected_rule, object_id=target_interface.id).count(), 1)
        self.assertEqual(DNSRuleRecord.objects.filter(rule=unselected_rule, object_id=target_interface.id).count(), 0)


class ScopeSelectionTestCase(BaseRuleEngineMixin, TransactionTestCase):
    """Validate SQL scope selection parity with engine semantics."""

    @classmethod
    def setUpTestData(cls):
        """Set up fixtures required for interface scope selection tests."""
        super().setUpTestData()
        cls.interface.ip_addresses.set([cls.ip_addresses[0]])

    def setUp(self):
        """Rebuild fixtures per test under TransactionTestCase semantics."""
        # Keep ContentType cache aligned with recreated test DB state.
        ContentType.objects.clear_cache()
        TransactionTestCase.setUp(self)
        type(self).setUpTestData()
        BaseRuleEngineMixin.setUp(self)

    @staticmethod
    def _scope_expected_ids_from_engine(objects, location_ids, tenant_ids=None):
        """Return expected object IDs via engine scope-resolution semantics."""
        tenant_ids = tenant_ids or set()
        rule_engine = DNSRuleEngine()
        expected_ids = set()
        for obj in objects:
            object_location = rule_engine._resolver.get_object_location(obj)  # pylint: disable=protected-access
            object_tenant = rule_engine._resolver.get_object_tenant(obj)  # pylint: disable=protected-access

            if location_ids and (object_location is None or object_location.id not in location_ids):
                continue

            if tenant_ids and (object_tenant is None or object_tenant.id not in tenant_ids):
                continue

            expected_ids.add(obj.id)

        return expected_ids

    def _scope_actual_ids(self, *, target_model_class, location_ids, tenant_ids=None):
        """Return object IDs selected by the bulk job scope pipeline path."""
        tenant_ids = tenant_ids or set()
        job = ReconcileDNSBulkJob()
        summary = ReconcileRunSummary()
        targets = list(
            job._iter_targets(  # pylint: disable=protected-access
                target_models=[target_model_class],
                batch_size=1000,
                limit=20000,
                location_ids=location_ids,
                tenant_ids=tenant_ids,
            )
        )
        selected_targets = job._build_limited_target_list(  # pylint: disable=protected-access
            targets,
            summary=summary,
            dryrun=True,
            limit=20000,
        )
        return {obj.id for _, obj in selected_targets}

    def _create_device_with_interface(self, *, name_prefix, location, tenant=None):
        """Create one device and one interface for scope-selection assertions."""
        device = Device.objects.create(
            name=f"{name_prefix}-device",
            device_type=self.device_type,
            location=location,
            tenant=tenant,
            role=self.device_role,
            status=self.device_status,
        )
        interface = Interface.objects.create(
            name=f"{name_prefix}-eth0",
            device=device,
            type=self.interface.type,
            status=self.interface_status,
        )
        return interface

    def _create_device_only(self, *, name_prefix, location, tenant=None):
        """Create one device for scope-selection assertions."""
        return Device.objects.create(
            name=f"{name_prefix}-device-only",
            device_type=self.device_type,
            location=location,
            tenant=tenant,
            role=self.device_role,
            status=self.device_status,
        )

    def _create_virtual_machine_only(self, *, name_prefix, cluster_location, cluster_tenant=None, vm_tenant=None):
        """Create one virtual machine for scope-selection assertions."""
        cluster = Cluster.objects.create(
            name=f"{name_prefix}-cluster",
            cluster_type=self.cluster_type,
            location=cluster_location,
            tenant=cluster_tenant,
        )
        return VirtualMachine.objects.create(
            cluster=cluster,
            name=f"{name_prefix}-vm",
            status=self.vm_status,
            tenant=vm_tenant,
        )

    @staticmethod
    def _create_vminterface_only(*, name_prefix, virtual_machine):
        """Create one VM interface for scope-selection assertions."""
        vm_interface_status = Status.objects.get_for_model(VMInterface).first()
        return VMInterface.objects.create(
            name=f"{name_prefix}-vmi0",
            virtual_machine=virtual_machine,
            status=vm_interface_status,
        )

    @staticmethod
    def _create_service_only(*, name_prefix, device=None, virtual_machine=None):
        """Create one Service for scope-selection assertions."""
        return Service.objects.create(
            name=f"{name_prefix}-svc",
            protocol="TCP",
            ports=[8443],
            device=device,
            virtual_machine=virtual_machine,
        )

    def test_device_scope_matches_engine_semantics(self):
        """Scoped device selection should match engine semantics for location filtering."""
        scoped_location = Location.objects.create(
            name="Scope Device Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        extra_location = Location.objects.create(
            name="Scope Device Extra Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        devices_in_scope = [
            self._create_device_only(name_prefix="device-in-1", location=scoped_location),
            self._create_device_only(name_prefix="device-in-2", location=scoped_location),
            self._create_device_only(name_prefix="device-in-3", location=scoped_location),
        ]
        devices_out_scope = [
            self._create_device_only(name_prefix="device-out-1", location=self.location),
            self._create_device_only(name_prefix="device-out-2", location=extra_location),
        ]
        created_devices = devices_in_scope + devices_out_scope
        location_ids = {scoped_location.id}

        expected_ids = {obj.id for obj in devices_in_scope}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_devices, location_ids)
        actual_ids = self._scope_actual_ids(target_model_class=Device, location_ids=location_ids) & {
            obj.id for obj in created_devices
        }
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_device_scope_tenant_matches_engine_semantics(self):
        """Scoped device selection should match engine semantics for tenant filtering."""
        other_tenant = Tenant.objects.create(name="Scope Device Other Tenant", tenant_group=self.tenant_group)
        devices_in_scope = [
            self._create_device_only(name_prefix="device-tenant-in-1", location=self.location, tenant=self.tenant),
            self._create_device_only(name_prefix="device-tenant-in-2", location=self.location, tenant=self.tenant),
        ]
        devices_out_scope = [
            self._create_device_only(name_prefix="device-tenant-out-1", location=self.location, tenant=other_tenant),
            self._create_device_only(name_prefix="device-tenant-out-2", location=self.location, tenant=None),
        ]
        created_devices = devices_in_scope + devices_out_scope
        location_ids = set()
        tenant_ids = {self.tenant.id}

        expected_ids = {obj.id for obj in devices_in_scope}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_devices, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=Device,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_devices}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_device_scope_location_and_tenant_matches_engine_semantics(self):
        """Scoped device selection should match engine semantics for location+tenant filtering."""
        scoped_location = Location.objects.create(
            name="Scope Device Location+Tenant",
            location_type=self.location_type,
            status=self.location.status,
        )
        other_tenant = Tenant.objects.create(name="Scope Device Combo Other Tenant", tenant_group=self.tenant_group)
        in_scope = self._create_device_only(
            name_prefix="device-combo-in",
            location=scoped_location,
            tenant=self.tenant,
        )
        out_scope = [
            self._create_device_only(
                name_prefix="device-combo-out-location",
                location=self.location,
                tenant=self.tenant,
            ),
            self._create_device_only(
                name_prefix="device-combo-out-tenant",
                location=scoped_location,
                tenant=other_tenant,
            ),
            self._create_device_only(
                name_prefix="device-combo-out-none",
                location=scoped_location,
                tenant=None,
            ),
        ]
        created_devices = [in_scope] + out_scope
        location_ids = {scoped_location.id}
        tenant_ids = {self.tenant.id}

        expected_ids = {in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_devices, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=Device,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_devices}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_device_target_queryset_avoids_n_plus_one(self):
        """Device target queryset should not emit per-object relation queries when iterated."""
        job = ReconcileDNSBulkJob()
        tenant = Tenant.objects.create(name="N+1 Device Tenant", tenant_group=self.tenant_group)
        prefix = "device-n-plus-one"
        device_counts = (2, 8)
        query_counts = []

        for count in device_counts:
            for index in range(count):
                device = self._create_device_only(
                    name_prefix=f"{prefix}-{count}-{index}",
                    location=self.location,
                    tenant=tenant,
                )
                device.primary_ip4 = self.ip_addresses[0]
                device.primary_ip6 = self.ipv6_addresses[0]
                device.save(update_fields=["primary_ip4", "primary_ip6"])

            queryset = job._build_target_queryset(  # pylint: disable=protected-access
                Device,
                location_ids=set(),
                tenant_ids=set(),
            )
            queryset = queryset.filter(name__startswith=f"{prefix}-{count}-").order_by("pk")

            with CaptureQueriesContext(connection) as queries:
                for device in queryset:
                    _ = device.location
                    _ = device.tenant
                    _ = device.primary_ip4
                    _ = device.primary_ip6

            query_counts.append(len(queries.captured_queries))

        self.assertEqual(query_counts[0], query_counts[1])

    def test_virtualmachine_scope_location_matches_engine_semantics(self):
        """Scoped VM selection should match engine semantics for location filtering."""
        scoped_location = Location.objects.create(
            name="Scope VM Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        extra_location = Location.objects.create(
            name="Scope VM Extra Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        vms_in_scope = [
            self._create_virtual_machine_only(name_prefix="vm-in-1", cluster_location=scoped_location),
            self._create_virtual_machine_only(name_prefix="vm-in-2", cluster_location=scoped_location),
        ]
        vms_out_scope = [
            self._create_virtual_machine_only(name_prefix="vm-out-1", cluster_location=self.location),
            self._create_virtual_machine_only(name_prefix="vm-out-2", cluster_location=extra_location),
        ]
        created_vms = vms_in_scope + vms_out_scope
        location_ids = {scoped_location.id}

        expected_ids = {obj.id for obj in vms_in_scope}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_vms, location_ids)
        actual_ids = self._scope_actual_ids(target_model_class=VirtualMachine, location_ids=location_ids) & {
            obj.id for obj in created_vms
        }
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_virtualmachine_scope_location_and_tenant_matches_engine_semantics(self):
        """Scoped VM selection should match engine semantics for location+tenant filtering."""
        scoped_location = Location.objects.create(
            name="Scope VM Location+Tenant",
            location_type=self.location_type,
            status=self.location.status,
        )
        other_tenant = Tenant.objects.create(name="Scope VM Combo Other Tenant", tenant_group=self.tenant_group)
        vm_in_scope = self._create_virtual_machine_only(
            name_prefix="vm-combo-in",
            cluster_location=scoped_location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_out_scope = [
            self._create_virtual_machine_only(
                name_prefix="vm-combo-out-location",
                cluster_location=self.location,
                cluster_tenant=self.tenant,
                vm_tenant=None,
            ),
            self._create_virtual_machine_only(
                name_prefix="vm-combo-out-tenant-fallback",
                cluster_location=scoped_location,
                cluster_tenant=other_tenant,
                vm_tenant=None,
            ),
            self._create_virtual_machine_only(
                name_prefix="vm-combo-out-tenant-override",
                cluster_location=scoped_location,
                cluster_tenant=self.tenant,
                vm_tenant=other_tenant,
            ),
        ]
        created_vms = [vm_in_scope] + vm_out_scope
        location_ids = {scoped_location.id}
        tenant_ids = {self.tenant.id}

        expected_ids = {vm_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_vms, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=VirtualMachine,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_vms}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_virtualmachine_target_queryset_avoids_n_plus_one(self):
        """VM target queryset should not emit per-object relation queries when iterated."""
        job = ReconcileDNSBulkJob()
        tenant = Tenant.objects.create(name="N+1 VM Tenant", tenant_group=self.tenant_group)
        prefix = "vm-n-plus-one"
        vm_counts = (2, 8)
        query_counts = []

        for count in vm_counts:
            for index in range(count):
                vm = self._create_virtual_machine_only(
                    name_prefix=f"{prefix}-{count}-{index}",
                    cluster_location=self.location,
                    cluster_tenant=tenant,
                    vm_tenant=tenant,
                )
                vm.primary_ip4 = self.ip_addresses[0]
                vm.primary_ip6 = self.ipv6_addresses[0]
                vm.save(update_fields=["primary_ip4", "primary_ip6"])

            queryset = job._build_target_queryset(  # pylint: disable=protected-access
                VirtualMachine,
                location_ids=set(),
                tenant_ids=set(),
            )
            queryset = queryset.filter(name__startswith=f"{prefix}-{count}-").order_by("pk")

            with CaptureQueriesContext(connection) as queries:
                for vm in queryset:
                    # Exercise the relation paths used by scope and reconcile flows.
                    _ = vm.cluster
                    _ = vm.cluster.location
                    _ = vm.cluster.tenant
                    _ = vm.tenant
                    _ = vm.primary_ip4
                    _ = vm.primary_ip6

            query_counts.append(len(queries.captured_queries))

        self.assertEqual(query_counts[0], query_counts[1])

    def test_vminterface_scope_location_matches_engine_semantics(self):
        """Scoped VMInterface selection should match engine semantics for location filtering."""
        scoped_location = Location.objects.create(
            name="Scope VMI Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        extra_location = Location.objects.create(
            name="Scope VMI Extra Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        vm_in_scope = self._create_virtual_machine_only(
            name_prefix="vmi-vm-in",
            cluster_location=scoped_location,
        )
        vm_out_scope = self._create_virtual_machine_only(
            name_prefix="vmi-vm-out",
            cluster_location=self.location,
        )
        vm_out_scope_extra = self._create_virtual_machine_only(
            name_prefix="vmi-vm-out-extra",
            cluster_location=extra_location,
        )
        vmi_in_scope = self._create_vminterface_only(name_prefix="vmi-in", virtual_machine=vm_in_scope)
        vmi_out_scope = self._create_vminterface_only(name_prefix="vmi-out", virtual_machine=vm_out_scope)
        vmi_out_scope_extra = self._create_vminterface_only(
            name_prefix="vmi-out-extra",
            virtual_machine=vm_out_scope_extra,
        )
        created_vm_interfaces = [vmi_in_scope, vmi_out_scope, vmi_out_scope_extra]
        location_ids = {scoped_location.id}

        expected_ids = {vmi_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_vm_interfaces, location_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=VMInterface,
            location_ids=location_ids,
        ) & {obj.id for obj in created_vm_interfaces}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_vminterface_scope_tenant_fallback_matches_engine_semantics(self):
        """Scoped VMInterface selection should match engine semantics for tenant filtering."""
        other_tenant = Tenant.objects.create(name="Scope VMI Other Tenant", tenant_group=self.tenant_group)
        vm_fallback_in_scope = self._create_virtual_machine_only(
            name_prefix="vmi-tenant-fallback-in",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_direct_in_scope = self._create_virtual_machine_only(
            name_prefix="vmi-tenant-direct-in",
            cluster_location=self.location,
            cluster_tenant=other_tenant,
            vm_tenant=self.tenant,
        )
        vm_fallback_out_scope = self._create_virtual_machine_only(
            name_prefix="vmi-tenant-fallback-out",
            cluster_location=self.location,
            cluster_tenant=other_tenant,
            vm_tenant=None,
        )
        vm_direct_out_scope = self._create_virtual_machine_only(
            name_prefix="vmi-tenant-direct-out",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=other_tenant,
        )
        created_vm_interfaces = [
            self._create_vminterface_only(name_prefix="vmi-tenant-fallback-in", virtual_machine=vm_fallback_in_scope),
            self._create_vminterface_only(name_prefix="vmi-tenant-direct-in", virtual_machine=vm_direct_in_scope),
            self._create_vminterface_only(name_prefix="vmi-tenant-fallback-out", virtual_machine=vm_fallback_out_scope),
            self._create_vminterface_only(name_prefix="vmi-tenant-direct-out", virtual_machine=vm_direct_out_scope),
        ]
        location_ids = set()
        tenant_ids = {self.tenant.id}

        expected_ids = {created_vm_interfaces[0].id, created_vm_interfaces[1].id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_vm_interfaces, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=VMInterface,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_vm_interfaces}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_vminterface_scope_location_and_tenant_matches_engine_semantics(self):
        """Scoped VMInterface selection should match engine semantics for location+tenant filtering."""
        scoped_location = Location.objects.create(
            name="Scope VMI Location+Tenant",
            location_type=self.location_type,
            status=self.location.status,
        )
        other_tenant = Tenant.objects.create(name="Scope VMI Combo Other Tenant", tenant_group=self.tenant_group)
        vm_in_scope = self._create_virtual_machine_only(
            name_prefix="vmi-combo-in",
            cluster_location=scoped_location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_out_scope_location = self._create_virtual_machine_only(
            name_prefix="vmi-combo-out-location",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_out_scope_tenant_fallback = self._create_virtual_machine_only(
            name_prefix="vmi-combo-out-tenant-fallback",
            cluster_location=scoped_location,
            cluster_tenant=other_tenant,
            vm_tenant=None,
        )
        vm_out_scope_tenant_override = self._create_virtual_machine_only(
            name_prefix="vmi-combo-out-tenant-override",
            cluster_location=scoped_location,
            cluster_tenant=self.tenant,
            vm_tenant=other_tenant,
        )
        vmi_in_scope = self._create_vminterface_only(name_prefix="vmi-combo-in", virtual_machine=vm_in_scope)
        vmi_out_scope = [
            self._create_vminterface_only(name_prefix="vmi-combo-out-location", virtual_machine=vm_out_scope_location),
            self._create_vminterface_only(
                name_prefix="vmi-combo-out-tenant-fallback",
                virtual_machine=vm_out_scope_tenant_fallback,
            ),
            self._create_vminterface_only(
                name_prefix="vmi-combo-out-tenant-override",
                virtual_machine=vm_out_scope_tenant_override,
            ),
        ]
        created_vm_interfaces = [vmi_in_scope] + vmi_out_scope
        location_ids = {scoped_location.id}
        tenant_ids = {self.tenant.id}

        expected_ids = {vmi_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_vm_interfaces, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=VMInterface,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_vm_interfaces}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_vminterface_target_queryset_avoids_n_plus_one(self):
        """VMInterface target queryset should not emit per-object relation queries when iterated."""
        job = ReconcileDNSBulkJob()
        tenant = Tenant.objects.create(name="N+1 VMInterface Tenant", tenant_group=self.tenant_group)
        prefix = "vmi-n-plus-one"
        interface_counts = (2, 8)
        query_counts = []

        for count in interface_counts:
            for index in range(count):
                vm = self._create_virtual_machine_only(
                    name_prefix=f"{prefix}-vm-{count}-{index}",
                    cluster_location=self.location,
                    cluster_tenant=tenant,
                    vm_tenant=tenant,
                )
                vm_interface = self._create_vminterface_only(
                    name_prefix=f"{prefix}-{count}-{index}",
                    virtual_machine=vm,
                )
                vm_interface.ip_addresses.set([self.ip_addresses[0]])

            queryset = job._build_target_queryset(  # pylint: disable=protected-access
                VMInterface,
                location_ids=set(),
                tenant_ids=set(),
            )
            queryset = queryset.filter(name__startswith=f"{prefix}-{count}-").order_by("pk")

            with CaptureQueriesContext(connection) as queries:
                for vm_interface in queryset:
                    _ = vm_interface.virtual_machine
                    _ = vm_interface.virtual_machine.cluster
                    _ = vm_interface.virtual_machine.cluster.location
                    _ = vm_interface.virtual_machine.cluster.tenant
                    _ = vm_interface.virtual_machine.tenant
                    _ = list(vm_interface.ip_addresses.all())

            query_counts.append(len(queries.captured_queries))

        self.assertEqual(query_counts[0], query_counts[1])

    def test_service_scope_location_matches_engine_semantics(self):
        """Scoped Service selection should match engine semantics for location filtering."""
        scoped_location = Location.objects.create(
            name="Scope Service Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        extra_location = Location.objects.create(
            name="Scope Service Extra Location",
            location_type=self.location_type,
            status=self.location.status,
        )

        device_in_scope = self._create_device_only(
            name_prefix="service-device-in",
            location=scoped_location,
        )
        device_out_scope = self._create_device_only(
            name_prefix="service-device-out",
            location=self.location,
        )
        vm_in_scope = self._create_virtual_machine_only(
            name_prefix="service-vm-in",
            cluster_location=scoped_location,
        )
        vm_out_scope = self._create_virtual_machine_only(
            name_prefix="service-vm-out",
            cluster_location=extra_location,
        )
        created_services = [
            self._create_service_only(name_prefix="service-loc-in-device", device=device_in_scope),
            self._create_service_only(name_prefix="service-loc-in-vm", virtual_machine=vm_in_scope),
            self._create_service_only(name_prefix="service-loc-out-device", device=device_out_scope),
            self._create_service_only(name_prefix="service-loc-out-vm", virtual_machine=vm_out_scope),
        ]
        location_ids = {scoped_location.id}

        expected_ids = {created_services[0].id, created_services[1].id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_services, location_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=Service,
            location_ids=location_ids,
        ) & {obj.id for obj in created_services}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_service_scope_tenant_matches_engine_semantics(self):
        """Scoped Service selection should match engine semantics for tenant filtering."""
        other_tenant = Tenant.objects.create(name="Scope Service Other Tenant", tenant_group=self.tenant_group)

        device_in_scope = self._create_device_only(
            name_prefix="service-tenant-device-in",
            location=self.location,
            tenant=self.tenant,
        )
        device_out_scope = self._create_device_only(
            name_prefix="service-tenant-device-out",
            location=self.location,
            tenant=other_tenant,
        )
        vm_fallback_in_scope = self._create_virtual_machine_only(
            name_prefix="service-tenant-vm-fallback-in",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_direct_in_scope = self._create_virtual_machine_only(
            name_prefix="service-tenant-vm-direct-in",
            cluster_location=self.location,
            cluster_tenant=other_tenant,
            vm_tenant=self.tenant,
        )
        vm_fallback_out_scope = self._create_virtual_machine_only(
            name_prefix="service-tenant-vm-fallback-out",
            cluster_location=self.location,
            cluster_tenant=other_tenant,
            vm_tenant=None,
        )
        vm_direct_out_scope = self._create_virtual_machine_only(
            name_prefix="service-tenant-vm-direct-out",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=other_tenant,
        )
        created_services = [
            self._create_service_only(name_prefix="service-tenant-device-in", device=device_in_scope),
            self._create_service_only(name_prefix="service-tenant-device-out", device=device_out_scope),
            self._create_service_only(
                name_prefix="service-tenant-vm-fallback-in", virtual_machine=vm_fallback_in_scope
            ),
            self._create_service_only(name_prefix="service-tenant-vm-direct-in", virtual_machine=vm_direct_in_scope),
            self._create_service_only(
                name_prefix="service-tenant-vm-fallback-out", virtual_machine=vm_fallback_out_scope
            ),
            self._create_service_only(name_prefix="service-tenant-vm-direct-out", virtual_machine=vm_direct_out_scope),
        ]
        location_ids = set()
        tenant_ids = {self.tenant.id}

        expected_ids = {created_services[0].id, created_services[2].id, created_services[3].id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_services, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=Service,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_services}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_service_scope_location_and_tenant_matches_engine_semantics(self):
        """Scoped Service selection should match engine semantics for location+tenant filtering."""
        scoped_location = Location.objects.create(
            name="Scope Service Location+Tenant",
            location_type=self.location_type,
            status=self.location.status,
        )
        other_tenant = Tenant.objects.create(name="Scope Service Combo Other Tenant", tenant_group=self.tenant_group)

        device_in_scope = self._create_device_only(
            name_prefix="service-combo-device-in",
            location=scoped_location,
            tenant=self.tenant,
        )
        device_out_scope_location = self._create_device_only(
            name_prefix="service-combo-device-out-location",
            location=self.location,
            tenant=self.tenant,
        )
        device_out_scope_tenant = self._create_device_only(
            name_prefix="service-combo-device-out-tenant",
            location=scoped_location,
            tenant=other_tenant,
        )
        vm_in_scope = self._create_virtual_machine_only(
            name_prefix="service-combo-vm-in",
            cluster_location=scoped_location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_out_scope_location = self._create_virtual_machine_only(
            name_prefix="service-combo-vm-out-location",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_out_scope_tenant_fallback = self._create_virtual_machine_only(
            name_prefix="service-combo-vm-out-tenant-fallback",
            cluster_location=scoped_location,
            cluster_tenant=other_tenant,
            vm_tenant=None,
        )
        vm_out_scope_tenant_override = self._create_virtual_machine_only(
            name_prefix="service-combo-vm-out-tenant-override",
            cluster_location=scoped_location,
            cluster_tenant=self.tenant,
            vm_tenant=other_tenant,
        )
        created_services = [
            self._create_service_only(name_prefix="service-combo-device-in", device=device_in_scope),
            self._create_service_only(
                name_prefix="service-combo-device-out-location", device=device_out_scope_location
            ),
            self._create_service_only(name_prefix="service-combo-device-out-tenant", device=device_out_scope_tenant),
            self._create_service_only(name_prefix="service-combo-vm-in", virtual_machine=vm_in_scope),
            self._create_service_only(
                name_prefix="service-combo-vm-out-location", virtual_machine=vm_out_scope_location
            ),
            self._create_service_only(
                name_prefix="service-combo-vm-out-tenant-fallback",
                virtual_machine=vm_out_scope_tenant_fallback,
            ),
            self._create_service_only(
                name_prefix="service-combo-vm-out-tenant-override",
                virtual_machine=vm_out_scope_tenant_override,
            ),
        ]
        location_ids = {scoped_location.id}
        tenant_ids = {self.tenant.id}

        expected_ids = {created_services[0].id, created_services[3].id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_services, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=Service,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_services}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_service_target_queryset_avoids_n_plus_one(self):
        """Service target queryset should not emit per-object relation queries when iterated."""
        job = ReconcileDNSBulkJob()
        tenant = Tenant.objects.create(name="N+1 Service Tenant", tenant_group=self.tenant_group)
        prefix = "service-n-plus-one"
        service_counts = (2, 8)
        query_counts = []

        for count in service_counts:
            count_prefix = f"{prefix}-{count}"
            for index in range(count):
                device = self._create_device_only(
                    name_prefix=f"{count_prefix}-device-{index}",
                    location=self.location,
                    tenant=tenant,
                )
                vm = self._create_virtual_machine_only(
                    name_prefix=f"{count_prefix}-vm-{index}",
                    cluster_location=self.location,
                    cluster_tenant=tenant,
                    vm_tenant=tenant,
                )
                self._create_service_only(name_prefix=f"{count_prefix}-device-{index}", device=device)
                self._create_service_only(name_prefix=f"{count_prefix}-vm-{index}", virtual_machine=vm)

            queryset = job._build_target_queryset(  # pylint: disable=protected-access
                Service,
                location_ids=set(),
                tenant_ids=set(),
            )
            queryset = queryset.filter(name__startswith=f"{count_prefix}-").order_by("pk")

            with CaptureQueriesContext(connection) as queries:
                for service in queryset:
                    _ = service.device
                    _ = service.virtual_machine

                    if service.device:
                        _ = service.device.location
                        _ = service.device.tenant

                    if service.virtual_machine:
                        _ = service.virtual_machine.tenant
                        _ = service.virtual_machine.cluster
                        _ = service.virtual_machine.cluster.location
                        _ = service.virtual_machine.cluster.tenant

            query_counts.append(len(queries.captured_queries))

        self.assertEqual(query_counts[0], query_counts[1])

    def test_virtualmachine_scope_tenant_fallback_matches_engine_semantics(self):
        """Scoped VM selection should match engine semantics for VM-tenant fallback behavior."""
        other_tenant = Tenant.objects.create(name="Scope VM Other Tenant", tenant_group=self.tenant_group)

        vm_fallback_in_scope = self._create_virtual_machine_only(
            name_prefix="vm-tenant-fallback-in",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=None,
        )
        vm_direct_in_scope = self._create_virtual_machine_only(
            name_prefix="vm-tenant-direct-in",
            cluster_location=self.location,
            cluster_tenant=other_tenant,
            vm_tenant=self.tenant,
        )
        vm_fallback_out_scope = self._create_virtual_machine_only(
            name_prefix="vm-tenant-fallback-out",
            cluster_location=self.location,
            cluster_tenant=other_tenant,
            vm_tenant=None,
        )
        vm_direct_out_scope = self._create_virtual_machine_only(
            name_prefix="vm-tenant-direct-out",
            cluster_location=self.location,
            cluster_tenant=self.tenant,
            vm_tenant=other_tenant,
        )
        created_vms = [
            vm_fallback_in_scope,
            vm_direct_in_scope,
            vm_fallback_out_scope,
            vm_direct_out_scope,
        ]
        location_ids = set()
        tenant_ids = {self.tenant.id}

        expected_ids = {vm_fallback_in_scope.id, vm_direct_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_vms, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=VirtualMachine,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {obj.id for obj in created_vms}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def _create_child_device_with_interface(self, *, name_prefix, parent_device, location):
        """Create one child device installed in parent device bay and one interface."""
        child_device = Device.objects.create(
            name=f"{name_prefix}-child-device",
            device_type=self.device_type,
            location=location,
            role=self.device_role,
            status=self.device_status,
        )
        device_bay = DeviceBay.objects.create(
            device=parent_device,
            name=f"{name_prefix}-bay0",
            installed_device=child_device,
        )
        # Ensure relation assignment is materialized before creating interface assertions.
        self.assertEqual(device_bay.installed_device_id, child_device.id)
        interface = Interface.objects.create(
            name=f"{name_prefix}-child-eth0",
            device=child_device,
            type=self.interface.type,
            status=self.interface_status,
        )
        return interface

    def _create_module_interface(self, *, name_prefix, parent_device):
        """Create one module on device and one module-backed interface."""
        module_status = Status.objects.get_for_model(Module).first()
        module_type = ModuleType.objects.create(
            manufacturer=self.manufacturer,
            model=f"{name_prefix}-module-type",
        )
        root_bay = ModuleBay.objects.create(
            parent_device=parent_device,
            name=f"{name_prefix}-module-bay0",
        )
        module = Module.objects.create(
            module_type=module_type,
            parent_module_bay=root_bay,
            status=module_status,
        )
        interface = Interface.objects.create(
            name=f"{name_prefix}-module-eth0",
            module=module,
            device=None,
            type=self.interface.type,
            status=self.interface_status,
        )
        return interface

    def _create_nested_module_interface(self, *, name_prefix, parent_device):
        """Create module-in-module topology and one nested module-backed interface."""
        module_status = Status.objects.get_for_model(Module).first()
        module_type = ModuleType.objects.create(
            manufacturer=self.manufacturer,
            model=f"{name_prefix}-nested-module-type",
        )
        root_bay = ModuleBay.objects.create(
            parent_device=parent_device,
            name=f"{name_prefix}-root-bay",
        )
        root_module = Module.objects.create(
            module_type=module_type,
            parent_module_bay=root_bay,
            status=module_status,
        )
        nested_bay = ModuleBay.objects.create(
            parent_module=root_module,
            name=f"{name_prefix}-nested-bay",
        )
        nested_module = Module.objects.create(
            module_type=module_type,
            parent_module_bay=nested_bay,
            status=module_status,
        )
        interface = Interface.objects.create(
            name=f"{name_prefix}-nested-module-eth0",
            module=nested_module,
            device=None,
            type=self.interface.type,
            status=self.interface_status,
        )
        return interface

    def test_interface_scope_plain_device_matches_engine_semantics(self):
        """Scoped interface selection should match engine semantics for plain device interfaces."""
        scoped_location = Location.objects.create(
            name="Scope Plain Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        interface_in_scope = self._create_device_with_interface(name_prefix="plain-in", location=scoped_location)
        interface_out_scope = self._create_device_with_interface(name_prefix="plain-out", location=self.location)
        created_interfaces = [interface_in_scope, interface_out_scope]
        location_ids = {scoped_location.id}

        expected_ids = {interface_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_interfaces, location_ids)
        actual_ids = self._scope_actual_ids(target_model_class=Interface, location_ids=location_ids) & {
            interface.id for interface in created_interfaces
        }
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_interface_scope_plain_device_tenant_matches_engine_semantics(self):
        """Scoped interface selection should match engine semantics for tenant filtering."""
        other_tenant = Tenant.objects.create(name="Scope Interface Other Tenant", tenant_group=self.tenant_group)
        interface_in_scope = self._create_device_with_interface(
            name_prefix="plain-tenant-in",
            location=self.location,
            tenant=self.tenant,
        )
        interface_out_scope = self._create_device_with_interface(
            name_prefix="plain-tenant-out",
            location=self.location,
            tenant=other_tenant,
        )
        interface_out_scope_none = self._create_device_with_interface(
            name_prefix="plain-tenant-out-none",
            location=self.location,
            tenant=None,
        )
        created_interfaces = [interface_in_scope, interface_out_scope, interface_out_scope_none]
        location_ids = set()
        tenant_ids = {self.tenant.id}

        expected_ids = {interface_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_interfaces, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=Interface,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {interface.id for interface in created_interfaces}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_interface_scope_plain_device_location_and_tenant_matches_engine_semantics(self):
        """Scoped interface selection should match engine semantics for location+tenant filtering."""
        scoped_location = Location.objects.create(
            name="Scope Interface Location+Tenant",
            location_type=self.location_type,
            status=self.location.status,
        )
        other_tenant = Tenant.objects.create(name="Scope Interface Combo Other Tenant", tenant_group=self.tenant_group)
        interface_in_scope = self._create_device_with_interface(
            name_prefix="plain-combo-in",
            location=scoped_location,
            tenant=self.tenant,
        )
        interface_out_scope = [
            self._create_device_with_interface(
                name_prefix="plain-combo-out-location",
                location=self.location,
                tenant=self.tenant,
            ),
            self._create_device_with_interface(
                name_prefix="plain-combo-out-tenant",
                location=scoped_location,
                tenant=other_tenant,
            ),
            self._create_device_with_interface(
                name_prefix="plain-combo-out-none",
                location=scoped_location,
                tenant=None,
            ),
        ]
        created_interfaces = [interface_in_scope] + interface_out_scope
        location_ids = {scoped_location.id}
        tenant_ids = {self.tenant.id}

        expected_ids = {interface_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_interfaces, location_ids, tenant_ids)
        actual_ids = self._scope_actual_ids(
            target_model_class=Interface,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
        ) & {interface.id for interface in created_interfaces}
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_interface_target_queryset_avoids_n_plus_one(self):
        """Interface target queryset should not emit per-object relation queries when iterated."""
        job = ReconcileDNSBulkJob()
        tenant = Tenant.objects.create(name="N+1 Interface Tenant", tenant_group=self.tenant_group)
        prefix = "interface-n-plus-one"
        interface_counts = (2, 8)
        query_counts = []

        for count in interface_counts:
            for index in range(count):
                self._create_device_with_interface(
                    name_prefix=f"{prefix}-{count}-{index}",
                    location=self.location,
                    tenant=tenant,
                )

            queryset = job._build_target_queryset(  # pylint: disable=protected-access
                Interface,
                location_ids=set(),
                tenant_ids=set(),
            )
            queryset = queryset.filter(name__startswith=f"{prefix}-{count}-").order_by("pk")

            with CaptureQueriesContext(connection) as queries:
                for interface in queryset:
                    _ = interface.device
                    _ = interface.device.location
                    _ = interface.device.tenant
                    _ = list(interface.ip_addresses.all())

            query_counts.append(len(queries.captured_queries))

        self.assertEqual(query_counts[0], query_counts[1])

    def test_interface_scope_child_device_matches_engine_semantics(self):
        """Scoped interface selection should match engine semantics for child-device interfaces."""
        scoped_location = Location.objects.create(
            name="Scope Child Device Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        parent_device = Device.objects.create(
            name="child-parent-device",
            device_type=self.device_type,
            location=scoped_location,
            role=self.device_role,
            status=self.device_status,
        )
        child_in_scope = self._create_child_device_with_interface(
            name_prefix="child-in", parent_device=parent_device, location=scoped_location
        )
        parent_device_out = Device.objects.create(
            name="child-parent-device-out",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )
        child_out_scope = self._create_child_device_with_interface(
            name_prefix="child-out", parent_device=parent_device_out, location=self.location
        )
        created_interfaces = [child_in_scope, child_out_scope]
        location_ids = {scoped_location.id}

        expected_ids = {child_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_interfaces, location_ids)
        actual_ids = self._scope_actual_ids(target_model_class=Interface, location_ids=location_ids) & {
            interface.id for interface in created_interfaces
        }
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_interface_scope_module_on_device_matches_engine_semantics(self):
        """Scoped interface selection should match engine semantics for module-backed interfaces on a device."""
        scoped_location = Location.objects.create(
            name="Scope Module Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        parent_device_in = Device.objects.create(
            name="module-parent-in",
            device_type=self.device_type,
            location=scoped_location,
            role=self.device_role,
            status=self.device_status,
        )
        parent_device_out = Device.objects.create(
            name="module-parent-out",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )
        module_in_scope = self._create_module_interface(name_prefix="module-in", parent_device=parent_device_in)
        module_out_scope = self._create_module_interface(name_prefix="module-out", parent_device=parent_device_out)
        created_interfaces = [module_in_scope, module_out_scope]
        location_ids = {scoped_location.id}

        expected_ids = {module_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_interfaces, location_ids)
        actual_ids = self._scope_actual_ids(target_model_class=Interface, location_ids=location_ids) & {
            interface.id for interface in created_interfaces
        }
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)

    def test_interface_scope_module_on_module_matches_engine_semantics(self):
        """Scoped interface selection should match engine semantics for nested module-backed interfaces."""
        scoped_location = Location.objects.create(
            name="Scope Nested Module Location",
            location_type=self.location_type,
            status=self.location.status,
        )
        parent_device_in = Device.objects.create(
            name="nested-module-parent-in",
            device_type=self.device_type,
            location=scoped_location,
            role=self.device_role,
            status=self.device_status,
        )
        parent_device_out = Device.objects.create(
            name="nested-module-parent-out",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )
        nested_in_scope = self._create_nested_module_interface(
            name_prefix="nested-module-in", parent_device=parent_device_in
        )
        nested_out_scope = self._create_nested_module_interface(
            name_prefix="nested-module-out", parent_device=parent_device_out
        )
        created_interfaces = [nested_in_scope, nested_out_scope]
        location_ids = {scoped_location.id}

        expected_ids = {nested_in_scope.id}
        expected_ids_from_engine = self._scope_expected_ids_from_engine(created_interfaces, location_ids)
        actual_ids = self._scope_actual_ids(target_model_class=Interface, location_ids=location_ids) & {
            interface.id for interface in created_interfaces
        }
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)


class ReconcileDNSJobJSONSchemaValidationTestCase(BaseRuleEngineMixin, TransactionTestCase):
    """Validate DNS reconciliation job outputs against the published JSON schema."""

    @classmethod
    def setUpTestData(cls):
        """Set up schema-validation fixtures and one enabled Interface rule."""
        super().setUpTestData()
        cls.interface.ip_addresses.set([cls.ip_addresses[0]])
        cls.interface_rule = DNSRule.objects.create(
            name="job-interface-schema",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

    def setUp(self):
        """Rebuild fixtures per test under TransactionTestCase semantics."""
        ContentType.objects.clear_cache()
        TransactionTestCase.setUp(self)
        type(self).setUpTestData()
        BaseRuleEngineMixin.setUp(self)

    @staticmethod
    def _load_result_schema():
        """Load and parse the canonical reconcile job result JSON schema."""
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "reconcile_dns_job_result.schema.json"
        return json.loads(schema_path.read_text(encoding="utf-8"))

    def test_object_result_matches_json_schema(self):
        """Successful object job output should validate against the published JSON schema."""
        result = ReconcileDNSObjectJob().run(
            dryrun=True,
            object_model=ContentType.objects.get_for_model(Interface),
            object_id=str(self.interface.id),
        )
        jsonschema.validate(instance=result, schema=self._load_result_schema())

    def test_bulk_result_matches_json_schema(self):
        """Successful bulk job output should validate against the published JSON schema."""
        result = ReconcileDNSBulkJob().run(
            dryrun=True,
            source_models=[ContentType.objects.get_for_model(Interface)],
            rules=[self.interface_rule],
            limit=1,
            batch_size=1,
            fast_mode=True,
        )
        jsonschema.validate(instance=result, schema=self._load_result_schema())
