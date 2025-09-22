"""Test DNS Rule Engine."""

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
from nautobot.virtualization.models import Cluster, ClusterType, VirtualMachine, VMInterface

from nautobot_dns_models.models import ARecordModel, DNSRule, DNSRuleRecord, DNSZoneModel
from nautobot_dns_models.rule_engine import DNSRuleEngine
from nautobot_dns_models.exceptions import DNSTemplateEmptyError


class DNSRuleEngineTestCase(TestCase):
    """Test the DNSRuleEngine class."""

    def setUp(self):
        """Set up test data."""
        self.engine = DNSRuleEngine()
        self.content_type_device = ContentType.objects.get_for_model(Device)

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

        class TestObj:
            pass

        try:
            result = render_jinja2("{{ obj.missing_attr }}", {"obj": TestObj()})
            print(f"Object attribute error - Result: {repr(result)}")
            # This might not throw an exception - let's see what we get
        except Exception as e:
            print(f"Object attribute error - Exception type: {type(e).__name__}, Message: {e}")

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


class DNSRuleIntegrationTestCase(TestCase):
    """Integration tests for DNS rule processing with real objects and signals."""

    def setUp(self):
        """Set up test data for integration tests."""
        # Create required objects for testing
        self.location_type = LocationType.objects.create(name="Site")
        self.location_status = Status.objects.get_for_model(Location).first()
        self.location = Location.objects.create(
            name="Test Site", location_type=self.location_type, status=self.location_status
        )

        self.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        self.device_type = DeviceType.objects.create(manufacturer=self.manufacturer, model="Test Model")

        # Create or get a device role
        self.device_role, _ = Role.objects.get_or_create(name="Test Role", defaults={"color": "ff0000"})
        self.device_role.content_types.add(ContentType.objects.get_for_model(Device))

        self.device_status = Status.objects.get_for_model(Device).first()
        self.device = Device.objects.create(
            name="test-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )

        self.interface_status = Status.objects.get_for_model(Interface).first()
        self.interface = Interface.objects.create(
            device=self.device, name="eth0", type="1000base-t", status=self.interface_status
        )

        # Create namespace and prefix for IP addresses
        self.namespace = Namespace.objects.create(name="Test Namespace")
        self.prefix = Prefix.objects.create(
            network="192.168.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=Status.objects.get_for_model(Prefix).first(),
        )

        self.ip_status = Status.objects.get_for_model(IPAddress).first()
        # Create IP address within the namespace and associate with parent prefix
        self.ip_address = IPAddress.objects.create(
            address="192.168.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=self.prefix,
        )

        # Create DNS zone
        self.dns_zone = DNSZoneModel.objects.create(name="example.com")

        # Create DNS rule for Interface A records
        self.dns_rule = DNSRule.objects.create(
            name="interface-a-record-rule",
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
        # Verify no A records exist initially
        initial_a_records = ARecordModel.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Verify no DNSRuleRecord tracking exists initially
        initial_rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule).count()
        self.assertEqual(initial_rule_records, 0)

        # Add IP address to interface (this should trigger A record creation)
        self.interface.ip_addresses.add(self.ip_address)

        # Verify A record was created
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        self.assertEqual(a_record.address, self.ip_address)
        self.assertEqual(a_record.name, "eth0.test-device")
        self.assertEqual(a_record.zone, self.dns_zone)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        rule_record = rule_records.first()
        self.assertEqual(rule_record.source_object, self.interface)
        self.assertEqual(rule_record.dns_record, a_record)

    def test_interface_a_record_deleted_on_ip_removal_via_m2m_api(self):
        """Test that A records are deleted when IP is removed from interface via Django M2M API."""
        # Setup initial state with IP and A record
        self.interface.ip_addresses.add(self.ip_address)

        # Verify A record exists
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Verify DNSRuleRecord tracking exists
        rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        # Remove IP address from interface (this should trigger A record deletion)
        self.interface.ip_addresses.remove(self.ip_address)

        # Verify A record was deleted
        remaining_a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0)

        # Verify DNSRuleRecord tracking was also cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule, object_id=self.interface.id)
        self.assertEqual(remaining_rule_records.count(), 0)

    def test_interface_a_record_removal_with_multiple_ips(self):
        """Test A record behavior when interface has multiple IPs and one is removed."""
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
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        # The record should use whichever IP is returned by .first()
        self.assertIn(a_record.address, [self.ip_address, ip_address_2])

        # Remove one IP address
        self.interface.ip_addresses.remove(self.ip_address)

        # Verify A record still exists (should now use the remaining IP)
        remaining_a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 1)

        # The record should now point to the remaining IP
        updated_record = remaining_a_records.first()
        self.assertEqual(updated_record.address, ip_address_2)

        # Remove the last IP address
        self.interface.ip_addresses.remove(ip_address_2)

        # Now the A record should be deleted (template fails with no IPs)
        final_a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
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
        initial_a_records = ARecordModel.objects.filter(name__startswith="eth0.test-device").count()
        self.assertEqual(initial_a_records, 0)

        # Verify no DNSRuleRecord tracking exists initially
        initial_rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule).count()
        self.assertEqual(initial_rule_records, 0)

        # Add IP address to interface using custom method (this should trigger A record creation)
        count = self.interface.add_ip_addresses(self.ip_address)
        self.assertEqual(count, 1)  # Verify return value

        # Verify A record was created
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        self.assertEqual(a_record.address, self.ip_address)
        self.assertEqual(a_record.name, "eth0.test-device")
        self.assertEqual(a_record.zone, self.dns_zone)

        # Verify DNSRuleRecord tracking was created
        rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule, object_id=self.interface.id)
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
        # Setup initial state with IP and A record using M2M API
        self.interface.ip_addresses.add(self.ip_address)

        # Verify A record exists
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Verify DNSRuleRecord tracking exists
        rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)

        # Remove IP address from interface using custom method (this should trigger A record deletion)
        count = self.interface.remove_ip_addresses(self.ip_address)
        self.assertEqual(count, 1)  # Verify return value

        # Verify A record was deleted
        remaining_a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 0)

        # Verify DNSRuleRecord tracking was also cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(rule=self.dns_rule, object_id=self.interface.id)
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
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        a_record = a_records.first()
        # The record should use whichever IP is returned by .first()
        self.assertIn(a_record.address, [self.ip_address, ip_address_2])

        # Remove one IP address using custom method
        count = self.interface.remove_ip_addresses(self.ip_address)
        self.assertEqual(count, 1)  # One IP should be removed

        # Verify A record still exists (should now use the remaining IP)
        remaining_a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_a_records.count(), 1)

        # The record should now point to the remaining IP
        updated_record = remaining_a_records.first()
        self.assertEqual(updated_record.address, ip_address_2)

        # Remove the last IP address using custom method
        count = self.interface.remove_ip_addresses(ip_address_2)
        self.assertEqual(count, 1)  # Last IP should be removed

        # Now the A record should be deleted (template fails with no IPs)
        final_a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
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
        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Change interface name
        self.interface.name = "eth1"
        self.interface.save()

        # Current expectation: DNS rule engine should update existing record
        # Note: This tests the UPDATE path in the rule engine
        updated_records = ARecordModel.objects.filter(name="eth1.test-device", zone=self.dns_zone)
        old_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)

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
        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Change device name (should trigger cascade processing of interfaces)
        self.device.name = "new-device"
        self.device.save()

        # Enhanced v0.9 behavior: Device name changes trigger Interface rule updates
        updated_records = ARecordModel.objects.filter(name="eth0.new-device", zone=self.dns_zone)
        old_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)

        # Verify cascade processing worked:
        self.assertEqual(updated_records.count(), 1, "Device name change should trigger interface record update")
        self.assertEqual(old_records.count(), 0, "Old record should be gone after device name change")
        self.assertEqual(updated_records.first().address, self.ip_address)

    def test_a_record_deleted_when_interface_deleted(self):
        """Test that A records are deleted when interface is deleted."""
        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Delete interface
        interface_id = self.interface.id
        self.interface.delete()

        # Verify A record deleted
        remaining_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_records.count(), 0)

        # Verify tracking cleaned up
        remaining_rule_records = DNSRuleRecord.objects.filter(object_id=interface_id)
        self.assertEqual(remaining_rule_records.count(), 0)

    def test_a_record_deleted_when_device_deleted(self):
        """Test that A records are deleted when device is deleted."""
        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Delete device (cascades to interface)
        interface_id = self.interface.id  # Store before deletion
        self.device.delete()

        # Verify A record deleted
        remaining_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(remaining_records.count(), 0)

        # Verify tracking cleaned up
        # Note: After device deletion, interface is also deleted, so check by object_id
        remaining_rule_records = DNSRuleRecord.objects.filter(
            rule=self.dns_rule,
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
        # Setup: add IP and create record
        self.interface.ip_addresses.add(self.ip_address)
        a_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 1)

        # Delete IP address directly (not just remove from interface)
        self.ip_address.delete()

        # This scenario needs investigation:
        # 1. Does the A record still exist but point to deleted IP? (BAD)
        # 2. Does the A record get deleted automatically? (GOOD)
        # 3. Does this cause an integrity error? (PROBLEMATIC)

        # For now, document the current behavior:
        try:
            remaining_records = ARecordModel.objects.filter(name="eth0.test-device", zone=self.dns_zone)
            if remaining_records.exists():
                record = remaining_records.first()
                # Check if record.address is now invalid
                self.fail(f"A record still exists after IP deletion: {record} - this may be problematic")
        except Exception as e:
            # Document any exceptions that occur
            self.fail(f"Exception during IP deletion scenario: {e} - needs investigation")


