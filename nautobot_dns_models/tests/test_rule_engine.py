"""
Categories:
- TemplateRenderingTestCase: Template rendering, syntax errors, undefined variables, error handling
- RuleResolutionTestCase: Rule resolution, location/tenant extraction, precedence logic, fallback scenarios
- IntegrationAndMultiRecordTestCase: End-to-end workflows, signal handlers, multi-IP scenarios, DNS record lifecycle
- RuleValidationTestCase: Template validation, runtime errors, filter validation
"""
# pylint: disable=too-many-lines

import itertools
from unittest import skip
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from jinja2 import TemplateSyntaxError, UndefinedError
from nautobot.apps.utils import render_jinja2
from nautobot.dcim.choices import InterfaceTypeChoices
from nautobot.dcim.models import Device, Interface, Location, LocationType
from nautobot.extras.models import Status
from nautobot.ipam.models import IPAddress, IPAddressToInterface, Service
from nautobot.virtualization.models import Cluster, ClusterType, VirtualMachine, VMInterface

from nautobot_dns_models.exceptions import DNSTemplateEmptyError
from nautobot_dns_models.models import AAAARecord, ARecord, DNSRule, DNSRuleRecord
from nautobot_dns_models.normalization import normalize_dns_name
from nautobot_dns_models.rules.template_proxies import wrap_for_template

from .mixins.rule_engine import BaseRuleEngineMixin

TEST_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        # This will capture logs from your app.
        # Replace 'myapp' with the name of the logger you want to see.
        "nautobot_dns_models": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": True,
        },
    },
}


