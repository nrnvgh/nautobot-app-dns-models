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
from nautobot.ipam.models import IPAddress, Prefix
from nautobot.tenancy.models import Tenant
from nautobot.virtualization.models import Cluster, VirtualMachine

from nautobot_dns_models.jobs import ReconcileDNSBulkJob, ReconcileDNSObjectJob, ReconcileRunSummary
from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine_selector import get_rule_engine
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
            source_models=["dcim.interface"],
            rules=[scoped_rule],
            locations=[scoped_location],
            limit=None,
            batch_size=1000,
        )
        self.assertEqual(primer["execution"]["targets_seen"], 8)

        scoped_rule.name_template = "{{ obj.device.name }}-{{ obj.name }}-updated"
        scoped_rule.save()

        # Limit is intentionally smaller than total interfaces so this exercises in-scope limit semantics.
        result = ReconcileDNSBulkJob().run(
            dryrun=False,
            source_models=["dcim.interface"],
            rules=[scoped_rule],
            locations=[scoped_location],
            limit=20,
            batch_size=1000,
        )
        self.assertEqual(result["execution"]["targets_seen"], 8)
        self.assertEqual(result["execution"]["processed_count"], 8)
        self.assertEqual(result["reconciliation"]["objects_changed"], 8)

class ScopeSelectionTestCase(BaseRuleEngineMixin, TransactionTestCase):
    """Validate SQL scope selection parity with engine semantics."""

    @classmethod
    def setUpTestData(cls):
        """Set up fixtures required for interface scope selection tests."""
        super().setUpTestData()
        cls.interface.ip_addresses.set([cls.ip_addresses[0]])

    def setUp(self):
        """Rebuild fixtures per test under TransactionTestCase semantics."""
        TransactionTestCase.setUp(self)
        type(self).setUpTestData()
        BaseRuleEngineMixin.setUp(self)

    @staticmethod
    def _scope_expected_ids_from_engine(objects, location_ids, tenant_ids=None):
        """Return expected object IDs via engine scope-resolution semantics."""
        tenant_ids = tenant_ids or set()
        selected_engine = get_rule_engine()
        expected_ids = set()
        for obj in objects:
            object_location = selected_engine._get_object_location(obj)  # pylint: disable=protected-access
            object_tenant = selected_engine._get_object_tenant(obj)  # pylint: disable=protected-access
            if location_ids and (object_location is None or object_location.id not in location_ids):
                continue
            if tenant_ids and (object_tenant is None or object_tenant.id not in tenant_ids):
                continue
            expected_ids.add(obj.id)
        return expected_ids

    def _scope_actual_ids(self, *, target_label, location_ids, tenant_ids=None):
        """Return object IDs selected by the bulk job scope pipeline path."""
        tenant_ids = tenant_ids or set()
        job = ReconcileDNSBulkJob()
        selected_engine = get_rule_engine()
        summary = ReconcileRunSummary()
        targets = list(
            job._iter_targets(  # pylint: disable=protected-access
                target_labels=[target_label],
                batch_size=1000,
                limit=20000,
                location_ids=location_ids,
                tenant_ids=tenant_ids,
            )
        )
        selected_targets = job._build_pipeline_in_scope_targets(  # pylint: disable=protected-access
            targets,
            summary=summary,
            selected_engine=selected_engine,
            dryrun=True,
            location_ids=location_ids,
            tenant_ids=tenant_ids,
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
        actual_ids = self._scope_actual_ids(target_label="dcim.device", location_ids=location_ids) & {
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
            target_label="dcim.device",
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
            target_label="dcim.device",
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

            queryset, _ = job._build_target_queryset(  # pylint: disable=protected-access
                "dcim.device",
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
        actual_ids = self._scope_actual_ids(target_label="virtualization.virtualmachine", location_ids=location_ids) & {
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
            target_label="virtualization.virtualmachine",
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

            queryset, _ = job._build_target_queryset(  # pylint: disable=protected-access
                "virtualization.virtualmachine",
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
            target_label="virtualization.virtualmachine",
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
        actual_ids = self._scope_actual_ids(target_label="dcim.interface", location_ids=location_ids) & {
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
            target_label="dcim.interface",
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
            target_label="dcim.interface",
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

            queryset, _ = job._build_target_queryset(  # pylint: disable=protected-access
                "dcim.interface",
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
        actual_ids = self._scope_actual_ids(target_label="dcim.interface", location_ids=location_ids) & {
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
        actual_ids = self._scope_actual_ids(target_label="dcim.interface", location_ids=location_ids) & {
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
        actual_ids = self._scope_actual_ids(target_label="dcim.interface", location_ids=location_ids) & {
            interface.id for interface in created_interfaces
        }
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertSetEqual(actual_ids, expected_ids_from_engine)