class MultiRecordTestCase(TestCase):
    """Test DNS rule multi-record cleanup scenarios."""

    @classmethod
    def setUpTestData(cls):
        """Create test infrastructure."""
        # Create required objects for Device/Interface creation
        cls.status = Status.objects.get_for_model(Device).first()
        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_type = DeviceType.objects.create(manufacturer=cls.manufacturer, model="Test Device Type")
        cls.location_type = LocationType.objects.create(name="Test Location Type")
        cls.location = Location.objects.create(
            name="Test Location", location_type=cls.location_type, status=Status.objects.get_for_model(Location).first()
        )

        # Get or create a role for devices
        device_role = Role.objects.get_for_model(Device).first()
        if not device_role:
            device_role = Role.objects.create(name="Test Device Role")
            device_role.content_types.set([ContentType.objects.get_for_model(Device)])
        cls.role = device_role

        # Create namespace and prefix for IP addresses
        cls.namespace = Namespace.objects.create(name="Test Namespace")
        cls.prefix = Prefix.objects.create(
            prefix="192.168.1.0/24", namespace=cls.namespace, status=Status.objects.get_for_model(Prefix).first()
        )

        # Create DNS zone for testing
        cls.dns_zone = DNSZoneModel.objects.create(name="test.local")

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
            role=self.role,
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
        a_records_after_add = ARecordModel.objects.filter(zone=self.dns_zone)
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
        a_records_after_removal = ARecordModel.objects.filter(zone=self.dns_zone)
        rule_records_after_removal = DNSRuleRecord.objects.filter(rule=rule)

        # Should have exactly 2 records after cleanup
        self.assertEqual(a_records_after_removal.count(), 2, "Should have exactly 2 A records after IP removal")
        self.assertEqual(
            rule_records_after_removal.count(), 2, "Should have exactly 2 tracking records after IP removal"
        )

        # Step 8: erify remaining A records point to correct IPs (ip1 and ip3, not ip2)
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
        a_records_final = ARecordModel.objects.filter(zone=self.dns_zone)
        rule_records_final = DNSRuleRecord.objects.filter(rule=rule)

        self.assertEqual(a_records_final.count(), 1, "Should have 1 A record after second removal")
        self.assertEqual(rule_records_final.count(), 1, "Should have 1 tracking record after second removal")

        # Verify last record points to remaining IP
        final_ip = {str(record.address_id) for record in a_records_final}
        self.assertEqual(final_ip, {str(ip1.id)}, "Final A record should point to ip1")


