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

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from jinja2 import TemplateError
from nautobot.apps.utils import render_jinja2
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import IPAddress, IPAddressToInterface, Namespace, Prefix, Service
from nautobot.tenancy.models import Tenant, TenantGroup
from nautobot.virtualization.models import Cluster, ClusterType, VirtualMachine, VMInterface

from nautobot_dns_models.exceptions import DNSTemplateEmptyError
from nautobot_dns_models.models import ARecord, DNSRule, DNSRuleRecord, DNSZone
from nautobot_dns_models.rules.engine import DNSRuleEngine

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

        cls.ipv6_prefix = Prefix.objects.create(
            network="2001:db8::",
            prefix_length=64,
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

        cls.ipv6_address = IPAddress.objects.create(
            address="2001:db8::1/64",
            status=cls.ip_status,
            namespace=cls.namespace,
            parent=cls.ipv6_prefix,
        )

        # Create Service test data
        cls.service_device_attached = Service.objects.create(
            device=cls.device, name="web-service", protocol="TCP", ports=[80, 443], description="Web service on device"
        )

        # Create VM infrastructure for VM-attached services
        cls.cluster_type = ClusterType.objects.create(name="Test Cluster Type")
        cls.cluster = Cluster.objects.create(name="Test Cluster", cluster_type=cls.cluster_type, location=cls.location)
        cls.vm_status = Status.objects.get_for_model(VirtualMachine).first()
        cls.vm = VirtualMachine.objects.create(cluster=cls.cluster, name="test-vm", status=cls.vm_status)

        cls.service_vm_attached = Service.objects.create(
            virtual_machine=cls.vm, name="api-service", protocol="TCP", ports=[8080], description="API service on VM"
        )

        # Additional IP for multi-IP testing
        cls.ip_address2 = IPAddress.objects.create(
            address="192.168.1.11/24", status=cls.ip_status, namespace=cls.namespace, parent=cls.prefix
        )

        # Create DNS zone
        cls.dns_zone = DNSZone.objects.create(name="example.com")

        # Content types for validation tests
        cls.device_content_type = ContentType.objects.get_for_model(Device)
        cls.interface_content_type = ContentType.objects.get_for_model(Interface)
        cls.service_content_type = ContentType.objects.get_for_model(Service)

        # Additional status objects that some tests expect
        cls.device_status = Status.objects.get_for_model(Device).first()
        cls.status = Status.objects.get_for_model(Device).first()  # Alias for compatibility

    def setUp(self):
        """Set up test data."""
        self.engine = DNSRuleEngine()

    def _calc_desired_record_data(self, rule: DNSRule, obj) -> list[dict]:
        """Helper for invoking the engine private API in tests."""
        # pylint: disable=protected-access
        return list(self.engine._calculate_desired_record_data(rule, obj))

    def _render_template(self, template_str: str, context: dict, field_name: str):
        """Wrapper around the engine's private _render_template helper."""
        # pylint: disable=protected-access
        return self.engine._render_template(template_str, context, field_name)

    def _get_object_location(self, obj):
        """Wrapper around engine object-location extraction."""
        # pylint: disable=protected-access
        return self.engine._get_object_location(obj)

    def _get_object_tenant(self, obj):
        """Wrapper around engine object-tenant extraction."""
        # pylint: disable=protected-access
        return self.engine._get_object_tenant(obj)

    def _get_applicable_rules(self, obj):
        """Wrapper around engine applicable rule resolution."""
        # pylint: disable=protected-access
        return self.engine._get_applicable_rules(obj)


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
        result = self._render_template("Hello {{ name }}", {"name": "World"}, "test_field")
        self.assertEqual(result, "Hello World")

    def test_render_template_method_with_undefined_variable(self):
        """Test _render_template method behavior with undefined variables."""
        # render_jinja2 returns empty string for undefined variables, which our method treats as an error
        with self.assertRaises(DNSTemplateEmptyError):
            self._render_template("{{ undefined_var }}", {}, "test_field")

    def test_render_template_method_with_syntax_error(self):
        """Test _render_template method behavior with syntax errors."""
        # render_jinja2 throws TemplateSyntaxError, which we catch and re-raise as TemplateError
        with self.assertRaises(TemplateError):
            self._render_template("{{ invalid }", {}, "test_field")

    def test_render_template_method_with_none_attribute(self):
        """Test _render_template method behavior when accessing attributes on None."""
        # This is the real-world case: when an IP is removed, obj.primary_ip4 becomes None
        # render_jinja2 returns empty string, which our method treats as an error
        with self.assertRaises(DNSTemplateEmptyError):
            self._render_template(
                "{{ obj.primary_ip4.id }}",
                {"obj": self.device},
                "test_field",  # self.device has no primary_ip4 set
            )

    def test_render_template_method_with_array_index_error(self):
        """Test _render_template method behavior with array index errors."""
        # render_jinja2 throws UndefinedError for array index errors, which we catch and re-raise
        # Create interface with no IP addresses to test array index error
        empty_interface = Interface.objects.create(
            name="empty-interface",
            device=self.device,
            type="1000base-t",
            status=Status.objects.get_for_model(Interface).first(),
        )
        with self.assertRaises(TemplateError):
            self._render_template("{{ obj.ip_addresses[0].id }}", {"obj": empty_interface}, "test_field")

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

    def test_what_does_no_such_element_actually_look_like(self):
        """Try to reproduce the '{{ no such element:' pattern we're checking for."""
        # Based on actual logs, this pattern occurs when accessing attributes on None
        # The pattern is: "{{ no such element: None['id'] }}"

        # Test case that should trigger the pattern (based on actual logs)
        # Create a device without primary_ip4 for testing
        device_no_ip = Device.objects.create(
            name="device-no-primary-ip",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=Status.objects.get_for_model(Device).first(),
            # primary_ip4 remains None by default
        )

        test_cases = [
            # Case from actual logs: obj.primary_ip4.id when primary_ip4 is None
            ("{{ obj.primary_ip4.id }}", {"obj": device_no_ip}),
            # Case: None object attribute access - use device with no primary_ip4
            ("{{ obj.primary_ip4.id }}", {"obj": device_no_ip}),
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
        # Use real device object without primary_ip4 set

        with self.assertRaises(DNSTemplateEmptyError) as context:
            self._render_template("{{ obj.primary_ip4.id }}", {"obj": self.device}, "test_field")

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
            type="1000base-t",
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Test the template that should trigger the DEBUG=True error pattern
        # The rule engine should catch the DebugUndefined error pattern and include it in the exception
        with self.assertRaises(DNSTemplateEmptyError) as context:
            self._render_template("{{ obj.role.id }}", {"obj": interface_no_role}, "test_field")

        # In DEBUG=True with DebugUndefined, the error message should contain the pattern
        self.assertIn("{{ no such element:", str(context.exception))

    def test_service_basic_template_rendering(self):
        """Test basic Service template rendering for both device and VM-attached services."""
        # Test device-attached service
        device_template = "{{ obj.name }}.{{ obj.device.name }}"
        result = render_jinja2(device_template, {"obj": self.service_device_attached})
        self.assertEqual(result, f"web-service.{self.device.name}")

        # Test VM-attached service
        vm_template = "{{ obj.name }}.{{ obj.virtual_machine.name }}"
        result = render_jinja2(vm_template, {"obj": self.service_vm_attached})
        self.assertEqual(result, f"api-service.{self.vm.name}")

    def test_service_parent_property_template(self):
        """Test Service.parent property works in templates."""
        parent_template = "{{ obj.parent.name }}"

        # Device-attached service
        result = render_jinja2(parent_template, {"obj": self.service_device_attached})
        self.assertEqual(result, self.device.name)

        # VM-attached service
        result = render_jinja2(parent_template, {"obj": self.service_vm_attached})
        self.assertEqual(result, self.vm.name)

    def test_service_location_template_rendering(self):
        """Test Service location access in templates."""
        # Device-attached service location
        device_location_template = "{{ obj.device.location.name | dns_normalize }}"
        result = render_jinja2(device_location_template, {"obj": self.service_device_attached})
        expected = self.location.name.lower().replace(" ", "-")
        self.assertEqual(result, expected)

        # VM-attached service location
        vm_location_template = "{{ obj.virtual_machine.cluster.location.name | dns_normalize }}"
        result = render_jinja2(vm_location_template, {"obj": self.service_vm_attached})
        self.assertEqual(result, expected)


class RuleResolutionTestCase(BaseRuleEngineTestCase):
    """Rule resolution, location/tenant extraction, precedence logic, fallback scenarios."""

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
            value_template="{{ obj.primary_ip4.id }}",
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

        rules = self._get_applicable_rules(self.device)

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

        rules = self._get_applicable_rules(self.device)

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

        rules = self._get_applicable_rules(device_with_both)

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

        rules = self._get_applicable_rules(device_with_both)

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
            value_template="{{ obj.ip_addresses.first() }}",
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
            address="192.168.1.110/24",
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
            value_template="{{ obj.ip_addresses.all() }}",  # Multi-IP template
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
            value_template="{{ obj.ip_addresses.all() }}",
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

    def test_service_dns_record_creation_end_to_end(self):
        """Test complete Service DNS record creation workflow."""
        # Create service DNS rule
        service_rule = DNSRule.objects.create(
            name="service-a-record-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name | dns_normalize }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Assign IP to service
        self.service_device_attached.ip_addresses.add(self.ip_address)

        # Verify DNS record creation
        a_records = ARecord.objects.filter(name="web-service", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)
        self.assertEqual(str(a_records.first().address_id), str(self.ip_address.id))

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
        self.service_device_attached.ip_addresses.add(self.ip_address, self.ip_address2)

        # Verify multiple DNS records
        a_records = ARecord.objects.filter(name="web-service", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 2)

        # Verify both IPs are represented
        record_ips = {str(record.address_id) for record in a_records}
        expected_ips = {str(self.ip_address.id), str(self.ip_address2.id)}
        self.assertEqual(record_ips, expected_ips)

    def test_service_ip_assignment_triggers_dns_update(self):
        """Test Service IP assignment triggers DNS record creation via M2M signals."""
        DNSRule.objects.create(
            name="service-signal-test-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Initially no DNS records
        self.assertEqual(ARecord.objects.filter(name="web-service").count(), 0)

        # Assign IP (should trigger M2M signal)
        self.service_device_attached.ip_addresses.add(self.ip_address)

        # Verify DNS record was created
        self.assertEqual(ARecord.objects.filter(name="web-service").count(), 1)

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
        self.service_device_attached.ip_addresses.add(self.ip_address)
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
        self.service_device_attached.ip_addresses.add(self.ip_address)
        first_record = ARecord.objects.filter(name="web-service").first()

        # Add second IP
        self.service_device_attached.ip_addresses.add(self.ip_address2)

        # Verify first record ID is preserved
        records_after = ARecord.objects.filter(name="web-service")
        self.assertEqual(records_after.count(), 2)

        record_for_ip1 = records_after.filter(address_id=self.ip_address.id).first()
        self.assertEqual(record_for_ip1.id, first_record.id)  # Should NOT be recreated

    def test_service_name_change_triggers_dns_update(self):
        """Test Service name change triggers DNS rule re-evaluation and updates DNS record name."""
        # Create service DNS rule that uses service name in the name template
        service_rule = DNSRule.objects.create(
            name="service-name-change-rule",
            content_type=self.service_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name | dns_normalize }}",  # Uses service name
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Assign IP to service and verify initial DNS record
        self.service_device_attached.ip_addresses.add(self.ip_address)

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
        self.assertEqual(str(new_record.address_id), str(self.ip_address.id), "Should point to same IP")

        # Verify tracking record is updated to point to the new record
        rule_records = DNSRuleRecord.objects.filter(rule=service_rule, object_id=self.service_device_attached.id)
        self.assertEqual(rule_records.count(), 1, "Should have one tracking record")
        self.assertEqual(rule_records.first().dns_record.id, new_record.id, "Tracking should point to new record")


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
            for _, messages in error_dict.items():
                # messages is a list, so join and check
                combined_message = " ".join(messages).lower()
                self.assertNotIn("runtime issues", combined_message)

    @override_settings(
        DEBUG=True,
        LOGGING=TEST_LOGGING_CONFIG,
    )
    def test_template_failure_preserves_existing_records(self):
        """Test that existing DNS records are not deleted when template rendering fails."""
        # Create a DNS rule for interface IPs with a template that will fail on interfaces without roles
        dns_rule = DNSRule.objects.create(
            name="interface-ip-with-role-rule",
            description="Create A records from interface IPs, requires role",
            content_type=ContentType.objects.get_for_model(Interface),
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
            status=Status.objects.get_for_model(Device).first(),
        )

        # Create interface role for successful interfaces
        interface_role = Role.objects.create(name="test-interface-role")
        interface_role.content_types.add(ContentType.objects.get_for_model(Interface))
        interface_status = Status.objects.get_for_model(Interface).first()
        ipaddress_status = Status.objects.get_for_model(IPAddress).first()

        # Create 3 interfaces
        interfaces_with_role = {}
        for i in range(1, 3):
            interface_name = f"eth{i}"
            interfaces_with_role[interface_name] = Interface.objects.create(
                name=interface_name,
                device=test_device,
                type="1000base-t",
                status=interface_status,
                role=interface_role,  # Has role - template should work
            )

        # No role - template should fail
        interface_no_role = Interface.objects.create(
            name=f"eth{i+1}",
            device=test_device,
            type="1000base-t",
            status=interface_status,
        )

        # Create IP addresses for interfaces 1 and 2 (successful cases)
        ip1 = IPAddress.objects.create(
            address="192.168.1.101/24",
            status=ipaddress_status,
            namespace=self.namespace,
            parent=self.prefix,
        )

        ip2 = IPAddress.objects.create(
            address="192.168.1.102/24",
            status=ipaddress_status,
            namespace=self.namespace,
            parent=self.prefix,
        )

        # Assign IPs to interfaces (this should trigger DNS record creation via M2M signals)
        interfaces_with_role["eth1"].ip_addresses.add(ip1)
        interfaces_with_role["eth2"].ip_addresses.add(ip2)

        # Verify DNS records were created for interfaces 1 and 2
        a_records_1 = ARecord.objects.filter(name=f"{interface_role.name}.eth1.{test_device.name}", zone=self.dns_zone)
        a_records_2 = ARecord.objects.filter(name=f"{interface_role.name}.eth2.{test_device.name}", zone=self.dns_zone)

        self.assertEqual(a_records_1.count(), 1, "DNS record should be created for interface 1")
        self.assertEqual(a_records_2.count(), 1, "DNS record should be created for interface 2")

        # Verify tracking records were created
        rule_records_1 = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interfaces_with_role["eth1"].id)
        rule_records_2 = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=interfaces_with_role["eth2"].id)

        self.assertEqual(rule_records_1.count(), 1, "Tracking record should exist for interface 1")
        self.assertEqual(rule_records_2.count(), 1, "Tracking record should exist for interface 2")

        # Now create IP for interface 3 (no role) - this should cause template failure
        ip3 = IPAddress.objects.create(
            address="192.168.1.103/24",
            status=ipaddress_status,
            namespace=self.namespace,
            parent=self.prefix,
        )

        # Assign IP to interface 3 - this should trigger template failure but not affect other records
        interface_no_role.ip_addresses.add(ip3)

        # Verify that existing DNS records for interfaces 1 and 2 are NOT deleted
        a_records_1_after = ARecord.objects.filter(
            name=f"{interface_role.name}.eth1.{test_device.name}", zone=self.dns_zone
        )
        a_records_2_after = ARecord.objects.filter(
            name=f"{interface_role.name}.eth2.{test_device.name}", zone=self.dns_zone
        )

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
            status=Status.objects.get_for_model(Device).first(),
        )

        test_interface = Interface.objects.create(
            name="eth0",
            device=test_device,
            type="1000base-t",
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Create first IP address and assign it
        ip1 = IPAddress.objects.create(
            address="192.168.1.110/24",
            status=Status.objects.get_for_model(IPAddress).first(),
            namespace=self.namespace,
            parent=self.prefix,
        )

        test_interface.ip_addresses.add(ip1)

        # Verify first DNS record was created
        a_records = ARecord.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1, "First DNS record should be created")

        first_record = a_records.first()
        first_record_id = first_record.id
        first_record_address_id = first_record.address_id

        # Verify it points to the first IP
        self.assertEqual(str(first_record_address_id), str(ip1.id), "First record should point to first IP")

        # Create second IP address and assign it
        ip2 = IPAddress.objects.create(
            address="192.168.1.120/24",
            status=Status.objects.get_for_model(IPAddress).first(),
            namespace=self.namespace,
            parent=self.prefix,
        )

        test_interface.ip_addresses.add(ip2)

        # Verify we now have TWO DNS records (one for each IP)
        a_records_after = ARecord.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
        self.assertEqual(a_records_after.count(), 2, "Should have two DNS records (one per IP)")

        # Get records by IP address to verify both exist
        record_for_ip1 = a_records_after.filter(address_id=ip1.id).first()
        record_for_ip2 = a_records_after.filter(address_id=ip2.id).first()

        self.assertIsNotNone(record_for_ip1, "Should have DNS record for first IP")
        self.assertIsNotNone(record_for_ip2, "Should have DNS record for second IP")

        # Critical test: The first record ID should be the same (not deleted and recreated)
        self.assertEqual(record_for_ip1.id, first_record_id, "First DNS record should NOT be deleted and recreated")

        # Verify tracking records exist for both IPs
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=test_interface.id)
        self.assertEqual(rule_records.count(), 2, "Should have two tracking records (one per IP)")

        # Remove the first IP to test that only its record is deleted
        test_interface.ip_addresses.remove(ip1)

        # Verify only the second IP's record remains
        a_records_final = ARecord.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
        self.assertEqual(a_records_final.count(), 1, "Should have one DNS record after removing first IP")

        final_record = a_records_final.first()
        self.assertEqual(str(final_record.address_id), str(ip2.id), "Remaining record should point to second IP")

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