class TemplateRenderingTestCase(BaseRuleEngineMixin, TestCase):
    """Template rendering, syntax errors, undefined variables, error handling."""

    def test_render_template_method_with_valid_template(self):
        """Test _render_template method with valid input."""
        result = self._render_template("Hello {{ name }}", {"name": "World"}, "test_field")
        self.assertEqual(result, "Hello World")

    def test_render_template_method_with_undefined_variable(self):
        """Test _render_template method behavior with undefined variables."""
        # render_jinja2 returns empty string for undefined variables, which our method treats as an error
        with self.assertRaises(DNSTemplateEmptyError):
            self._render_template("{{ undefined_var }}", {}, "test_field")

    def test_render_template_method_with_syntax_error(self):
        """Test _render_template method behavior with syntax errors."""
        with self.assertRaises(TemplateSyntaxError):
            self._render_template("{{ invalid }", {}, "test_field")

    def test_render_template_method_with_none_attribute(self):
        """Test _render_template method behavior when accessing attributes on None."""
        # This is the real-world case: when an IP is removed, obj.primary_ip4 becomes None
        # render_jinja2 returns empty string, which our method treats as an error
        with self.assertRaises(DNSTemplateEmptyError):
            self._render_template(
                "{{ obj.primary_ip4 }}",
                {"obj": wrap_for_template(self.device)},
                "test_field",  # self.device has no primary_ip4 set
            )

    def test_render_template_using_array_index(self):
        """Test _render_template method behavior with array index."""
        # Add IP address to interface before rendering
        self.interface.ip_addresses.add(self.ip_addresses[0])
        result = self._render_template("{{ obj.ip_addresses.all()[0] }}", {"obj": wrap_for_template(self.interface)}, "test_field")
        # TemplateIPAddressProxy returns UUID string when rendered
        self.assertEqual(result, str(self.ip_addresses[0].pk))

    def test_render_template_method_with_array_index_error(self):
        """Test _render_template method behavior with array index errors."""
        # Create interface with no IP addresses to test array index error
        empty_interface = Interface.objects.create(
            name="empty-interface",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )
        with self.assertRaises(DNSTemplateEmptyError) as context:
            self._render_template("{{ obj.ip_addresses.all()[0] }}", {"obj": wrap_for_template(empty_interface)}, "test_field")

        # When accessing index 0 on empty queryset, Jinja2 renders empty string, triggering DNSTemplateEmptyError
        self.assertIn("Template test_field rendered empty", str(context.exception))
        self.assertIn("obj.ip_addresses.all()[0]", str(context.exception))

    def test_render_template_method_empty_string_handling(self):
        """Test that empty string results are treated as errors."""
        # Templates that evaluate to empty strings should be treated as failures
        test_cases = [
            ("{{ obj.missing_attr }}", {"obj": {}}),
            ("{{ missing_var }}", {}),
            ("{{ obj.attr }}", {"obj": None}),
        ]

        for template, context in test_cases:
            with self.subTest(template=template, context=context):
                with self.assertRaises(DNSTemplateEmptyError):
                    self._render_template(template, context, "test_field")

    def test_render_template_method_valid_non_empty_result(self):
        """Test that valid non-empty results work correctly."""
        result = self._render_template("{{ name }}", {"name": "test-value"}, "test_field")
        self.assertEqual(result, "test-value")

        # Test with zero (which is falsy but might be valid for MX/SRV fields)
        result = self._render_template("{{ count }}", {"count": 0}, "test_field")
        self.assertEqual(result, "0")  # render_jinja2 converts 0 to "0" string

        # Test with False
        result = self._render_template("{{ flag }}", {"flag": False}, "test_field")
        self.assertEqual(result, "False")  # render_jinja2 converts False to "False" string

    def test_render_template_method_catches_empty_results_for_object_with_no_primary_ip4(self):
        """Test that our _render_template method catches empty results from template failures."""
        # Test case where template renders to empty string (most common failure mode)
        # Use real device object without primary_ip4 set
        with self.assertRaises(DNSTemplateEmptyError) as context:
            self._render_template("{{ obj.primary_ip4 }}", {"obj": wrap_for_template(self.device)}, "test_field")

        # The error should mention that template rendered empty
        error_message = str(context.exception)
        self.assertIn("Template test_field rendered empty", error_message)

    @override_settings(DEBUG=True)
    def test_render_template_method_catches_error_strings(self):
        """Test detection of '{{ no such element:' error strings from DEBUG=True environments."""
        # In DEBUG=True environments, Django uses jinja2.runtime.DebugUndefined which returns
        # descriptive error strings like "{{ no such element: None['id'] }}" instead of empty strings.

        # Create interface with no role to test the real scenario
        interface_no_role = Interface.objects.create(
            name="test-interface-no-role",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Test the template that should trigger the DEBUG=True error pattern
        # The rule engine should catch the DebugUndefined error pattern and include it in the exception
        with self.assertRaises(DNSTemplateEmptyError) as context:
            self._render_template("{{ obj.role.name }}", {"obj": wrap_for_template(interface_no_role)}, "test_field")

        # In DEBUG=True with DebugUndefined, the error message should contain the pattern
        self.assertIn("{{ no such element:", str(context.exception))

    def test_service_basic_template_rendering(self):
        """Test basic Service template rendering for both device and VM-attached services."""
        # Test device-attached service
        device_template = "{{ obj.name }}.{{ obj.device.name }}"
        result = render_jinja2(device_template, {"obj": wrap_for_template(self.service_device_attached)})
        self.assertEqual(result, f"web-service.{self.device.name}")

        # Test VM-attached service
        vm_template = "{{ obj.name }}.{{ obj.virtual_machine.name }}"
        result = render_jinja2(vm_template, {"obj": wrap_for_template(self.service_vm_attached)})
        self.assertEqual(result, f"api-service.{self.vm.name}")

    def test_service_parent_property_template(self):
        """Test Service.parent property works in templates."""
        parent_template = "{{ obj.parent.name }}"

        # Device-attached service
        result = render_jinja2(parent_template, {"obj": wrap_for_template(self.service_device_attached)})
        self.assertEqual(result, self.device.name)

        # VM-attached service
        result = render_jinja2(parent_template, {"obj": wrap_for_template(self.service_vm_attached)})
        self.assertEqual(result, self.vm.name)

    def test_service_location_template_rendering(self):
        """Test Service location access in templates."""
        # Device-attached service location
        device_location_template = "{{ obj.device.location.name }}"
        result = render_jinja2(device_location_template, {"obj": wrap_for_template(self.service_device_attached)})
        expected = self.location.name
        self.assertEqual(result, expected)

        # VM-attached service location
        vm_location_template = "{{ obj.virtual_machine.cluster.location.name }}"
        result = render_jinja2(vm_location_template, {"obj": wrap_for_template(self.service_vm_attached)})
        self.assertEqual(result, expected)


class RuleResolutionTestCase(BaseRuleEngineMixin, TestCase):
    """
    Rule resolution tests.

    Tests that desired rule precedence is respected.
    
    """

    def test_get_object_location_device(self):
        """Test _get_object_location returns device.location for Device objects."""
        # Test location extraction
        result = self._get_object_location(self.device)
        self.assertEqual(result, self.location)

    def test_get_object_location_interface(self):
        """Test _get_object_location returns interface.device.location for Interface objects."""
        # Test location extraction from interface
        result = self._get_object_location(self.interface)
        self.assertEqual(result, self.location)

    def test_get_object_location_virtualmachine_not_implemented(self):
        """Test _get_object_location returns None for VirtualMachine objects (future support)."""
        # VirtualMachine is a realistic future object type for DNS rules
        # Currently returns None because vm.cluster.location extraction is not implemented
        cluster_type = ClusterType.objects.create(name="test-cluster-type")
        cluster = Cluster.objects.create(
            name="test-cluster",
            cluster_type=cluster_type,
        )

        vm = VirtualMachine.objects.create(
            name="test-vm",
            cluster=cluster,
            status=Status.objects.get_for_model(VirtualMachine).first(),
        )

        # Currently returns None - will return vm.cluster.location when TODO is implemented
        # TODO: Update this test to expect vm.cluster.location when VirtualMachine support is added
        result = self._get_object_location(vm)
        self.assertIsNone(result)  # Current behavior - should change to assertEqual(result, cluster.location)

    def test_get_applicable_rules_location_specific_rules_selected(self):
        """Test that location-specific rules are selected when object has location."""

        # Create location-specific rule
        location_rule = DNSRule.objects.create(
            name="location-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create global rule (should be ignored when location rule exists)
        DNSRule.objects.create(
            name="global-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        rules = self._get_applicable_rules(self.device)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first(), location_rule)

    def test_get_applicable_rules_global_fallback(self):
        """Test that global rules are used when no location-specific rules exist."""

        # Create only global rule (no location-specific rules)
        global_rule = DNSRule.objects.create(
            name="global-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        rules = self._get_applicable_rules(self.device)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first(), global_rule)

    def test_get_applicable_rules_no_location_gets_global(self):
        """Test that objects without location only get global rules."""
        # Use VirtualMachine which currently has no location extraction
        cluster_type = ClusterType.objects.create(name="test-cluster-type")
        cluster = Cluster.objects.create(name="test-cluster", cluster_type=cluster_type)
        vm = VirtualMachine.objects.create(
            name="test-vm",
            cluster=cluster,
            status=Status.objects.get_for_model(VirtualMachine).first(),
        )

        # Create location-specific rule (should be ignored)
        DNSRule.objects.create(
            name="location-rule",
            content_type=ContentType.objects.get_for_model(VirtualMachine),
            location=self.location,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="192.168.1.1",
        )

        # Create global rule (should be selected)
        global_rule = DNSRule.objects.create(
            name="global-rule",
            content_type=ContentType.objects.get_for_model(VirtualMachine),
            location=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="192.168.1.1",
        )

        rules = self._get_applicable_rules(vm)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first(), global_rule)

    def test_get_applicable_rules_per_record_type_precedence_mixed_rules(self):
        """Test per-record-type precedence: location-specific A rule + global AAAA rule."""
        # Create location-specific A record rule
        location_a_rule = DNSRule.objects.create(
            name="location-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create global AAAA record rule
        global_aaaa_rule = DNSRule.objects.create(
            name="global-aaaa-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,  # Global rule
            zone_template="global.example.com",
            record_type="AAAA",
            name_template="{{ obj.name }}-ipv6",
            value_template="{{ obj.primary_ip6 }}",
        )

        # Create global A record rule (should be overridden by location-specific)
        global_a_rule = DNSRule.objects.create(
            name="global-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,  # Global rule
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4 }}",
        )

        rules = self._get_applicable_rules(self.device)

        # Should get location-specific A rule + global AAAA rule (2 rules total)
        self.assertEqual(rules.count(), 2)

        # Verify we got the correct rules
        rule_names = {rule.name for rule in rules}
        self.assertIn(location_a_rule.name, rule_names)  # Location-specific A rule
        self.assertIn(global_aaaa_rule.name, rule_names)  # Global AAAA rule
        self.assertNotIn(global_a_rule.name, rule_names)  # Should be overridden

    def test_get_applicable_rules_per_record_type_precedence_location_override(self):
        """Test that location-specific rules override global rules for same record type."""
        # Create location-specific A record rule
        location_rule = DNSRule.objects.create(
            name="location-override-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}-location",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create global A record rule (should be overridden)
        DNSRule.objects.create(
            name="global-override-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4 }}",
        )

        rules = self._get_applicable_rules(self.device)

        # Should only get location-specific rule
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first().name, location_rule.name)

    def test_get_applicable_rules_per_record_type_precedence_multiple_location_rules(self):
        """Test that multiple location-specific rules for different record types are all returned."""
        # Create multiple location-specific rules for different record types
        location_a_rule = DNSRule.objects.create(
            name="location-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        location_aaaa_rule = DNSRule.objects.create(
            name="location-aaaa-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="AAAA",
            name_template="{{ obj.name }}-ipv6",
            value_template="{{ obj.primary_ip6 }}",
        )

        rules = self._get_applicable_rules(self.device)

        # Should get both location-specific rules
        self.assertEqual(rules.count(), 2)
        rule_names = {rule.name for rule in rules}
        expected_names = {location_a_rule.name, location_aaaa_rule.name}
        self.assertEqual(rule_names, expected_names)

    def test_get_applicable_rules_tenant_precedence_location_first(self):
        """Test location-first precedence: Location+Tenant > Location > Tenant > Global."""
        # Create rules with different scoping levels
        DNSRule.objects.create(
            name="global-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            tenant=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4 }}",
        )

        DNSRule.objects.create(
            name="tenant-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            tenant=self.tenant,
            zone_template="tenant.example.com",
            record_type="A",
            name_template="{{ obj.name }}-tenant",
            value_template="{{ obj.primary_ip4 }}",
        )

        DNSRule.objects.create(
            name="location-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            tenant=None,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}-location",
            value_template="{{ obj.primary_ip4 }}",
        )

        location_tenant_rule = DNSRule.objects.create(
            name="location-tenant-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            tenant=self.tenant,
            zone_template="location-tenant.example.com",
            record_type="A",
            name_template="{{ obj.name }}-location-tenant",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create device with both location and tenant
        device_with_both = Device.objects.create(
            name="test-device-scoped",
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=Status.objects.get_for_model(Device).first(),
        )

        rules = self._get_applicable_rules(device_with_both)

        # Should get the most specific rule (location+tenant)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first().name, location_tenant_rule.name)

    def test_get_applicable_rules_tenant_precedence_mixed_scoping(self):
        """Test that a Location A rule + Tenant AAAA rule are both applicable for same object."""
        # Create location-specific A rule
        location_a_rule = DNSRule.objects.create(
            name="location-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            tenant=None,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create tenant-specific AAAA rule
        tenant_aaaa_rule = DNSRule.objects.create(
            name="tenant-aaaa-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            tenant=self.tenant,
            zone_template="tenant.example.com",
            record_type="AAAA",
            name_template="{{ obj.name }}-ipv6",
            value_template="{{ obj.primary_ip6 }}",
        )

        # Create device with both location and tenant
        device_with_both = Device.objects.create(
            name="test-device-mixed",
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=Status.objects.get_for_model(Device).first(),
        )

        rules = self._get_applicable_rules(device_with_both)

        # Should get both rules (different record types)
        self.assertEqual(rules.count(), 2)
        rule_names = {rule.name for rule in rules}
        expected_names = {location_a_rule.name, tenant_aaaa_rule.name}
        self.assertEqual(rule_names, expected_names)

    def test_get_applicable_rules_tenant_fallback_scenarios(self):
        """Test various fallback scenarios for tenant/location precedence."""
        # Create global rule as fallback
        global_rule = DNSRule.objects.create(
            name="global-fallback-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            tenant=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Test 1: Device with location but no tenant → should get global rule
        device_location_only = Device.objects.create(
            name="test-device-loc-only",
            device_type=self.device_type,
            location=self.location,
            tenant=None,
            role=self.device_role,
            status=Status.objects.get_for_model(Device).first(),
        )

        rules = self._get_applicable_rules(device_location_only)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first().name, global_rule.name)

        # Test 2: Device with tenant but no location → should get global rule
        device_tenant_only = Device.objects.create(
            name="test-device-tenant-only",
            device_type=self.device_type,
            location=self.location,  # Has location for creation, will clear tenant
            tenant=self.tenant,
            role=self.device_role,
            status=Status.objects.get_for_model(Device).first(),
        )
        # Simulate device with tenant but in different location (no location-scoped rules)
        device_tenant_only.location = Location.objects.create(
            name="Different Location",
            location_type=self.location_type,
            status=Status.objects.get_for_model(Location).first(),
        )
        device_tenant_only.save()

        rules = self._get_applicable_rules(device_tenant_only)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first().name, global_rule.name)

    def test_service_location_extraction(self):
        """Test location extraction for both Service attachment types."""
        # Device-attached service
        location = self._get_object_location(self.service_device_attached)
        self.assertEqual(location, self.location)

        # VM-attached service
        location = self._get_object_location(self.service_vm_attached)
        self.assertEqual(location, self.location)

    def test_service_tenant_extraction_with_fallback(self):
        """Test tenant extraction including VM→cluster fallback."""
        # Create cluster with tenant but VM without tenant
        cluster_with_tenant = Cluster.objects.create(
            name="Tenant Cluster", cluster_type=self.cluster_type, location=self.location, tenant=self.tenant
        )
        vm_no_tenant = VirtualMachine.objects.create(
            cluster=cluster_with_tenant,
            name="VM No Tenant",
            status=self.vm_status,
            # tenant=None
        )
        service_cluster_tenant = Service.objects.create(
            virtual_machine=vm_no_tenant, name="service-cluster-tenant", protocol="TCP", ports=[80]
        )

        # Should get cluster tenant as fallback
        tenant = self._get_object_tenant(service_cluster_tenant)
        self.assertEqual(tenant, self.tenant)


class IntegrationAndMultiRecordTestCase(BaseRuleEngineMixin, TestCase):  # pylint: disable=too-many-public-methods
    """End-to-end workflows, signal handlers, multi-IP scenarios, DNS record lifecycle."""

    def _create_dns_rule_for_interface_a_record(self, name="interface-a-record-rule"):
        """Helper method to create a DNS rule for integration tests."""
        return DNSRule.objects.create(
            name=name,
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

    def _create_dns_rule_for_device_a_record(self, name="device-a-record-rule"):
        """Helper method to create a DNS rule for integration tests."""
        return DNSRule.objects.create(
            name=name,
            description="Create A records for devices",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
            enabled=True,
        )

    def test_interface_a_record_created_on_ip_addition_via_m2m_api(self):
        """Test that A records are created when IP is added to interface via Django M2M API."""
        # Create DNS rule for this test
        dns_rule = self._create_dns_rule_for_interface_a_record()

        # Verify no A records exist initially
        initial_a_records = ARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Verify no DNSRuleRecord tracking exists initially
        initial_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule).count()
        self.assertEqual(initial_rule_records, 0)

        # Add IP address to interface (this should trigger A record creation)
        self.interface.ip_addresses.add(self.ip_addresses[0])

        # Verify A record was created
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        self.assertEqual(a_record.address, self.ip_addresses[0])
        self.assertEqual(a_record.name, "eth0.test-device")
        self.assertEqual(a_record.zone, self.dns_zone)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        rule_record = rule_records.first()
        self.assertEqual(rule_record.source_object, self.interface)
        self.assertEqual(rule_record.dns_record, a_record)

    def test_interface_multiple_a_records_created_one_at_a_time_on_ip_addition_via_m2m_api(self):
        """Test that multiple A records are created when IP is added to interface via Django M2M API."""
        # Create DNS rule for this test
        DNSRule.objects.create(
            name="interface-multiple-a-records-rule",
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        # Verify no A records exist initially
        initial_a_records = ARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Add IP address to interface (this should trigger A record creation)
        self.interface.ip_addresses.add(self.ip_addresses[0])

        # Verify A record was created
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Add second IP address to interface (this should trigger another A record creation)
        self.interface.ip_addresses.add(self.ip_addresses[1])

        # Verify second A record was created
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 2)

    def test_interface_multiple_a_records_created_in_one_call_on_ip_addition_via_m2m_api(self):
        """Test that multiple A records are created when multiple IP addresses are added to interface via Django M2M API."""
        # Create DNS rule for this test
        dns_rule = DNSRule.objects.create(
            name="interface-multiple-a-records-rule",
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )
        # Verify no A records exist initially
        initial_a_records = ARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Add multiple IP addresses to interface (this should trigger A record creation)
        self.interface.ip_addresses.add(self.ip_addresses[0], self.ip_addresses[1])

        # Verify A records were created
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 2)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 2)

    def test_interface_multiple_aaaa_records_created_one_at_a_time_on_ip_addition_via_m2m_api(self):
        """Test that multiple AAAA records are created when IP is added to interface via Django M2M API."""
        # Create DNS rule for this test
        DNSRule.objects.create(
            name="interface-multiple-aaaa-records-rule",
            description="Create AAAA records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="AAAA",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        # Verify no AAAA records exist initially
        initial_aaaa_records = AAAARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_aaaa_records, 0)

        # Add IP address to interface (this should trigger AAAA record creation)
        self.interface.ip_addresses.add(self.ipv6_addresses[0])

        # Verify AAAA record was created
        aaaa_records = AAAARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(aaaa_records.count(), 1)

        # Add second IP address to interface (this should trigger another AAAA record creation)
        self.interface.ip_addresses.add(self.ipv6_addresses[1])

        # Verify second AAAA record was created
        aaaa_records = AAAARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(aaaa_records.count(), 2)

    def test_interface_multiple_aaaa_records_created_in_one_call_on_ip_addition_via_m2m_api(self):
        """Test that multiple AAAA records are created when multiple IP addresses are added to interface via Django M2M API."""
        # Create DNS rule for this test
        dns_rule = DNSRule.objects.create(
            name="interface-multiple-aaaa-records-rule",
            description="Create AAAA records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="AAAA",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )
        # Verify no AAAA records exist initially
        initial_aaaa_records = AAAARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_aaaa_records, 0)

        # Add multiple IP addresses to interface (this should trigger AAAA record creation)
        self.interface.ip_addresses.add(self.ipv6_addresses[0], self.ipv6_addresses[1])

        # Verify AAAA records were created
        aaaa_records = AAAARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(aaaa_records.count(), 2)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 2)

    def test_interface_a_record_deleted_on_ip_removal_via_m2m_api(self):
        """Test that A records are deleted when IP is removed from interface via Django M2M API."""
        # Create DNS rule for this test
        dns_rule = self._create_dns_rule_for_interface_a_record()

        # Setup initial state with IP and A record
        self.interface.ip_addresses.add(self.ip_addresses[0])

        # Verify A record exists
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Verify DNSRuleRecord tracking exists
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        # Remove IP address from interface (this should trigger A record deletion)
        self.interface.ip_addresses.remove(self.ip_addresses[0])

        # Verify A record was deleted
        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0)

        # Verify DNSRuleRecord tracking was also cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(remaining_rule_records.count(), 0)

    def test_interface_a_record_removal_with_multiple_ips(self):
        """Test A record behavior when interface has multiple IPs and one is removed."""
        # Create DNS rule for this test
        self._create_dns_rule_for_interface_a_record()

        # Add both IP addresses to interface.
        self.interface.ip_addresses.add(self.ip_addresses[0], self.ip_addresses[1])

        # Verify A record was created (should use first IP)
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        # The record should use whichever IP is returned by .first()
        self.assertIn(a_record.address, [self.ip_addresses[0], self.ip_addresses[1]])

        # Remove one IP address
        self.interface.ip_addresses.remove(self.ip_addresses[0])

        # Verify A record still exists (should now use the remaining IP)
        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 1)

        # The record should now point to the remaining IP
        updated_record = remaining_a_records.first()
        self.assertEqual(updated_record.address, self.ip_addresses[1])

        # Remove the last IP address
        self.interface.ip_addresses.remove(self.ip_addresses[1])

        # Now the A record should be deleted (template fails with no IPs)
        final_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(final_a_records.count(), 0)

    def test_atomicity_dnsrecord_validation_failure_rolls_back(self):
        """If DNSRecord validation fails, no DNSRecord or tracking row should persist."""
        # Create an AAAA rule but only assign an IPv4 address -> validation should fail
        DNSRule.objects.create(
            name="iface-aaaa-invalid",
            description="Invalid AAAA creation path",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="AAAA",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        # Pre-condition: no AAAA records
        self.assertEqual(AAAARecord.objects.filter(name__startswith="eth0.").count(), 0)

        # Assign IPv4 address; engine will attempt AAAA creation and should fail validation
        self.interface.ip_addresses.add(self.ip_addresses[0])

        # Assert: still no AAAA records and no tracking rows
        self.assertEqual(AAAARecord.objects.filter(name__startswith="eth0.").count(), 0)
        self.assertEqual(
            DNSRuleRecord.objects.filter(dns_record_content_type=ContentType.objects.get_for_model(AAAARecord)).count(),
            0,
        )

    def test_atomicity_tracking_uniqueness_failure_rolls_back(self):
        """If tracking creation fails (IntegrityError), the DNSRecord should not persist (rolled back)."""

        # Create an A rule that would normally succeed
        DNSRule.objects.create(
            name="iface-a-atomicity",
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        expected_name = f"{self.interface.name}.{self.device.name}"
        self.assertEqual(ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(), 0)

        # Force DNSRuleRecord.objects.create to raise IntegrityError to simulate uniqueness failure
        with patch(
            "nautobot_dns_models.rules.engine.DNSRuleRecord.objects.create",
            side_effect=IntegrityError("dup"),
        ):
            # Assign IPv4 to trigger engine
            self.interface.ip_addresses.add(self.ip_addresses[0])

        # Assert DNSRecord was not persisted due to atomic rollback
        self.assertEqual(ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(), 0)

    def test_interface_a_record_created_on_ip_addition_via_custom_method(self):
        """Test that A records are created when IP is added to interface via custom add_ip_addresses method."""
        # Verify no A records exist initially
        initial_a_records = ARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Create DNS rule for this test
        dns_rule = self._create_dns_rule_for_interface_a_record()

        # Verify no DNSRuleRecord tracking exists initially
        initial_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule).count()
        self.assertEqual(initial_rule_records, 0)

        # Add IP address to interface using custom method (this should trigger A record creation)
        count = self.interface.add_ip_addresses(self.ip_addresses[0])
        self.assertEqual(count, 1)  # Verify return value

        # Verify A record was created
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        self.assertEqual(a_record.address, self.ip_addresses[0])
        self.assertEqual(a_record.name, "eth0.test-device")
        self.assertEqual(a_record.zone, self.dns_zone)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        rule_record = rule_records.first()
        self.assertEqual(rule_record.source_object, self.interface)
        self.assertEqual(rule_record.dns_record, a_record)

    def test_interface_a_record_deleted_on_ip_removal_via_custom_method(self):
        """Test that A records are deleted when IP is removed from interface via custom remove_ip_addresses method."""
        # Create DNS rule for this test
        dns_rule = self._create_dns_rule_for_interface_a_record()

        # Setup initial state with IP and A record using M2M API
        self.interface.ip_addresses.add(self.ip_addresses[0])

        # Verify A record exists
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Verify DNSRuleRecord tracking exists
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        # Remove IP address from interface using custom method (this should trigger A record deletion)
        count = self.interface.remove_ip_addresses(self.ip_addresses[0])
        self.assertEqual(count, 1)  # Verify return value

        # Verify A record was deleted
        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0)

        # Verify DNSRuleRecord tracking was also cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(remaining_rule_records.count(), 0)

    def test_interface_a_record_multiple_ips_via_custom_method(self):
        """Test A record behavior with multiple IPs using custom methods."""
        self._create_dns_rule_for_interface_a_record()

        expected_dns_name = f"{self.interface.name}.{self.device.name}"
        # Add  IP addresses to interface using custom method
        count = self.interface.add_ip_addresses([self.ip_addresses[0], self.ip_addresses[1]])
        self.assertEqual(count, 2)  # Both IPs should be added

        # Verify A record was created (should use first IP)
        a_records = ARecord.objects.filter(name=expected_dns_name, zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        # The record should use whichever IP is returned by .first()
        self.assertIn(a_record.address, [self.ip_addresses[0], self.ip_addresses[1]])

        # Remove one IP address using custom method
        count = self.interface.remove_ip_addresses(self.ip_addresses[0])
        self.assertEqual(count, 1)  # One IP should be removed

        # Verify A record still exists (should now use the remaining IP)
        remaining_a_records = ARecord.objects.filter(name=expected_dns_name, zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 1)

        # The record should now point to the remaining IP
        updated_record = remaining_a_records.first()
        self.assertEqual(updated_record.address, self.ip_addresses[1])

        # Remove the last IP address using custom method
        count = self.interface.remove_ip_addresses(self.ip_addresses[1])
        self.assertEqual(count, 1)  # Last IP should be removed

        # Now the A record should be deleted (template fails with no IPs)
        final_a_records = ARecord.objects.filter(name=expected_dns_name, zone=self.dns_zone)
        self.assertEqual(final_a_records.count(), 0)

    def test_interface_ip_addition_with_conflicting_through_defaults_fails(self):
        """Test that IP addition fails when through_defaults violate IPAddressToInterface mutual exclusion."""
        vm_interface_status = Status.objects.get_for_model(VMInterface).first()
        vm_interface = VMInterface.objects.create(
            virtual_machine=self.vm, name=self.interface.name, status=vm_interface_status
        )

        # Test 1: Physical Interface with VMInterface in through_defaults (should fail)
        with self.assertRaises(ValidationError) as context:
            with transaction.atomic():
                self.interface.ip_addresses.add(
                    self.ip_addresses[0],
                    through_defaults={
                        "vm_interface": vm_interface,  # ← Violates mutual exclusion
                        "is_primary": True,
                    },
                )

        # Verify the error message relates to mutual exclusion
        self.assertIn("Cannot use a single instance to associate to both", str(context.exception))

        # Verify no IPAddressToInterface instance was created
        assignments = IPAddressToInterface.objects.filter(interface=self.interface, ip_address=self.ip_addresses[0])
        self.assertEqual(assignments.count(), 0)

        # Test 2: VMInterface with Interface in through_defaults (should fail)
        with self.assertRaises(ValidationError) as context:
            with transaction.atomic():
                vm_interface.ip_addresses.add(
                    self.ip_addresses[0],
                    through_defaults={
                        "interface": self.interface,  # ← Violates mutual exclusion
                        "is_primary": True,
                    },
                )

        # Verify the error message relates to mutual exclusion
        self.assertIn("Cannot use a single instance to associate to both", str(context.exception))

        # Verify no IPAddressToInterface instance was created
        assignments = IPAddressToInterface.objects.filter(vm_interface=vm_interface, ip_address=self.ip_addresses[0])
        self.assertEqual(assignments.count(), 0)

    def test_a_record_updated_when_interface_name_changed(self):
        """Test that A records are updated when interface name changes."""
        # Create DNS rule for this test
        self._create_dns_rule_for_interface_a_record()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_addresses[0])
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Change interface name
        self.interface.name = "eth1"
        self.interface.save()

        # Current expectation: DNS rule engine should update existing record
        # Note: This tests the UPDATE path in the rule engine
        updated_records = ARecord.objects.filter(name="eth1.test-device", zone=self.dns_zone)
        old_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)

        # For v0.9, we expect the record to be updated (not recreated)
        # The exact behavior depends on rule engine update logic
        self.assertEqual(updated_records.count(), 1, "DNS rule should update record name")
        self.assertEqual(old_records.count(), 0, "Old record should be gone")
        self.assertEqual(updated_records.first().address, self.ip_addresses[0])

    def test_a_record_updated_when_device_name_changed(self):
        """Test that A records are updated when device name changes.

        This tests enhanced cascade processing where device name changes trigger
        updates to Interface-based DNS records that reference {{ obj.device.name }}
        in their templates.

        PERFORMANCE NOTE: Device name changes trigger processing of all interfaces
        on that device. For devices with many interfaces, this has performance cost
        proportional to the interface count, but is necessary for template accuracy.
        """
        # Create DNS rule for this test
        self._create_dns_rule_for_interface_a_record()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_addresses[0])
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Change device name (should trigger cascade processing of interfaces)
        self.device.name = "new-device"
        self.device.save()

        # Enhanced v0.9 behavior: Device name changes trigger Interface rule updates
        updated_records = ARecord.objects.filter(name="eth0.new-device", zone=self.dns_zone)
        old_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)

        # Verify cascade processing worked:
        self.assertEqual(updated_records.count(), 1, "Device name change should trigger interface record update")
        self.assertEqual(old_records.count(), 0, "Old record should be gone after device name change")
        self.assertEqual(updated_records.first().address, self.ip_addresses[0])

    def test_a_record_deleted_when_interface_deleted(self):
        """Test that A records are deleted when interface is deleted."""
        # Create DNS rule for this test
        self._create_dns_rule_for_interface_a_record()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_addresses[0])
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Delete interface
        interface_id = self.interface.id
        self.interface.delete()

        # Verify A record deleted
        remaining_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_records.count(), 0)

        # Verify tracking cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(object_id=interface_id)
        self.assertEqual(remaining_rule_records.count(), 0)

    def test_a_record_deleted_when_device_deleted(self):
        """Test that A records are deleted when device is deleted."""
        # Create DNS rule for this test
        dns_rule = self._create_dns_rule_for_interface_a_record()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_addresses[0])
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Delete device (cascades to interface)
        interface_id = self.interface.id  # Store before deletion
        self.device.delete()

        # Verify A record deleted
        remaining_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_records.count(), 0)

        # Verify tracking cleaned up
        # Note: After device deletion, interface is also deleted, so check by object_id
        remaining_rule_records = DNSRuleRecord.objects.filter(
            rule=dns_rule,
            object_id=interface_id,  # Check for specific interface that was deleted
        )
        self.assertEqual(remaining_rule_records.count(), 0)

    def test_a_record_behavior_when_ip_address_deleted_from_interface(self):
        """Test A record behavior when IP address itself is deleted."""

        # Create DNS rule for this test
        self._create_dns_rule_for_interface_a_record()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_addresses[0])
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)
        rule_records = DNSRuleRecord.objects.filter(object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1, "Rule record should be created when IP address is added to interface")

        # Delete IP address directly (not just remove from interface)
        self.ip_addresses[0].delete()

        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0, "A record should be deleted when IP address is deleted")

        remaining_rule_records = DNSRuleRecord.objects.filter(object_id=self.interface.id)
        self.assertEqual(remaining_rule_records.count(), 0, "Rule record should be deleted when IP address is deleted")

    def test_a_record_behavior_when_ip_address_deleted_from_device(self):
        """Test A record behavior when IP address is deleted from device."""

        # Create DNS rule for this test
        self._create_dns_rule_for_device_a_record()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_addresses[0])
        self.device.primary_ip4 = self.ip_addresses[0]
        self.device.save()

        a_records = ARecord.objects.filter(name="test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)
        rule_records = DNSRuleRecord.objects.filter(object_id=self.device.id)
        self.assertEqual(rule_records.count(), 1, "Rule record should be created when IP address is added to device")

        # Delete IP address directly (not just remove from device)
        self.ip_addresses[0].delete()

        remaining_a_records = ARecord.objects.filter(name="test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0, "A record should be deleted when IP address is deleted")

        remaining_rule_records = DNSRuleRecord.objects.filter(object_id=self.device.id)
        self.assertEqual(remaining_rule_records.count(), 0, "Rule record should be deleted when IP address is deleted")

    def test_location_specific_rule_overrides_global(self):
        """Test that location-specific rules override global rules in real DNS record creation."""
        # Create global rule
        DNSRule.objects.create(
            name="global-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create location-specific rule (should override global)
        DNSRule.objects.create(
            name="location-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create device in the location
        device = Device.objects.create(
            name="test-location-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )

        # Assign primary IP so template works; signal handlers will trigger DNS processing
        device.primary_ip4 = self.ip_addresses[0]
        device.save()

        # Should create record from location rule, not global rule
        location_records = ARecord.objects.filter(name="test-location-device-loc")
        global_records = ARecord.objects.filter(name="test-location-device")

        self.assertEqual(location_records.count(), 1)
        self.assertEqual(global_records.count(), 0)

        # Verify the record is in the correct zone and has correct IP
        location_record = location_records.first()
        self.assertEqual(location_record.zone.name, "example.com")
        self.assertEqual(location_record.address, self.ip_addresses[0])

    def test_global_rule_fallback_when_no_location_rules(self):
        """Test that global rules are used when no location-specific rules exist."""
        # Create only global rule
        DNSRule.objects.create(
            name="global-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create device in location
        # No location-specific rules exist, so should use global rule
        device = Device.objects.create(
            name="test-global-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )

        # Assign primary IP so template works; signal handlers will trigger DNS processing
        device.primary_ip4 = self.ip_addresses[0]
        device.save()

        # Should create record from global rule
        global_records = ARecord.objects.filter(name="test-global-device")
        self.assertEqual(global_records.count(), 1)

        # Verify the record is in the correct zone and has correct IP
        global_record = global_records.first()
        self.assertEqual(global_record.zone.name, "example.com")
        self.assertEqual(global_record.address, self.ip_addresses[0])

    def test_interface_inherits_device_location(self):
        """Test that Interface objects inherit location from their Device for rule processing."""
        # Create location-specific rule for interfaces
        DNSRule.objects.create(
            name="location-interface-rule",
            content_type=ContentType.objects.get_for_model(Interface),
            location=self.location,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first().id }}",
        )

        # Create device and interface
        device = Device.objects.create(
            name="test-interface-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )

        interface = Interface.objects.create(
            name="eth0",
            device=device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Add IP to interface (signal handlers should trigger DNS processing)
        # Interface should inherit location from device for rule processing
        interface.ip_addresses.add(self.ip_addresses[0])

        # Should create record using location rule (interface inherits device location)
        interface_records = ARecord.objects.filter(name="eth0.test-interface-device")
        self.assertEqual(interface_records.count(), 1)

        # Verify the record is in the correct zone and has correct IP
        interface_record = interface_records.first()
        self.assertEqual(interface_record.zone.name, "example.com")
        self.assertEqual(interface_record.address, self.ip_addresses[0])

    def test_device_location_change_updates_dns_records(self):
        """Test that DNS records are updated when a device moves between locations."""
        # Create second location
        location_type_2 = LocationType.objects.create(name="Site 2")
        location_type_2.content_types.add(ContentType.objects.get_for_model(Device))
        location_2 = Location.objects.create(
            name="Test Site 2",
            location_type=location_type_2,
            status=Status.objects.get_for_model(Location).first(),
        )

        # Create location-specific rules for both locations
        DNSRule.objects.create(
            name="location-1-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc1",
            value_template="{{ obj.primary_ip4 }}",
        )

        DNSRule.objects.create(
            name="location-2-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=location_2,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc2",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Create device in location 1 with primary IP assigned
        device = Device.objects.create(
            name="test-moving-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )

        # Assign primary IP after creation - this triggers the problematic pattern
        device.primary_ip4 = self.ip_addresses[0]
        device.save()

        # Should have location-1 record
        loc1_records = ARecord.objects.filter(name="test-moving-device-loc1")
        loc2_records = ARecord.objects.filter(name="test-moving-device-loc2")
        self.assertEqual(loc1_records.count(), 1)
        self.assertEqual(loc2_records.count(), 0)

        # Move device to location 2; signal handlers should update DNS records
        device.location = location_2
        device.save()

        # Should now have location-2 record, not location-1 record
        loc1_records = ARecord.objects.filter(name="test-moving-device-loc1")
        loc2_records = ARecord.objects.filter(name="test-moving-device-loc2")
        self.assertEqual(loc1_records.count(), 0)
        self.assertEqual(loc2_records.count(), 1)

    def test_multi_record_cleanup_on_ip_removal(self):
        """
        Test that removing IP from interface properly cleans up all related DNS records.

        This tests the critical multi-record cleanup gap where:
        - Rule creates multiple A records (one per IP)
        - IP is removed from interface
        - All old records must be cleaned up properly
        - No orphaned DNS records or tracking records should remain
        """
        # Create device and interface
        device = Device.objects.create(
            name="test-device",
            device_type=self.device_type,
            location=self.location,
            status=self.device_status,
            role=self.device_role,
        )

        interface = Interface.objects.create(
            device=device,
            name="eth0",
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Create DNS rule FIRST (before IP assignment)
        interface_content_type = ContentType.objects.get_for_model(Interface)

        rule = DNSRule.objects.create(
            name="Multi-A Record Rule",
            content_type=interface_content_type,
            record_type="A",
            enabled=True,
            zone_template=self.dns_zone.name,
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",  # Multi-IP template
        )

        # Assign all 3 IPs to interface (triggers M2M signal → automatic DNS processing)
        interface.ip_addresses.set(self.ip_addresses[0:3])

        # Verify 3 A records and 3 tracking records were created via signal
        a_records_after_add = ARecord.objects.filter(zone=self.dns_zone)
        # rule_records_after_add = DNSRuleRecord.objects.filter(rule=rule)

        self.assertEqual(a_records_after_add.count(), 3, "Should create 3 A records initially")
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=rule).count(), 3, "Should create 3 tracking records initially"
        )

        # Verify A records point to correct IPs
        created_ips = {str(record.address_id) for record in a_records_after_add}
        expected_ips = {str(ip.id) for ip in self.ip_addresses[0:3]}
        self.assertEqual(created_ips, expected_ips, "A records should point to all 3 IPs")

        # Remove IPs one at a time and verify at each step
        assigned = list(self.ip_addresses[0:3])
        removal_order = [assigned[1], assigned[2], assigned[0]]
        remaining = {str(ip.id) for ip in assigned}

        for ip in removal_order:
            interface.ip_addresses.remove(ip)
            remaining.discard(str(ip.id))

            a_records_after = ARecord.objects.filter(zone=self.dns_zone)
            rule_records_after = DNSRuleRecord.objects.filter(rule=rule)

            # Counts should match remaining IPs
            self.assertEqual(a_records_after.count(), len(remaining))
            self.assertEqual(rule_records_after.count(), len(remaining))

            # A records should exactly match remaining IPs
            self.assertEqual({str(r.address_id) for r in a_records_after}, remaining)

            # No orphans: every DNS record must have a tracking record
            self.assertEqual(
                {str(rr.dns_record_object_id) for rr in rule_records_after},
                {str(ar.id) for ar in a_records_after},
            )

    def test_a_records_deleted_when_interface_deleted_multiple_ips(self):
        """
        Test that all A records are deleted when interface with multiple IPs is deleted.

        This tests cascade deletion scenario where:
        - Interface has multiple IPs with multiple A records
        - Interface itself is deleted
        - All A records and tracking records should be cleaned up via signal handling
        """
        # Create device and interface
        device = Device.objects.create(
            name="test-device",
            device_type=self.device_type,
            location=self.location,
            status=self.device_status,
            role=self.device_role,
        )

        interface = Interface.objects.create(
            device=device,
            name="eth0",
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Create DNS rule for A records
        interface_content_type = ContentType.objects.get_for_model(Interface)

        rule = DNSRule.objects.create(
            name="Interface A Record Rule",
            content_type=interface_content_type,
            record_type="A",
            enabled=True,
            zone_template=self.dns_zone.name,
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        interface.ip_addresses.add(self.ip_addresses[0], self.ip_addresses[1], self.ip_addresses[2])

        # Verify multiple A records were created
        a_records = ARecord.objects.filter(zone=self.dns_zone)
        rule_records = DNSRuleRecord.objects.filter(rule=rule)

        self.assertEqual(a_records.count(), 3, "Should create 3 A records for 3 IPs")
        self.assertEqual(rule_records.count(), 3, "Should create 3 tracking records")

        # Verify A records point to correct IPs
        created_ips = {str(record.address_id) for record in a_records}
        expected_ips = {str(self.ip_addresses[0].id), str(self.ip_addresses[1].id), str(self.ip_addresses[2].id)}
        self.assertEqual(created_ips, expected_ips, "A records should point to all 3 IPs")

        # Delete the interface (triggers cascade deletion)
        interface_id = interface.id
        interface.delete()

        # Verify all A records were deleted via signal handling
        remaining_a_records = ARecord.objects.filter(zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0, "All A records should be deleted when interface is deleted")

        # Verify all tracking records were cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(
            rule=rule,
            object_id=interface_id,  # Check for specific interface that was deleted
        )
        self.assertEqual(
            remaining_rule_records.count(), 0, "All tracking records should be cleaned up when interface is deleted"
        )

    def test_service_dns_record_creation_end_to_end(self):
        """Test complete Service DNS record creation workflow."""
        # Create service DNS rule
        service_rule = DNSRule.objects.create(
            name="service-a-record-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Initially no DNS records
        self.assertEqual(ARecord.objects.filter(name="web-service").count(), 0)

        # Assign IP to service
        self.service_device_attached.ip_addresses.add(self.ip_addresses[0])

        # Verify DNS record creation
        a_records = ARecord.objects.filter(name="web-service", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)
        self.assertEqual(str(a_records.first().address_id), str(self.ip_addresses[0].id))

        # Verify tracking record
        rule_records = DNSRuleRecord.objects.filter(rule=service_rule, object_id=self.service_device_attached.id)
        self.assertEqual(rule_records.count(), 1)

    def test_service_multi_ip_dns_records(self):
        """Test Service with multiple IP addresses creates multiple DNS records."""
        DNSRule.objects.create(
            name="service-multi-ip-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Assign multiple IPs
        self.service_device_attached.ip_addresses.add(self.ip_addresses[0], self.ip_addresses[1])

        # Verify multiple DNS records
        a_records = ARecord.objects.filter(name="web-service", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 2)

        # Verify both IPs are represented
        record_ips = {str(record.address_id) for record in a_records}
        expected_ips = {str(self.ip_addresses[0].id), str(self.ip_addresses[1].id)}
        self.assertEqual(record_ips, expected_ips)

    def test_service_deletion_cleans_up_dns_records(self):
        """Test Service deletion cleans up associated DNS records."""
        DNSRule.objects.create(
            name="service-cleanup-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Create DNS records
        self.service_device_attached.ip_addresses.add(self.ip_addresses[0])
        self.assertEqual(ARecord.objects.filter(name="web-service").count(), 1)

        # Delete service (should trigger cleanup)
        self.service_device_attached.delete()

        # Verify cleanup
        self.assertEqual(ARecord.objects.filter(name="web-service").count(), 0)
        self.assertEqual(DNSRuleRecord.objects.filter(object_id=self.service_device_attached.id).count(), 0)

    def test_service_differential_record_reconciliation(self):
        """Test Service record reconciliation preserves existing record IDs."""
        DNSRule.objects.create(
            name="service-reconciliation-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Add first IP
        self.service_device_attached.ip_addresses.add(self.ip_addresses[0])
        first_record = ARecord.objects.filter(name="web-service").first()

        # Add second IP
        self.service_device_attached.ip_addresses.add(self.ip_addresses[1])

        # Verify first record ID is preserved
        records_after = ARecord.objects.filter(name="web-service")
        self.assertEqual(records_after.count(), 2)

        record_for_ip1 = records_after.filter(address_id=self.ip_addresses[0].id).first()
        self.assertEqual(record_for_ip1.id, first_record.id)  # Should NOT be recreated

    def test_service_name_change_triggers_dns_update(self):
        """Test Service name change triggers DNS rule re-evaluation and updates DNS record name."""
        # Create service DNS rule that uses service name in the name template
        service_rule = DNSRule.objects.create(
            name="service-name-change-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",  # Uses service name
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Assign IP to service and verify initial DNS record
        self.service_device_attached.ip_addresses.add(self.ip_addresses[0])

        # Verify initial DNS record with original service name
        initial_records = ARecord.objects.filter(name="web-service", zone=self.dns_zone)
        self.assertEqual(initial_records.count(), 1, "Initial DNS record should be created")

        #
        # We need to store the ID of the initial record because it will be deleted when we save
        # the service, rendeing the queryset useless
        initial_record_id = initial_records.first().id

        # Change the service name
        self.service_device_attached.name = "api-gateway"
        self.service_device_attached.save()

        # Verify original record UUID no longer exists
        with self.assertRaises(ARecord.DoesNotExist):
            ARecord.objects.get(id=initial_record_id)

        # Verify new DNS record is created with updated name
        new_records = ARecord.objects.filter(name="api-gateway", zone=self.dns_zone)
        self.assertEqual(new_records.count(), 1, "New DNS record should be created with updated name")
        new_record = new_records.first()

        # Verify it points to the same IP (delete+create behavior)
        self.assertEqual(str(new_record.address_id), str(self.ip_addresses[0].id), "Should point to same IP")

        # Verify tracking record is updated to point to the new record
        rule_records = DNSRuleRecord.objects.filter(rule=service_rule, object_id=self.service_device_attached.id)
        self.assertEqual(rule_records.count(), 1, "Should have one tracking record")
        self.assertEqual(rule_records.first().dns_record.id, new_record.id, "Tracking should point to new record")

    def test_ipaddresstointerface_add_creates_dns_record(self):
        """Test that creating an IPAddressToInterface relationship creates a DNS record."""

        self._create_dns_rule_for_interface_a_record()

        ipaddresstointerface = IPAddressToInterface.objects.create(
            ip_address=self.ip_addresses[0],
            interface=self.interface,
        )
        rule_records = DNSRuleRecord.objects.filter(object_id=self.interface.pk)
        self.assertEqual(rule_records.count(), 1)

        arecord = ARecord.objects.get(address=ipaddresstointerface.ip_address)
        self.assertEqual(arecord.address, self.ip_addresses[0])

    def test_ipaddresstointerface_delete_deletes_dns_record(self):
        """Test that deleting an IPAddressToInterface relationship deletes a DNS record."""
        self._create_dns_rule_for_interface_a_record()
        ipaddresstointerface = IPAddressToInterface.objects.create(
            ip_address=self.ip_addresses[0],
            interface=self.interface,
        )
        rule_records = DNSRuleRecord.objects.filter(object_id=self.interface.pk)
        self.assertEqual(rule_records.count(), 1)
        self.assertEqual(ARecord.objects.count(), 1)

        ipaddresstointerface.delete()
        self.assertEqual(ARecord.objects.count(), 0)


class RuleValidationTestCase(BaseRuleEngineMixin, TestCase):
    """Template validation, runtime errors, filter validation."""

    @classmethod
    def setUpTestData(cls):
        """Set up additional test data for validation tests."""
        super().setUpTestData()

        # Assign IP address to interface for validation tests
        cls.interface.ip_addresses.add(cls.ip_addresses[0])

    def test_rule_validation_a_record_without_value_template(self):
        """Test that A records without value_template are allowed - runtime will handle gracefully."""
        rule = DNSRule(
            name="No Value Template Rule",
            content_type=self.interface_content_type,
            record_type="A",
            enabled=True,
            zone_template="test.local",
            name_template="{{ obj.name }}",
            # No value_template - should be allowed
        )

        # Should NOT raise ValidationError - runtime will handle gracefully
        try:
            rule.clean()  # Should succeed
        except ValidationError:
            self.fail("A/AAAA records without value_template should be allowed - runtime handles gracefully")

        # Note: Runtime behavior will be:
        # - Log warning about missing value_template
        # - Return empty list (no records created)
        # - Could potentially implement smart defaults in the future

    def test_rule_validation_allows_valid_templates(self):
        """Test that valid templates pass validation."""
        rule = DNSRule(
            name="Valid Rule",
            content_type=self.interface_content_type,
            record_type="A",
            enabled=True,
            zone_template="test.local",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",  # Valid
        )

        # Should not raise any exceptions
        try:
            rule.clean()
        except ValidationError:
            self.fail("Valid template should not raise ValidationError")

    def test_rule_validation_with_runtime_template_warning(self):
        """Test that templates with potential runtime issues generate warnings but don't block save."""
        # Template that might fail at runtime depending on data (obj.missing_attr)
        rule = DNSRule(
            name="Runtime Warning Rule",
            content_type=self.interface_content_type,
            record_type="A",
            enabled=True,
            zone_template="test.local",
            name_template="{{ obj.name }}",
            value_template="{{ obj.nonexistent_attribute }}",  # May fail at runtime
        )

        # This should NOT raise ValidationError (just logs warning)
        try:
            rule.clean()  # Should succeed despite potential runtime issues
        except ValidationError as e:
            # If there's a ValidationError, it should NOT be about runtime issues
            error_dict = e.message_dict
            for _, messages in error_dict.items():
                # messages is a list, so join and check
                combined_message = " ".join(messages).lower()
                self.assertNotIn("runtime issues", combined_message)

    @override_settings(
        DEBUG=True,
        LOGGING=TEST_LOGGING_CONFIG,
    )
    def test_template_failure_preserves_existing_records(self): # pylint: disable=too-many-locals
        """Test that existing DNS records are not deleted when template rendering fails."""
        # Create a DNS rule for interface IPs with a template that will fail on interfaces without roles
        dns_rule = DNSRule.objects.create(
            name="interface-ip-with-role-rule",
            description="Create A records from interface IPs, requires role",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.role.name }}.{{ obj.name }}.{{ obj.device.name }}",  # This will fail if no role
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

        # Create a test device
        test_device = Device.objects.create(
            name="multi-interface-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )

        # Create interfaces, two with a role, one without
        interfaces_with_role = {}
        for i in range(1, 3):
            interfaces_with_role[f"eth{i}"] = Interface.objects.create(
                name=f"eth{i}",
                device=test_device,
                type=InterfaceTypeChoices.TYPE_1GE_FIXED,
                status=self.interface_status,
                role=self.interface_role,
            )

        interface_no_role = Interface.objects.create(
            name=f"eth{i+1}",
            device=test_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        # Assign IPs to interfaces (this should trigger DNS record creation via M2M signals)
        interfaces_with_role["eth1"].ip_addresses.add(self.ip_addresses[0])
        interfaces_with_role["eth2"].ip_addresses.add(self.ip_addresses[1])

        # Verify DNS records were created for interfaces 1 and 2
        normalized_name_1 = normalize_dns_name(f"{self.interface_role.name}.eth1.{test_device.name}")
        normalized_name_2 = normalize_dns_name(f"{self.interface_role.name}.eth2.{test_device.name}")
        a_records_1 = ARecord.objects.filter(name=normalized_name_1, zone=self.dns_zone)
        a_records_2 = ARecord.objects.filter(name=normalized_name_2, zone=self.dns_zone)

        self.assertEqual(a_records_1.count(), 1, "DNS record should be created for interface 1")
        self.assertEqual(a_records_2.count(), 1, "DNS record should be created for interface 2")

        # Verify tracking records were created
        rule_records_1 = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interfaces_with_role["eth1"].id)
        rule_records_2 = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interfaces_with_role["eth2"].id)

        self.assertEqual(rule_records_1.count(), 1, "Tracking record should exist for interface 1")
        self.assertEqual(rule_records_2.count(), 1, "Tracking record should exist for interface 2")

        # Now create IP for interface 3 (no role) - this should cause template failure
        ip_without_role = IPAddress.objects.create(
            address="192.168.1.103/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=self.prefix,
        )

        # Assign IP to interface 3 - this should trigger template failure but not affect other records
        interface_no_role.ip_addresses.add(ip_without_role)

        # Verify that existing DNS records for interfaces 1 and 2 are NOT deleted
        a_records_1_after = ARecord.objects.filter(name=normalized_name_1, zone=self.dns_zone)
        a_records_2_after = ARecord.objects.filter(name=normalized_name_2, zone=self.dns_zone)

        self.assertEqual(
            a_records_1_after.count(), 1, "Interface 1 DNS record should NOT be deleted on template failure"
        )
        self.assertEqual(
            a_records_2_after.count(), 1, "Interface 2 DNS record should NOT be deleted on template failure"
        )

        # Verify no DNS record was created for interface 3 (template failure)
        # Note: We can't predict the exact name since the template will fail on the role part
        a_records_3 = ARecord.objects.filter(name=interface_no_role.name, zone=self.dns_zone)
        self.assertEqual(
            a_records_3.count(), 0, "No DNS record should be created for interface 3 due to template failure"
        )

        # Verify tracking records for interfaces 1 and 2 still exist
        rule_records_1_after = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interfaces_with_role["eth1"].id)
        rule_records_2_after = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interfaces_with_role["eth2"].id)

        self.assertEqual(rule_records_1_after.count(), 1, "Interface 1 tracking record should be preserved")
        self.assertEqual(rule_records_2_after.count(), 1, "Interface 2 tracking record should be preserved")

    def test_arecord_rule_with_ipv6_address_handles_validation_error(self):
        """Test that a DNS rule for A records gracefully handles ValidationError when IPv6 address is provided."""
        # Create a DNS rule for A records
        dns_rule = DNSRule.objects.create(
            name="interface-a-record-rule",
            description="Create A records from interface IPs",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )
        interface = Interface.objects.create(
            name="eth0-v6-test",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Verify no A records exist initially
        initial_a_records = ARecord.objects.filter(name=f"{interface.name}.{self.device.name}", zone=self.dns_zone)
        self.assertEqual(initial_a_records.count(), 0)

        # Assign IPv6 address to interface (invalid for A record)
        # This should trigger the rule engine via signals, which will catch ValidationError
        interface.ip_addresses.add(self.ipv6_addresses[0])

        # Verify no A record was created (ValidationError should have been caught)
        final_a_records = ARecord.objects.filter(name=f"{interface.name}.{self.device.name}", zone=self.dns_zone)
        self.assertEqual(
            final_a_records.count(),
            0,
            "No A record should be created when rule tries to assign IPv6 address to A record",
        )

        # Verify no tracking records were created either
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interface.id)
        self.assertEqual(rule_records.count(), 0, "No tracking records should be created when validation fails")

    def test_aaaarecord_rule_with_ipv4_address_handles_validation_error(self):
        """Test that a DNS rule for AAAA records gracefully handles ValidationError when IPv4 address is provided."""
        # Create a DNS rule for AAAA records
        dns_rule = DNSRule.objects.create(
            name="interface-aaaa-record-rule",
            description="Create AAAA records from interface IPs",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="AAAA",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        interface = Interface.objects.create(
            name="eth0-v4-test",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Verify no AAAA records exist initially
        initial_aaaa_records = AAAARecord.objects.filter(
            name=f"{interface.name}.{self.device.name}", zone=self.dns_zone
        )
        self.assertEqual(initial_aaaa_records.count(), 0)

        # Assign IPv4 address to interface (invalid for AAAA record)
        # This should trigger the rule engine via signals, which will catch ValidationError
        interface.ip_addresses.add(self.ip_addresses[0])

        # Verify no AAAA record was created (ValidationError should have been caught)
        final_aaaa_records = AAAARecord.objects.filter(name=f"{interface.name}.{self.device.name}", zone=self.dns_zone)
        self.assertEqual(
            final_aaaa_records.count(),
            0,
            "No AAAA record should be created when rule tries to assign IPv4 address to AAAA record",
        )

        # Verify no tracking records were created either
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interface.id)
        self.assertEqual(rule_records.count(), 0, "No tracking records should be created when validation fails")

    def test_arecord_rule_filters_ipv6_from_mixed_addresses(self):
        """Test that an A record rule only creates records for IPv4 addresses when interface has both IPv4 and IPv6."""
        # Create a DNS rule for A records
        dns_rule = DNSRule.objects.create(
            name="interface-mixed-ip-rule",
            description="Create A records from interface IPs (should filter IPv6)",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        interface = Interface.objects.create(
            name="eth0-mixed",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Assign 3 IPv4 and 3 IPv6 addresses to interface. Zip them to v4,v6,v4,v6 order to ensure we
        # don't do all one one version first, just in case doing so masks a problem.
        v4_and_v6_addresses = list(itertools.chain.from_iterable(zip(self.ip_addresses[:3], self.ipv6_addresses[:3])))
        interface.ip_addresses.set(v4_and_v6_addresses)
        self.assertEqual(interface.ip_addresses.count(), 6)

        # Verify only 3 A records were created (one for each IPv4 address)
        a_records = ARecord.objects.filter(name=f"{interface.name}.{self.device.name}", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 3, "Should create exactly 3 A records for 3 IPv4 addresses")

        # Verify no AAAA records were created
        aaaa_records = AAAARecord.objects.filter(name=f"{interface.name}.{self.device.name}", zone=self.dns_zone)
        self.assertEqual(aaaa_records.count(), 0, "Should not create any AAAA records")

        # Verify the A records point to IPv4 addresses only
        created_addresses = {record.address for record in a_records}
        expected_ipv4_addresses = set(self.ip_addresses)
        self.assertEqual(
            created_addresses,
            expected_ipv4_addresses,
            "A records should only contain IPv4 addresses",
        )

        # Verify exactly 3 tracking records were created (one per A record)
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interface.id)
        self.assertEqual(rule_records.count(), 3, "Should create exactly 3 tracking records for 3 A records")

        # Verify each tracking record corresponds to an A record
        for rule_record in rule_records:
            self.assertIsInstance(rule_record.dns_record, ARecord)
            self.assertIn(rule_record.dns_record.address, expected_ipv4_addresses)

    def test_aaaarecord_rule_filters_ipv4_from_mixed_addresses(self):
        """Test that an AAAA record rule only creates records for IPv6 addresses when interface has both IPv4 and IPv6."""
        # Create a DNS rule for AAAA records
        dns_rule = DNSRule.objects.create(
            name="interface-mixed-ip-aaaa-rule",
            description="Create AAAA records from interface IPs (should filter IPv4)",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="AAAA",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        interface = Interface.objects.create(
            name="eth0-mixed-aaaa",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Assign 3 IPv4 and 3 IPv6 addresses to interface. Zip them to v4,v6,v4,v6 order to ensure we
        # don't do all one one version first, just in case doing so masks a problem.
        v4_and_v6_addresses = list(itertools.chain.from_iterable(zip(self.ip_addresses[:3], self.ipv6_addresses[:3])))
        interface.ip_addresses.set(v4_and_v6_addresses)
        self.assertEqual(interface.ip_addresses.count(), 6)
        print(f"\n\ninterface.ip_addresses.all(): {interface.ip_addresses.all()}\n")

        # Verify only 3 AAAA records were created (one for each IPv6 address)
        aaaa_records = AAAARecord.objects.filter(name=f"{interface.name}.{self.device.name}", zone=self.dns_zone)
        self.assertEqual(aaaa_records.count(), 3, "Should create exactly 3 AAAA records for 3 IPv6 addresses")

        # Verify no A records were created
        a_records = ARecord.objects.filter(name=f"{interface.name}.{self.device.name}", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 0, "Should not create any A records")

        # Verify the AAAA records point to IPv6 addresses only
        created_addresses = {record.address for record in aaaa_records}
        expected_ipv6_addresses = set(self.ipv6_addresses)
        self.assertEqual(
            created_addresses,
            expected_ipv6_addresses,
            "AAAA records should only contain IPv6 addresses",
        )

        # Verify exactly 3 tracking records were created (one per AAAA record)
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interface.id)
        self.assertEqual(rule_records.count(), 3, "Should create exactly 3 tracking records for 3 AAAA records")

        # Verify each tracking record corresponds to an AAAA record
        for rule_record in rule_records:
            self.assertIsInstance(rule_record.dns_record, AAAARecord)
            self.assertIn(rule_record.dns_record.address, expected_ipv6_addresses)

    def test_multiple_ips_preserves_existing_records(self):
        """Test that adding a second IP to an interface doesn't delete/recreate the first DNS record."""
        # Create a DNS rule for interface IPs
        dns_rule = DNSRule.objects.create(
            name="interface-multi-ip-rule",
            description="Create A records from interface IPs",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        # Create a test device and interface
        test_device = Device.objects.create(
            name="multi-ip-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )

        test_interface = Interface.objects.create(
            name="eth0",
            device=test_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        test_interface.ip_addresses.add(self.ip_addresses[0])

        # Verify first DNS record was created
        a_records = ARecord.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1, "First DNS record should be created")

        first_record = a_records.first()
        first_record_id = first_record.id
        first_record_address_id = first_record.address_id

        # Verify it points to the first IP
        self.assertEqual(
            str(first_record_address_id), str(self.ip_addresses[0].id), "First record should point to first IP"
        )

        test_interface.ip_addresses.add(self.ip_addresses[1])

        # Verify we now have TWO DNS records (one for each IP)
        a_records_after = ARecord.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
        self.assertEqual(a_records_after.count(), 2, "Should have two DNS records (one per IP)")

        # Get records by IP address to verify both exist
        record_for_ip1 = a_records_after.filter(address_id=self.ip_addresses[0].id).first()
        record_for_ip2 = a_records_after.filter(address_id=self.ip_addresses[1].id).first()

        self.assertIsNotNone(record_for_ip1, "Should have DNS record for first IP")
        self.assertIsNotNone(record_for_ip2, "Should have DNS record for second IP")

        # Critical test: The first record ID should be the same (not deleted and recreated)
        self.assertEqual(record_for_ip1.id, first_record_id, "First DNS record should NOT be deleted and recreated")

        # Verify tracking records exist for both IPs
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=test_interface.id)
        self.assertEqual(rule_records.count(), 2, "Should have two tracking records (one per IP)")

        # Remove the first IP to test that only its record is deleted
        test_interface.ip_addresses.remove(self.ip_addresses[0])

        # Verify only the second IP's record remains
        a_records_final = ARecord.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
        self.assertEqual(a_records_final.count(), 1, "Should have one DNS record after removing first IP")

        final_record = a_records_final.first()
        self.assertEqual(
            str(final_record.address_id), str(self.ip_addresses[1].id), "Remaining record should point to second IP"
        )

        # Verify only one tracking record remains
        rule_records_final = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=test_interface.id)
        self.assertEqual(rule_records_final.count(), 1, "Should have one tracking record after IP removal")

    @skip(
        "Skipping test_service_rule_uniqueness_validation since we currently don't disallow two rules with the same content_type + record_type"
    )
    def test_service_rule_uniqueness_validation(self):
        """Test Service rule uniqueness constraints."""
        # Create first rule (global rule: location=None, tenant=None, enabled=True)
        DNSRule.objects.create(
            name="service-rule-1",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
            # location=None, tenant=None (global rule)
        )

        # Attempt to create duplicate global rule (should fail due to uniqueness constraint)
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="service-rule-2",
                content_type=self.service_content_type,
                record_type="A",  # Same content_type + record_type + location + tenant
                zone_template="example.com",
                name_template="{{ obj.name }}",
                value_template="{{ obj.ip_addresses.all() }}",
                enabled=True,
                # location=None, tenant=None (same as first rule)
            )
            rule.clean()  # This should trigger the uniqueness validation


class RuleEngineTemplateProxyIntegrationTest(BaseRuleEngineMixin, TestCase):
    """Integration checks for template proxies within the rule engine."""

    def test_interface_first_renders_uuid(self):
        """Interface value template using first() should render the first IP UUID."""
        rule = DNSRule.objects.create(
            name="interface-first",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
        )
        self.interface.ip_addresses.set([self.ip_addresses[0], self.ip_addresses[1]])

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["address_id"], str(self.ip_addresses[0].pk))

    def test_interface_last_empty(self):
        """Interface last() should raise DNSTemplateEmptyError when no IPs exist."""
        rule = DNSRule.objects.create(
            name="interface-last-empty",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.last() }}",
        )
        self.interface.ip_addresses.clear()

        with self.assertRaises(DNSTemplateEmptyError):
            self._calc_desired_record_data(rule, self.interface)

    def test_interface_filter_first_and_last(self):
        """Interface filter(...).first()/last() should render UUIDs respecting the filter."""
        rule = DNSRule.objects.create(
            name="interface-filter",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.filter(ip_version=4).first() }} {{ obj.ip_addresses.filter(ip_version=4).last() }}",
        )
        self.interface.ip_addresses.set([self.ip_addresses[0], self.ip_addresses[1]])

        results = self._calc_desired_record_data(rule, self.interface)
        # Expect two records: one for first() and one for last()
        self.assertEqual(len(results), 2)
        returned_ids = {record["address_id"] for record in results}
        expected_ids = {str(self.ip_addresses[0].pk), str(self.ip_addresses[1].pk)}
        self.assertEqual(returned_ids, expected_ids)

    def test_interface_filter_ipv4_only(self):
        """Interface filter(ip_version=4) should ignore IPv6 addresses."""
        rule = DNSRule.objects.create(
            name="interface-filter-list",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.filter(ip_version=4) }}",
        )
        self.interface.ip_addresses.set([self.ip_addresses[0], self.ip_addresses[1], self.ipv6_addresses[0]])

        results = self._calc_desired_record_data(rule, self.interface)
        returned_ids = {record["address_id"] for record in results}
        expected_ids = {str(self.ip_addresses[0].pk), str(self.ip_addresses[1].pk)}
        self.assertEqual(returned_ids, expected_ids)

    def test_service_filter_all(self):
        """Service filter(...).all() should yield records for each matching IP UUID."""
        rule = DNSRule.objects.create(
            name="service-filter-all",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.filter(ip_version=4).all() }}",
        )
        self.service_device_attached.ip_addresses.set([self.ip_addresses[0], self.ip_addresses[1]])

        results = self._calc_desired_record_data(rule, self.service_device_attached)
        returned_ids = {record["address_id"] for record in results}
        expected_ids = {str(self.ip_addresses[0].pk), str(self.ip_addresses[1].pk)}
        self.assertEqual(returned_ids, expected_ids)

    def test_filter_skips_invalid_uuid_values(self):
        """Invalid address IDs should be ignored when building record variations."""
        rule = DNSRule.objects.create(
            name="filter-invalid",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="invalid-uuid {{ obj.ip_addresses.all() }}",
        )
        # include valid IPs but template prepends an invalid literal
        self.interface.ip_addresses.set([self.ip_addresses[0]])

        results = self._calc_desired_record_data(rule, self.interface)
        # Only the valid UUID should produce a record
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["address_id"], str(self.ip_addresses[0].pk))