class DNSRuleValidationTestCase(TestCase):
    """Test DNS rule template validation."""

    @classmethod
    def setUpTestData(cls):
        """Create test infrastructure."""
        cls.device_content_type = ContentType.objects.get_for_model(Device)
        cls.interface_content_type = ContentType.objects.get_for_model(Interface)
        
        # Create sample objects for template validation testing
        # (Our enhanced template validation needs real objects to test against)
        manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        device_type = DeviceType.objects.create(manufacturer=manufacturer, model="Test Device Type")
        location_type = LocationType.objects.create(name="Test Location Type")
        location = Location.objects.create(
            name="Test Location", 
            location_type=location_type,
            status=Status.objects.get_for_model(Location).first()
        )
        device_role = Role.objects.get_for_model(Device).first()
        if not device_role:
            device_role = Role.objects.create(name="Test Device Role")
            device_role.content_types.set([ContentType.objects.get_for_model(Device)])
        
        # Create sample Device and Interface for template testing. These are only needed because of the 
        # enhanced template validation done in DNSRule.clean().
        cls.device = Device.objects.create(
            name="test-device",
            device_type=device_type,
            location=location,
            status=Status.objects.get_for_model(Device).first(),
            role=device_role,
        )
        cls.interface = Interface.objects.create(
            device=cls.device,
            name="eth0",
            type="1000base-t",
            status=Status.objects.get_for_model(Interface).first()
        )
        
        # Create IP address infrastructure for template testing
        namespace = Namespace.objects.create(name="Test Namespace")
        prefix = Prefix.objects.create(
            prefix="192.168.1.0/24",
            namespace=namespace,
            status=Status.objects.get_for_model(Prefix).first()
        )
        ip_address = IPAddress.objects.create(
            address="192.168.1.100/24",
            namespace=namespace,
            status=Status.objects.get_for_model(IPAddress).first()
        )
        # Assign IP to interface so ip_address filter has data to work with
        cls.interface.ip_addresses.add(ip_address)

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
