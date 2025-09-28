"""
Reorganized DNS Rule Engine Tests

This file contains the same 52 test methods from test_rule_engine.py,
reorganized into logical test classes for better maintainability.

Categories:
- TemplateRenderingTestCase: Template rendering, syntax errors, undefined variables, error handling
- RuleResolutionTestCase: Rule resolution, location/tenant extraction, precedence logic, fallback scenarios
- IntegrationAndMultiRecordTestCase: End-to-end workflows, signal handlers, multi-IP scenarios, DNS record lifecycle
- RuleValidationTestCase: Template validation, runtime errors, filter validation
"""

from unittest import skip
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase
from jinja2 import TemplateError
from nautobot.core.utils.data import render_jinja2
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import IPAddress, IPAddressToInterface, Namespace, Prefix
from nautobot.tenancy.models import Tenant, TenantGroup
from nautobot.virtualization.models import Cluster, ClusterType, VirtualMachine, VMInterface

from nautobot_dns_models.exceptions import DNSTemplateEmptyError
from nautobot_dns_models.models import ARecord, DNSRule, DNSRuleRecord, DNSZone
from nautobot_dns_models.rule_engine import DNSRuleEngine


class BaseRuleEngineTestCase(TestCase):
    """Base test case with comprehensive setup data for all DNS rule engine tests."""

    @classmethod
    def setUpTestData(cls):
        """Set up comprehensive shared test data for all test cases."""
        # Create location infrastructure
        cls.location_type = LocationType.objects.create(name="Test Location Type")
        cls.location_type.content_types.add(ContentType.objects.get_for_model(Device))

        cls.location = Location.objects.create(
            name="Test Location",
            location_type=cls.location_type,
            status=Status.objects.get_for_model(Location).first(),
        )

        # Create tenant infrastructure
        cls.tenant_group = TenantGroup.objects.create(name="Test Tenant Group")
        cls.tenant = Tenant.objects.create(name="Test Tenant", tenant_group=cls.tenant_group)

        # Create device infrastructure
        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_type = DeviceType.objects.create(manufacturer=cls.manufacturer, model="Test Device Type")
        cls.device_role = Role.objects.create(name="Test Device Role")
        cls.device_role.content_types.add(ContentType.objects.get_for_model(Device))

        # Create shared device and interface for tests
        cls.device = Device.objects.create(
            name="test-device",
            device_type=cls.device_type,
            location=cls.location,
            role=cls.device_role,
            status=Status.objects.get_for_model(Device).first(),
        )

        cls.interface = Interface.objects.create(
            name="eth0",
            device=cls.device,
            type="1000base-t",
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Create namespace and prefix for IP addresses
        cls.namespace = Namespace.objects.create(name="Test Namespace")
        cls.prefix = Prefix.objects.create(
            network="192.168.1.0",
            prefix_length=24,
            namespace=cls.namespace,
            status=Status.objects.get_for_model(Prefix).first(),
        )

        cls.ip_status = Status.objects.get_for_model(IPAddress).first()
        # Create IP address within the namespace and associate with parent prefix
        cls.ip_address = IPAddress.objects.create(
            address="192.168.1.10/24",
            status=cls.ip_status,
            namespace=cls.namespace,
            parent=cls.prefix,
        )

        # Create DNS zone
        cls.dns_zone = DNSZone.objects.create(name="example.com")

        # Content types for validation tests
        cls.device_content_type = ContentType.objects.get_for_model(Device)
        cls.interface_content_type = ContentType.objects.get_for_model(Interface)

        # Additional status objects that some tests expect
        cls.device_status = Status.objects.get_for_model(Device).first()
        cls.status = Status.objects.get_for_model(Device).first()  # Alias for compatibility

    def setUp(self):
        """Set up test data."""
        self.engine = DNSRuleEngine()


class TemplateRenderingTestCase(BaseRuleEngineTestCase):
    """Template rendering, syntax errors, undefined variables, error handling."""

    def test_render_jinja2_with_undefined_variable(self):
        """Investigate what render_jinja2 does with undefined variables."""
        result = render_jinja2("{{ undefined_var }}", {})
        print(f"Undefined variable - Result: {repr(result)}")
        print(f"Undefined variable - Type: {type(result)}")
        print(f"Undefined variable - Length: {len(result)}")
        print(f"Undefined variable - Is empty string: {result == ''}")
        print(f"Undefined variable - Is None: {result is None}")
        # This will show us exactly what we get

    def test_render_jinja2_with_syntax_error(self):
        """Investigate what render_jinja2 does with syntax errors."""
        try:
            result = render_jinja2("{{ invalid }", {})
            self.fail(f"Expected exception but got result: {repr(result)}")
        except Exception as e:
            print(f"Syntax error - Exception type: {type(e).__name__}, Message: {e}")
            # This test will show us what actually happens

    def test_render_jinja2_with_attribute_error_dict(self):
        """Investigate what render_jinja2 does with missing dict keys."""
        try:
            result = render_jinja2("{{ obj.missing_attr }}", {"obj": {}})
            print(f"Dict attribute error - Result: {repr(result)}")
            # This might not throw an exception - let's see what we get
        except Exception as e:
            print(f"Dict attribute error - Exception type: {type(e).__name__}, Message: {e}")

    def test_render_jinja2_with_attribute_error_object(self):
        """Investigate what render_jinja2 does with missing object attributes."""

    def test_render_jinja2_with_none_object(self):
        """Investigate what render_jinja2 does when accessing attributes on None."""
        try:
            result = render_jinja2("{{ obj.missing_attr }}", {"obj": None})
            print(f"None attribute error - Result: {repr(result)}")
            # This is a common case when IP addresses are removed
        except Exception as e:
            print(f"None attribute error - Exception type: {type(e).__name__}, Message: {e}")

    def test_render_jinja2_with_array_index_error(self):
        """Investigate what render_jinja2 does with array index errors."""
        try:
            result = render_jinja2("{{ arr[5] }}", {"arr": [1, 2, 3]})
            print(f"Array index error - Result: {repr(result)}")
        except Exception as e:
            print(f"Array index error - Exception type: {type(e).__name__}, Message: {e}")

    def test_render_template_method_with_valid_template(self):
        """Test _render_template method with valid input."""
        result = self.engine._render_template("Hello {{ name }}", {"name": "World"}, "test_field")
        self.assertEqual(result, "Hello World")

    def test_render_template_method_with_undefined_variable(self):
        """Test _render_template method behavior with undefined variables."""
        # render_jinja2 returns empty string for undefined variables, which our method treats as an error
        with self.assertRaises(DNSTemplateEmptyError):
            self.engine._render_template("{{ undefined_var }}", {}, "test_field")

    def test_render_template_method_with_syntax_error(self):
        """Test _render_template method behavior with syntax errors."""
        # render_jinja2 throws TemplateSyntaxError, which we catch and re-raise as TemplateError
        with self.assertRaises(TemplateError):
            self.engine._render_template("{{ invalid }", {}, "test_field")

    def test_render_template_method_with_none_attribute(self):
        """Test _render_template method behavior when accessing attributes on None."""
        # This is the real-world case: when an IP is removed, obj.primary_ip4 becomes None
        # render_jinja2 returns empty string, which our method treats as an error
        with self.assertRaises(DNSTemplateEmptyError):
            self.engine._render_template(
                "{{ obj.primary_ip4.id }}", {"obj": type("MockObj", (), {"primary_ip4": None})()}, "test_field"
            )

    def test_render_template_method_with_array_index_error(self):
        """Test _render_template method behavior with array index errors."""
        # render_jinja2 throws UndefinedError for array index errors, which we catch and re-raise
        with self.assertRaises(TemplateError):
            self.engine._render_template(
                "{{ obj.ip_addresses[0].id }}", {"obj": type("MockInterface", (), {"ip_addresses": []})()}, "test_field"
            )

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
                    self.engine._render_template(template, context, "test_field")

    def test_render_template_method_valid_non_empty_result(self):
        """Test that valid non-empty results work correctly."""
        result = self.engine._render_template("{{ name }}", {"name": "test-value"}, "test_field")
        self.assertEqual(result, "test-value")

        # Test with zero (which is falsy but might be valid for MX/SRV fields)
        result = self.engine._render_template("{{ count }}", {"count": 0}, "test_field")
        self.assertEqual(result, "0")  # render_jinja2 converts 0 to "0" string

        # Test with False
        result = self.engine._render_template("{{ flag }}", {"flag": False}, "test_field")
        self.assertEqual(result, "False")  # render_jinja2 converts False to "False" string

    def test_what_does_no_such_element_actually_look_like(self):
        """Try to reproduce the '{{ no such element:' pattern we're checking for."""
        # Based on actual logs, this pattern occurs when accessing attributes on None
        # The pattern is: "{{ no such element: None['id'] }}"

        # Test case that should trigger the pattern (based on actual logs)
        test_cases = [
            # Case from actual logs: obj.primary_ip4.id when primary_ip4 is None
            ("{{ obj.primary_ip4.id }}", {"obj": type("MockDevice", (), {"primary_ip4": None})()}),
            # Case: None object attribute access
            ("{{ obj.attr.id }}", {"obj": type("MockObj", (), {"attr": None})()}),
        ]

        for template, context in test_cases:
            try:
                result = render_jinja2(template, context)
                print(f"Template: {template}")
                print(f"Result: {repr(result)}")
                print(f"Contains 'no such element': {'{{ no such element:' in result}")
                print("---")
            except Exception as e:
                print(f"Template: {template}")
                print(f"Exception: {type(e).__name__}: {e}")
                print("---")

    def test_render_template_method_catches_empty_results(self):
        """Test that our _render_template method catches empty results from template failures."""
        # Test case where template renders to empty string (most common failure mode)
        mock_obj = type("MockDevice", (), {"primary_ip4": None})()

        with self.assertRaises(DNSTemplateEmptyError) as context:
            self.engine._render_template("{{ obj.primary_ip4.id }}", {"obj": mock_obj}, "test_field")

        # The error should mention that template rendered empty
        error_message = str(context.exception)
        self.assertIn("Template test_field rendered empty", error_message)

    def test_render_template_method_catches_error_strings(self):
        """Test detection of '{{ no such element:' error strings (if we can reproduce them)."""
        # Note: This pattern might be environment-specific or occur in different contexts
        # For now, test that our detection logic works if such a string is returned

        # Mock render_jinja2 to return the error pattern
        error_string = "{{ no such element: None['id'] }}"

        with patch("nautobot_dns_models.rule_engine.render_jinja2", return_value=error_string):
            with self.assertRaises(DNSTemplateEmptyError) as context:
                self.engine._render_template("{{ obj.attr.id }}", {"obj": "test"}, "test_field")

            # The error should mention template rendered empty and contain the actual error pattern
            error_message = str(context.exception)
            self.assertIn("Template test_field rendered empty", error_message)
            self.assertIn("{{ no such element:", error_message)


class RuleResolutionTestCase(BaseRuleEngineTestCase):
    """Rule resolution, location/tenant extraction, precedence logic, fallback scenarios."""

    def test_get_object_location_device(self):
        """Test _get_object_location returns device.location for Device objects."""
        # Test location extraction
        result = self.engine._get_object_location(self.device)
        self.assertEqual(result, self.location)

    def test_get_object_location_interface(self):
        """Test _get_object_location returns interface.device.location for Interface objects."""
        # Test location extraction from interface
        result = self.engine._get_object_location(self.interface)
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
        result = self.engine._get_object_location(vm)
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
            value_template="{{ obj.primary_ip4.id }}",
        )

        # Create global rule (should be ignored when location rule exists)
        DNSRule.objects.create(
            name="global-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )

        rules = self.engine._get_applicable_rules(self.device)
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
            value_template="{{ obj.primary_ip4.id }}",
        )

        rules = self.engine._get_applicable_rules(self.device)
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

        rules = self.engine._get_applicable_rules(vm)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first(), global_rule)

    def test_get_applicable_rules_per_record_type_precedence_mixed_rules(self):
        """Test per-record-type precedence: location-specific A rule + global CNAME rule."""
        # Create location-specific A record rule
        location_a_rule = DNSRule.objects.create(
            name="location-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )

        # Create global CNAME record rule
        global_cname_rule = DNSRule.objects.create(
            name="global-cname-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,  # Global rule
            zone_template="global.example.com",
            record_type="CNAME",
            name_template="{{ obj.name }}-alias",
            value_template="{{ obj.name }}.example.com",
        )

        # Create global A record rule (should be overridden by location-specific)
        global_a_rule = DNSRule.objects.create(
            name="global-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,  # Global rule
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4.id }}",
        )

        rules = self.engine._get_applicable_rules(self.device)

        # Should get location-specific A rule + global CNAME rule (2 rules total)
        self.assertEqual(rules.count(), 2)

        # Verify we got the correct rules
        rule_names = {rule.name for rule in rules}
        self.assertIn(location_a_rule.name, rule_names)  # Location-specific A rule
        self.assertIn(global_cname_rule.name, rule_names)  # Global CNAME rule
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
            value_template="{{ obj.primary_ip4.id }}",
        )

        # Create global A record rule (should be overridden)
        DNSRule.objects.create(
            name="global-override-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="global.example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4.id }}",
        )

        rules = self.engine._get_applicable_rules(self.device)

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
            value_template="{{ obj.primary_ip4.id }}",
        )

        location_cname_rule = DNSRule.objects.create(
            name="location-cname-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="CNAME",
            name_template="{{ obj.name }}-alias",
            value_template="{{ obj.name }}.example.com",
        )

        location_mx_rule = DNSRule.objects.create(
            name="location-mx-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="location.example.com",
            record_type="MX",
            name_template="{{ obj.name }}-mail",
            value_template="mail.example.com",
            preference_template="10",
        )

        rules = self.engine._get_applicable_rules(self.device)

        # Should get all 3 location-specific rules
        self.assertEqual(rules.count(), 3)
        rule_names = {rule.name for rule in rules}
        expected_names = {location_a_rule.name, location_cname_rule.name, location_mx_rule.name}
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
            value_template="{{ obj.primary_ip4.id }}",
        )

        DNSRule.objects.create(
            name="tenant-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            tenant=self.tenant,
            zone_template="tenant.example.com",
            record_type="A",
            name_template="{{ obj.name }}-tenant",
            value_template="{{ obj.primary_ip4.id }}",
        )

        DNSRule.objects.create(
            name="location-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            tenant=None,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}-location",
            value_template="{{ obj.primary_ip4.id }}",
        )

        location_tenant_rule = DNSRule.objects.create(
            name="location-tenant-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            tenant=self.tenant,
            zone_template="location-tenant.example.com",
            record_type="A",
            name_template="{{ obj.name }}-location-tenant",
            value_template="{{ obj.primary_ip4.id }}",
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

        rules = self.engine._get_applicable_rules(device_with_both)

        # Should get the most specific rule (location+tenant)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first().name, location_tenant_rule.name)

    def test_get_applicable_rules_tenant_precedence_mixed_scoping(self):
        """Test mixed scoping: Location A rule + Tenant CNAME rule for same object."""
        # Create location-specific A rule
        location_a_rule = DNSRule.objects.create(
            name="location-a-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            tenant=None,
            zone_template="location.example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc",
            value_template="{{ obj.primary_ip4.id }}",
        )

        # Create tenant-specific CNAME rule
        tenant_cname_rule = DNSRule.objects.create(
            name="tenant-cname-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            tenant=self.tenant,
            zone_template="tenant.example.com",
            record_type="CNAME",
            name_template="{{ obj.name }}-alias",
            value_template="{{ obj.name }}.example.com",
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

        rules = self.engine._get_applicable_rules(device_with_both)

        # Should get both rules (different record types)
        self.assertEqual(rules.count(), 2)
        rule_names = {rule.name for rule in rules}
        expected_names = {location_a_rule.name, tenant_cname_rule.name}
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
            value_template="{{ obj.primary_ip4.id }}",
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

        rules = self.engine._get_applicable_rules(device_location_only)
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

        rules = self.engine._get_applicable_rules(device_tenant_only)
        self.assertEqual(rules.count(), 1)
        self.assertEqual(rules.first().name, global_rule.name)


class IntegrationAndMultiRecordTestCase(BaseRuleEngineTestCase):
    """End-to-end workflows, signal handlers, multi-IP scenarios, DNS record lifecycle."""

    def _create_dns_rule(self, name="interface-a-record-rule"):
        """Helper method to create a DNS rule for integration tests."""
        return DNSRule.objects.create(
            name=name,
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() | ip_address }}",
            enabled=True,
        )

    def test_interface_a_record_created_on_ip_addition_via_m2m_api(self):
        """Test that A records are created when IP is added to interface via Django M2M API."""
        # Create DNS rule for this test
        dns_rule = self._create_dns_rule()

        # Verify no A records exist initially
        initial_a_records = ARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Verify no DNSRuleRecord tracking exists initially
        initial_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule).count()
        self.assertEqual(initial_rule_records, 0)

        # Add IP address to interface (this should trigger A record creation)
        self.interface.ip_addresses.add(self.ip_address)

        # Verify A record was created
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        self.assertEqual(a_record.address, self.ip_address)
        self.assertEqual(a_record.name, "eth0.test-device")
        self.assertEqual(a_record.zone, self.dns_zone)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        rule_record = rule_records.first()
        self.assertEqual(rule_record.source_object, self.interface)
        self.assertEqual(rule_record.dns_record, a_record)

    def test_interface_a_record_deleted_on_ip_removal_via_m2m_api(self):
        """Test that A records are deleted when IP is removed from interface via Django M2M API."""
        # Create DNS rule for this test
        dns_rule = self._create_dns_rule()

        # Setup initial state with IP and A record
        self.interface.ip_addresses.add(self.ip_address)

        # Verify A record exists
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Verify DNSRuleRecord tracking exists
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        # Remove IP address from interface (this should trigger A record deletion)
        self.interface.ip_addresses.remove(self.ip_address)

        # Verify A record was deleted
        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0)

        # Verify DNSRuleRecord tracking was also cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(remaining_rule_records.count(), 0)

    def test_interface_a_record_removal_with_multiple_ips(self):
        """Test A record behavior when interface has multiple IPs and one is removed."""
        # Create DNS rule for this test
        self._create_dns_rule()

        # Create second IP address within the namespace and associate with parent prefix
        ip_address_2 = IPAddress.objects.create(
            address="192.168.1.11/24",
            status=Status.objects.get_for_model(IPAddress).first(),
            namespace=self.namespace,
            parent=self.prefix,
        )

        # Add both IP addresses to interface. In theory, should be add_ip_addresses, but see
        # https://github.com/nautobot/nautobot/issues/7728.
        self.interface.ip_addresses.add(self.ip_address, ip_address_2)

        # Verify A record was created (should use first IP)
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        # The record should use whichever IP is returned by .first()
        self.assertIn(a_record.address, [self.ip_address, ip_address_2])

        # Remove one IP address
        self.interface.ip_addresses.remove(self.ip_address)

        # Verify A record still exists (should now use the remaining IP)
        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 1)

        # The record should now point to the remaining IP
        updated_record = remaining_a_records.first()
        self.assertEqual(updated_record.address, ip_address_2)

        # Remove the last IP address
        self.interface.ip_addresses.remove(ip_address_2)

        # Now the A record should be deleted (template fails with no IPs)
        final_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(final_a_records.count(), 0)

    @skip("Requires Nautobot M2M signal improvements - see nautobot/nautobot#7728")
    def test_interface_a_record_created_on_ip_addition_via_custom_method(self):
        """Test that A records are created when IP is added to interface via custom add_ip_addresses method.

        NOTE: This test requires M2M signal improvements to work.
        The custom add_ip_addresses method needs to trigger M2M signals for DNS rules to fire.
        See: https://github.com/nautobot/nautobot/issues/7728

        WARNING: This functionality is currently UNTESTED in the standard test environment.
        """
        # Verify no A records exist initially
        initial_a_records = ARecord.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Create DNS rule for this test
        dns_rule = self._create_dns_rule()

        # Verify no DNSRuleRecord tracking exists initially
        initial_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule).count()
        self.assertEqual(initial_rule_records, 0)

        # Add IP address to interface using custom method (this should trigger A record creation)
        count = self.interface.add_ip_addresses(self.ip_address)
        self.assertEqual(count, 1)  # Verify return value

        # Verify A record was created
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        self.assertEqual(a_record.address, self.ip_address)
        self.assertEqual(a_record.name, "eth0.test-device")
        self.assertEqual(a_record.zone, self.dns_zone)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        rule_record = rule_records.first()
        self.assertEqual(rule_record.source_object, self.interface)
        self.assertEqual(rule_record.dns_record, a_record)

    @skip("Requires Nautobot M2M signal improvements - see nautobot/nautobot#7728")
    def test_interface_a_record_deleted_on_ip_removal_via_custom_method(self):
        """Test that A records are deleted when IP is removed from interface via custom remove_ip_addresses method.

        NOTE: This test requires M2M signal improvements to work.
        The custom remove_ip_addresses method needs to trigger M2M signals for DNS rules to fire.
        See: https://github.com/nautobot/nautobot/issues/7728

        WARNING: This functionality is currently UNTESTED in the standard test environment.
        """
        # Create DNS rule for this test
        dns_rule = self._create_dns_rule()

        # Setup initial state with IP and A record using M2M API
        self.interface.ip_addresses.add(self.ip_address)

        # Verify A record exists
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Verify DNSRuleRecord tracking exists
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        # Remove IP address from interface using custom method (this should trigger A record deletion)
        count = self.interface.remove_ip_addresses(self.ip_address)
        self.assertEqual(count, 1)  # Verify return value

        # Verify A record was deleted
        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0)

        # Verify DNSRuleRecord tracking was also cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(remaining_rule_records.count(), 0)

    @skip("Requires Nautobot M2M signal improvements - see nautobot/nautobot#7728")
    def test_interface_a_record_multiple_ips_via_custom_method(self):
        """Test A record behavior with multiple IPs using custom methods.

        NOTE: This test requires M2M signal improvements to work.
        The custom add_ip_addresses/remove_ip_addresses methods need to trigger M2M signals.
        See: https://github.com/nautobot/nautobot/issues/7728

        WARNING: This functionality is currently UNTESTED in the standard test environment.
        """
        # Create second IP address within the namespace and associate with parent prefix
        ip_address_2 = IPAddress.objects.create(
            address="192.168.1.11/24",
            status=Status.objects.get_for_model(IPAddress).first(),
            namespace=self.namespace,
            parent=self.prefix,
        )

        # Add both IP addresses to interface using custom method
        count = self.interface.add_ip_addresses([self.ip_address, ip_address_2])
        self.assertEqual(count, 2)  # Both IPs should be added

        # Verify A record was created (should use first IP)
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        # The record should use whichever IP is returned by .first()
        self.assertIn(a_record.address, [self.ip_address, ip_address_2])

        # Remove one IP address using custom method
        count = self.interface.remove_ip_addresses(self.ip_address)
        self.assertEqual(count, 1)  # One IP should be removed

        # Verify A record still exists (should now use the remaining IP)
        remaining_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 1)

        # The record should now point to the remaining IP
        updated_record = remaining_a_records.first()
        self.assertEqual(updated_record.address, ip_address_2)

        # Remove the last IP address using custom method
        count = self.interface.remove_ip_addresses(ip_address_2)
        self.assertEqual(count, 1)  # Last IP should be removed

        # Now the A record should be deleted (template fails with no IPs)
        final_a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(final_a_records.count(), 0)

    @skip("Requires Nautobot M2M signal improvements - see nautobot/nautobot#7728")
    def test_interface_ip_addition_with_conflicting_through_defaults_fails(self):
        """Test that IP addition fails when through_defaults violate IPAddressToInterface mutual exclusion.

        NOTE: This test requires M2M signal validation to work.
        The signal handler needs to call full_clean() on IPAddressToInterface instances.
        See: https://github.com/nautobot/nautobot/issues/7728

        WARNING: This functionality is currently UNTESTED in the standard test environment.
        """
        # Create a VM and VMInterface
        cluster_type = ClusterType.objects.create(name="Test Cluster Type")
        cluster = Cluster.objects.create(name="test-cluster", cluster_type=cluster_type, location=self.location)

        vm_status = Status.objects.get_for_model(VirtualMachine).first()
        virtual_machine = VirtualMachine.objects.create(name="test-vm", cluster=cluster, status=vm_status)

        vm_interface_status = Status.objects.get_for_model(VMInterface).first()
        vm_interface = VMInterface.objects.create(
            virtual_machine=virtual_machine, name="eth0", status=vm_interface_status
        )

        # Test 1: Physical Interface with VMInterface in through_defaults (should fail)
        with self.assertRaises(ValidationError) as context:
            self.interface.ip_addresses.add(
                self.ip_address,
                through_defaults={
                    "vm_interface": vm_interface,  # ← Violates mutual exclusion
                    "is_primary": True,
                },
            )

        # Verify the error message relates to mutual exclusion
        self.assertIn("Cannot use a single instance to associate to both", str(context.exception))

        # Verify no IPAddressToInterface instance was created
        assignments = IPAddressToInterface.objects.filter(interface=self.interface, ip_address=self.ip_address)
        self.assertEqual(assignments.count(), 0)

        # Test 2: VMInterface with Interface in through_defaults (should fail)
        with self.assertRaises(ValidationError) as context:
            vm_interface.ip_addresses.add(
                self.ip_address,
                through_defaults={
                    "interface": self.interface,  # ← Violates mutual exclusion
                    "is_primary": True,
                },
            )

        # Verify the error message relates to mutual exclusion
        self.assertIn("Cannot use a single instance to associate to both", str(context.exception))

        # Verify no IPAddressToInterface instance was created
        assignments = IPAddressToInterface.objects.filter(vm_interface=vm_interface, ip_address=self.ip_address)
        self.assertEqual(assignments.count(), 0)

    def test_a_record_updated_when_interface_name_changed(self):
        """Test that A records are updated when interface name changes."""
        # Create DNS rule for this test
        self._create_dns_rule()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
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
        self.assertEqual(updated_records.first().address, self.ip_address)

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
        self._create_dns_rule()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
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
        self.assertEqual(updated_records.first().address, self.ip_address)

    def test_a_record_deleted_when_interface_deleted(self):
        """Test that A records are deleted when interface is deleted."""
        # Create DNS rule for this test
        self._create_dns_rule()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
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
        dns_rule = self._create_dns_rule()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
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

    def test_a_record_behavior_when_ip_address_deleted(self):
        """Test A record behavior when IP address itself is deleted.

        NOTE: This is an unusual scenario that may warrant special handling.
        When an IP address is deleted directly (not just removed from interface),
        the DNS record should be cleaned up, but this may require special signal
        handling since the IP→Interface relationship is severed.

        UPDATE: IP deletion validation IS possible using custom_validators.py
        in the plugin. We can prevent IP deletion when DNS records reference it.

        TODO: Should we implement IPAddress custom validator to block deletion when
        A/AAAA records reference the IP address, or enhance cleanup signals
        to handle the cascading deletion properly?
        """
        # Create DNS rule for this test
        self._create_dns_rule()

        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Delete IP address directly (not just remove from interface)
        self.ip_address.delete()

        # This scenario needs investigation:
        # 1. Does the A record still exist but point to deleted IP? (BAD)
        # 2. Does the A record get deleted automatically? (GOOD)
        # 3. Does this cause an integrity error? (PROBLEMATIC)

        # For now, document the current behavior:
        try:
            remaining_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
            if remaining_records.exists():
                record = remaining_records.first()
                # Check if record.address is now invalid
                self.fail(f"A record still exists after IP deletion: {record} - this may be problematic")
        except Exception as e:
            # Document any exceptions that occur
            self.fail(f"Exception during IP deletion scenario: {e} - needs investigation")

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
            value_template="{{ obj.primary_ip4.id }}",
        )

        # Create location-specific rule (should override global)
        DNSRule.objects.create(
            name="location-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc",
            value_template="{{ obj.primary_ip4.id }}",
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
        device.primary_ip4 = self.ip_address
        device.save()

        # Should create record from location rule, not global rule
        location_records = ARecord.objects.filter(name="test-location-device-loc")
        global_records = ARecord.objects.filter(name="test-location-device")

        self.assertEqual(location_records.count(), 1)
        self.assertEqual(global_records.count(), 0)

        # Verify the record is in the correct zone and has correct IP
        location_record = location_records.first()
        self.assertEqual(location_record.zone.name, "example.com")
        self.assertEqual(location_record.address, self.ip_address)

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
            value_template="{{ obj.primary_ip4.id }}",
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
        device.primary_ip4 = self.ip_address
        device.save()

        # Should create record from global rule
        global_records = ARecord.objects.filter(name="test-global-device")
        self.assertEqual(global_records.count(), 1)

        # Verify the record is in the correct zone and has correct IP
        global_record = global_records.first()
        self.assertEqual(global_record.zone.name, "example.com")
        self.assertEqual(global_record.address, self.ip_address)

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
            type="1000base-t",
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Add IP to interface (signal handlers should trigger DNS processing)
        # Interface should inherit location from device for rule processing
        interface.ip_addresses.add(self.ip_address)

        # Should create record using location rule (interface inherits device location)
        interface_records = ARecord.objects.filter(name="eth0.test-interface-device")
        self.assertEqual(interface_records.count(), 1)

        # Verify the record is in the correct zone and has correct IP
        interface_record = interface_records.first()
        self.assertEqual(interface_record.zone.name, "example.com")
        self.assertEqual(interface_record.address, self.ip_address)

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
            value_template="{{ obj.primary_ip4.id }}",
        )

        DNSRule.objects.create(
            name="location-2-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=location_2,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc2",
            value_template="{{ obj.primary_ip4.id }}",
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
        device.primary_ip4 = self.ip_address
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
        # Step 1: Create device and interface
        device = Device.objects.create(
            name="test-device",
            device_type=self.device_type,
            location=self.location,
            status=self.status,
            role=self.device_role,
        )

        interface = Interface.objects.create(
            device=device, name="eth0", type="1000base-t", status=Status.objects.get_for_model(Interface).first()
        )

        # Step 2: Create DNS rule FIRST (before IP assignment)
        interface_content_type = ContentType.objects.get_for_model(Interface)

        rule = DNSRule.objects.create(
            name="Multi-A Record Rule",
            content_type=interface_content_type,
            record_type="A",
            enabled=True,
            zone_template=self.dns_zone.name,
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() | ip_address }}",  # Multi-IP template
        )

        # Step 3: Create 3 IP addresses
        ip1 = IPAddress.objects.create(
            address="192.168.1.100/24", namespace=self.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )
        ip2 = IPAddress.objects.create(
            address="192.168.1.101/24", namespace=self.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )
        ip3 = IPAddress.objects.create(
            address="192.168.1.102/24", namespace=self.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )

        # Step 4: Assign all 3 IPs to interface (triggers M2M signal → automatic DNS processing)
        interface.ip_addresses.add(ip1, ip2, ip3)

        # Step 5: Verify 3 A records and 3 tracking records were created via signal
        a_records_after_add = ARecord.objects.filter(zone=self.dns_zone)
        rule_records_after_add = DNSRuleRecord.objects.filter(rule=rule)

        self.assertEqual(a_records_after_add.count(), 3, "Should create 3 A records initially")
        self.assertEqual(rule_records_after_add.count(), 3, "Should create 3 tracking records initially")

        # Verify A records point to correct IPs
        created_ips = {str(record.address_id) for record in a_records_after_add}
        expected_ips = {str(ip1.id), str(ip2.id), str(ip3.id)}
        self.assertEqual(created_ips, expected_ips, "A records should point to all 3 IPs")

        # Step 6: Remove one IP from interface (triggers M2M signal → automatic cleanup)
        interface.ip_addresses.remove(ip2)

        # Step 7: Verify cleanup was complete and correct
        a_records_after_removal = ARecord.objects.filter(zone=self.dns_zone)
        rule_records_after_removal = DNSRuleRecord.objects.filter(rule=rule)

        # Should have exactly 2 records after cleanup
        self.assertEqual(a_records_after_removal.count(), 2, "Should have exactly 2 A records after IP removal")
        self.assertEqual(
            rule_records_after_removal.count(), 2, "Should have exactly 2 tracking records after IP removal"
        )

        # Step 8: Verify remaining A records point to correct IPs (ip1 and ip3, not ip2)
        remaining_ips = {str(record.address_id) for record in a_records_after_removal}
        expected_remaining = {str(ip1.id), str(ip3.id)}
        self.assertEqual(remaining_ips, expected_remaining, "Remaining A records should point to remaining IPs only")

        # Step 9: Verify no orphaned records exist
        # Check for any A records in the zone that don't have tracking records
        tracked_dns_record_ids = {str(rr.dns_record_object_id) for rr in rule_records_after_removal}
        actual_dns_record_ids = {str(ar.id) for ar in a_records_after_removal}

        self.assertEqual(
            tracked_dns_record_ids, actual_dns_record_ids, "All A records should have corresponding tracking records"
        )

        # Step 10: Remove another IP to test down to 1 record (triggers M2M signal again)
        interface.ip_addresses.remove(ip3)

        # Step 11: Verify final state after second IP removal
        a_records_final = ARecord.objects.filter(zone=self.dns_zone)
        rule_records_final = DNSRuleRecord.objects.filter(rule=rule)

        self.assertEqual(a_records_final.count(), 1, "Should have 1 A record after second removal")
        self.assertEqual(rule_records_final.count(), 1, "Should have 1 tracking record after second removal")

        # Verify last record points to remaining IP
        final_ip = {str(record.address_id) for record in a_records_final}
        self.assertEqual(final_ip, {str(ip1.id)}, "Final A record should point to ip1")

    def test_a_records_deleted_when_interface_deleted_multiple_ips(self):
        """
        Test that all A records are deleted when interface with multiple IPs is deleted.

        This tests cascade deletion scenario where:
        - Interface has multiple IPs with multiple A records
        - Interface itself is deleted
        - All A records and tracking records should be cleaned up via signal handling
        """
        # Step 1: Create device and interface
        device = Device.objects.create(
            name="test-device",
            device_type=self.device_type,
            location=self.location,
            status=self.status,
            role=self.device_role,
        )

        interface = Interface.objects.create(
            device=device, name="eth0", type="1000base-t", status=Status.objects.get_for_model(Interface).first()
        )

        # Step 2: Create DNS rule for A records
        interface_content_type = ContentType.objects.get_for_model(Interface)

        rule = DNSRule.objects.create(
            name="Interface A Record Rule",
            content_type=interface_content_type,
            record_type="A",
            enabled=True,
            zone_template=self.dns_zone.name,
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() | ip_address }}",
        )

        # Step 3: Create multiple IP addresses and assign to interface
        ip1 = IPAddress.objects.create(
            address="192.168.1.100/24", namespace=self.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )
        ip2 = IPAddress.objects.create(
            address="192.168.1.101/24", namespace=self.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )
        ip3 = IPAddress.objects.create(
            address="192.168.1.102/24", namespace=self.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )

        interface.ip_addresses.add(ip1, ip2, ip3)

        # Step 4: Verify multiple A records were created
        a_records = ARecord.objects.filter(zone=self.dns_zone)
        rule_records = DNSRuleRecord.objects.filter(rule=rule)

        self.assertEqual(a_records.count(), 3, "Should create 3 A records for 3 IPs")
        self.assertEqual(rule_records.count(), 3, "Should create 3 tracking records")

        # Verify A records point to correct IPs
        created_ips = {str(record.address_id) for record in a_records}
        expected_ips = {str(ip1.id), str(ip2.id), str(ip3.id)}
        self.assertEqual(created_ips, expected_ips, "A records should point to all 3 IPs")

        # Step 5: Delete the interface (triggers cascade deletion)
        interface_id = interface.id
        interface.delete()

        # Step 6: Verify all A records were deleted via signal handling
        remaining_a_records = ARecord.objects.filter(zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0, "All A records should be deleted when interface is deleted")

        # Step 7: Verify all tracking records were cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(
            rule=rule,
            object_id=interface_id,  # Check for specific interface that was deleted
        )
        self.assertEqual(
            remaining_rule_records.count(), 0, "All tracking records should be cleaned up when interface is deleted"
        )