class RuleEngineTemplateProxyIntegrationTest(BaseRuleEngineTestCase):
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
        self.interface.ip_addresses.set([self.ip_address, self.ip_address2])

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["address_id"], str(self.ip_address.pk))

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
        self.interface.ip_addresses.set([self.ip_address, self.ip_address2])

        results = self._calc_desired_record_data(rule, self.interface)
        # Expect two records: one for first() and one for last()
        self.assertEqual(len(results), 2)
        returned_ids = {record["address_id"] for record in results}
        expected_ids = {str(self.ip_address.pk), str(self.ip_address2.pk)}
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
        self.interface.ip_addresses.set([self.ip_address, self.ip_address2, self.ipv6_address])

        results = self._calc_desired_record_data(rule, self.interface)
        returned_ids = {record["address_id"] for record in results}
        expected_ids = {str(self.ip_address.pk), str(self.ip_address2.pk)}
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
        self.service_device_attached.ip_addresses.set([self.ip_address, self.ip_address2])

        results = self._calc_desired_record_data(rule, self.service_device_attached)
        returned_ids = {record["address_id"] for record in results}
        expected_ids = {str(self.ip_address.pk), str(self.ip_address2.pk)}
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
        self.interface.ip_addresses.set([self.ip_address])

        results = self._calc_desired_record_data(rule, self.interface)
        # Only the valid UUID should produce a record
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["address_id"], str(self.ip_address.pk))