class RuleValidationTestCase(BaseRuleEngineTestCase):
    """Template validation, runtime errors, filter validation."""

    @classmethod
    def setUpTestData(cls):
        """Set up additional test data for validation tests."""
        super().setUpTestData()

        # Assign IP address to interface for validation tests
        cls.interface.ip_addresses.add(cls.ip_address)

    def test_render_template_error_string_detection(self):
        """Test whether our error string detection works."""
        # If render_jinja2 returns error strings instead of raising exceptions,
        # we need to detect them. Let's see if this actually happens.

        # First, let's see what error strings look like (if any)
        test_cases = [
            ("{{ obj.nonexistent }}", {"obj": {}}),
            ("{{ missing_var }}", {}),
            ("{{ obj.attr }}", {"obj": None}),
        ]

        for template, context in test_cases:
            try:
                result = render_jinja2(template, context)
                print(f"Template '{template}' with context {context} returned: {repr(result)}")

                # Test our current error detection
                if result and "{{ no such element:" in result:
                    print("  -> Our error detection WOULD catch this")
                else:
                    print("  -> Our error detection would NOT catch this")

            except Exception as e:
                print(f"Template '{template}' raised exception: {type(e).__name__}: {e}")

    def test_rule_validation_catches_nonexistent_filter(self):
        """Test that DNSRule.clean() catches non-existent filter errors during rule creation."""
        with self.assertRaises(ValidationError) as cm:
            rule = DNSRule(
                name="Bad Filter Rule",
                content_type=self.interface_content_type,
                record_type="A",
                enabled=True,
                zone_template="test.local",
                name_template="{{ obj.name }}",
                value_template="{{ obj.name | nonexistent_filter }}",  # This should be caught
            )
            rule.clean()  # Should raise ValidationError

        # Verify the error message mentions the filter problem
        error_dict = cm.exception.message_dict
        self.assertIn("value_template", error_dict)
        # error_dict values are lists, so join them and check
        error_messages = " ".join(error_dict["value_template"]).lower()
        self.assertIn("filter error", error_messages)

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
            value_template="{{ obj.ip_addresses.all() | ip_address }}",  # Valid
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
            record_type="CNAME",
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
            for field, messages in error_dict.items():
                # messages is a list, so join and check
                combined_message = " ".join(messages).lower()
                self.assertNotIn("runtime issues", combined_message)

    def test_rule_validation_critical_template_runtime_errors(self):
        """Test that A/AAAA value templates with runtime errors are blocked."""
        # A record value template that would fail at runtime - should be blocked
        rule = DNSRule(
            name="Critical Runtime Error Rule",
            content_type=self.interface_content_type,
            record_type="A",
            enabled=True,
            zone_template="test.local",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() | ip_address | nonexistent_filter }}",  # Runtime error
        )

        # This SHOULD raise ValidationError for A record value templates
        with self.assertRaises(ValidationError) as cm:
            rule.clean()

        # Should mention the filter error from validation
        error_dict = cm.exception.message_dict
        self.assertIn("value_template", error_dict)

        # error_dict values are lists, so join them and check
        error_messages = " ".join(error_dict["value_template"]).lower()
        self.assertIn("filter error", error_messages)
