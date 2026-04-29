"""
Categories:
- TemplateRenderingTestCase: Template rendering, syntax errors, undefined variables, error handling
- RuleResolutionTestCase: Rule resolution, location/tenant extraction, precedence logic, fallback scenarios
- IntegrationAndMultiRecordTestCase: End-to-end workflows, signal handlers, multi-IP scenarios, DNS record lifecycle
- RuleValidationTestCase: Template validation, runtime errors, filter validation
"""
# pylint: disable=too-many-lines

import itertools
import uuid
from unittest import skip
from unittest.mock import Mock, PropertyMock, patch

from constance.test import override_config
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from jinja2 import TemplateError, TemplateSyntaxError
from nautobot.apps.utils import render_jinja2
from nautobot.dcim.choices import InterfaceTypeChoices
from nautobot.dcim.models import Device, Interface, Location, LocationType
from nautobot.extras.models import CustomField, Status
from nautobot.ipam.models import IPAddress, IPAddressToInterface, Prefix, Service
from nautobot.tenancy.models import Tenant
from nautobot.virtualization.models import Cluster, ClusterType, VirtualMachine, VMInterface

from nautobot_dns_models.exceptions import DNSRuleRenderedValueLookupError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    DNSRule,
    DNSRuleFailureState,
    DNSRuleRecord,
    DNSView,
    DNSZone,
)
from nautobot_dns_models.normalization import normalize_dns_name
from nautobot_dns_models.rules.engine import DNSRuleEngine, ExecutionMode
from nautobot_dns_models.rules.engine.constants import (
    PHASE_UPDATE_RECONCILE,
    REASON_VIEW_NOT_FOUND,
    REASON_VIEW_TEMPLATE_EMPTY,
    REASON_ZONE_NOT_FOUND,
)
from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER
from nautobot_dns_models.rules.engine.resolver import RuleResolver
from nautobot_dns_models.rules.engine.strategies import UpdateResult
from nautobot_dns_models.rules.engine.template_proxies import wrap_for_template
from nautobot_dns_models.rules.engine.writer import RecordWriter
from nautobot_dns_models.tests.mixins.rule_engine import BaseRuleEngineMixin

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
        with self.assertRaises(DNSRuleTemplateRenderedEmptyError) as context:
            self._render_template("{{ undefined_var }}", {}, "test_field")

        self.assertEqual("Template test_field rendered empty: {{ undefined_var }}", str(context.exception))

    def test_render_template_method_with_syntax_error(self):
        """Test _render_template method behavior with syntax errors."""
        with self.assertRaises(TemplateSyntaxError):
            self._render_template("{{ invalid }", {}, "test_field")

    def test_render_template_method_with_none_attribute(self):
        """Test _render_template method behavior when accessing attributes on None."""
        # This is the real-world case: when an IP is removed, obj.primary_ip4 becomes None
        # render_jinja2 returns empty string, which our method treats as an error
        with self.assertRaises(DNSRuleTemplateRenderedEmptyError):
            self._render_template(
                "{{ obj.primary_ip4 }}",
                {"obj": wrap_for_template(self.device)},
                "test_field",  # self.device has no primary_ip4 set
            )

    def test_render_template_using_array_index(self):
        """Test _render_template method behavior with array index."""
        # Add IP address to interface before rendering
        self.interface.ip_addresses.add(self.ip_addresses[0])
        result = self._render_template(
            "{{ obj.ip_addresses.all()[0] }}", {"obj": wrap_for_template(self.interface)}, "test_field"
        )
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
        with self.assertRaises(DNSRuleTemplateRenderedEmptyError) as context:
            self._render_template(
                "{{ obj.ip_addresses.all()[0] }}", {"obj": wrap_for_template(empty_interface)}, "test_field"
            )

        # When accessing index 0 on empty queryset, Jinja2 renders empty string, triggering DNSRuleTemplateRenderedEmptyError
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
                with self.assertRaises(DNSRuleTemplateRenderedEmptyError):
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
        with self.assertRaises(DNSRuleTemplateRenderedEmptyError) as context:
            self._render_template("{{ obj.primary_ip4 }}", {"obj": wrap_for_template(self.device)}, "test_field")

        # The error should mention that template rendered empty
        error_message = str(context.exception)
        self.assertIn("Template test_field rendered empty", error_message)

    @override_settings(DEBUG=True)
    def test_render_template_method_catches_error_strings(self):
        """Test invalid DEBUG=True template output still raises DNSRuleTemplateRenderedEmptyError."""
        # Build a fresh engine inside the DEBUG override so its cached Jinja env
        # uses DebugUndefined behavior for invalid attribute access.
        test_engine = DNSRuleEngine()

        # Create interface with no role to test the real scenario
        interface_no_role = Interface.objects.create(
            name="test-interface-no-role",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

        # Test template with invalid attribute access under DEBUG=True.
        with self.assertRaises(DNSRuleTemplateRenderedEmptyError) as context:
            test_engine._materializer.render_template(
                "{{ obj.role.name }}",
                {"obj": wrap_for_template(interface_no_role)},
                "test_field",
            )

        self.assertIn("no such element", str(context.exception))
        self.assertIn("Template test_field rendered empty", str(context.exception))

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

    def test_zone_template_resolves_zone_from_custom_field(self):
        """Test zone_template can resolve DNS zone name from object custom field data."""
        custom_zone = "custom-zone.example.com"
        DNSZone.objects.create(name=custom_zone)

        custom_field = CustomField.objects.create(key="dns_zone_name", label="DNS Zone Name", type="text")
        custom_field.content_types.add(ContentType.objects.get_for_model(Interface))

        self.interface.cf["dns_zone_name"] = custom_zone
        self.interface.validated_save()
        self.interface.ip_addresses.set([self.ip_addresses[0]])

        rule = DNSRule.objects.create(
            name="interface-zone-from-cf",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="{{ obj.cf.dns_zone_name }}",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["zone"].name, custom_zone)

    def test_zone_template_resolves_zone_from_device_location(self):
        """Test zone_template can resolve DNS zone name from the source device location."""
        location_zone = f"{self.location.name.lower().replace(' ', '-')}.example.com"
        DNSZone.objects.create(name=location_zone)

        self.interface.ip_addresses.set([self.ip_addresses[0]])
        self.device.primary_ip4 = self.ip_addresses[0]
        self.device.save()

        rule = DNSRule.objects.create(
            name="device-zone-from-location",
            content_type=self.device_content_type,
            record_type="A",
            zone_template="{{ obj.location.name|lower|replace(' ', '-') }}.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        results = self._calc_desired_record_data(rule, self.device)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["zone"].name, location_zone)

    def test_zone_template_resolves_zone_from_device_location_custom_field(self):
        """Test zone_template can resolve DNS zone name from a custom field on device location."""
        location_zone = "location-cf-zone.example.com"
        DNSZone.objects.create(name=location_zone)

        custom_field = CustomField.objects.create(key="dns_zone_name", label="DNS Zone Name", type="text")
        custom_field.content_types.add(ContentType.objects.get_for_model(Location))

        self.location.cf["dns_zone_name"] = location_zone
        self.location.validated_save()

        self.interface.ip_addresses.set([self.ip_addresses[0]])
        self.device.primary_ip4 = self.ip_addresses[0]
        self.device.save()

        rule = DNSRule.objects.create(
            name="device-zone-from-location-cf",
            content_type=self.device_content_type,
            record_type="A",
            zone_template="{{ obj.location.cf.dns_zone_name }}",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        results = self._calc_desired_record_data(rule, self.device)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["zone"].name, location_zone)

    def test_zone_template_resolves_zone_using_view_template(self):
        """Test zone resolution uses view_template when zone names overlap."""
        internal_view = DNSView.objects.create(name="Internal")
        external_view = DNSView.objects.create(name="External")
        DNSZone.objects.create(name="example.com", dns_view=external_view)
        internal_zone = DNSZone.objects.create(name="example.com", dns_view=internal_view)

        self.interface.ip_addresses.set([self.ip_addresses[0]])

        rule = DNSRule.objects.create(
            name="interface-zone-from-view",
            content_type=self.interface_content_type,
            record_type="A",
            view_template="Internal",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["zone"], internal_zone)

    def test_zone_template_resolves_zone_using_case_sensitive_view_name(self):
        """Test view_template matching is case-sensitive when views differ only by case."""
        title_case_view = DNSView.objects.create(name="Internal")
        lower_case_view = DNSView.objects.create(name="internal")
        DNSZone.objects.create(name="case.example.com", dns_view=title_case_view)
        lower_case_zone = DNSZone.objects.create(name="case.example.com", dns_view=lower_case_view)

        self.interface.ip_addresses.set([self.ip_addresses[0]])

        rule = DNSRule.objects.create(
            name="interface-zone-case-sensitive-view",
            content_type=self.interface_content_type,
            record_type="A",
            view_template="internal",
            zone_template="case.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["zone"], lower_case_zone)

    def test_zone_template_uses_default_view_when_view_template_unset(self):
        """Test zone resolution falls back to Default DNS view when view_template is unset."""
        default_view = DNSView.objects.get(name="Default")
        external_view = DNSView.objects.create(name="External-Ambiguous")
        default_zone = DNSZone.objects.create(name="ambiguous.example.com", dns_view=default_view)
        DNSZone.objects.create(name="ambiguous.example.com", dns_view=external_view)

        self.interface.ip_addresses.set([self.ip_addresses[0]])

        rule = DNSRule.objects.create(
            name="interface-zone-ambiguous",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="ambiguous.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
        )
        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["zone"], default_zone)

    def test_zone_template_multiview_rule_creates_variations_per_view(self):
        """Test one rule with multi-value view_template creates record data per view."""
        internal_view = DNSView.objects.create(name="Internal-Multi")
        guest_view = DNSView.objects.create(name="Guest-Multi")
        internal_zone = DNSZone.objects.create(name="multi.example.com", dns_view=internal_view)
        guest_zone = DNSZone.objects.create(name="multi.example.com", dns_view=guest_view)

        self.interface.ip_addresses.set([self.ip_addresses[0]])
        rule = DNSRule.objects.create(
            name="interface-zone-multiview",
            content_type=self.interface_content_type,
            record_type="A",
            view_template="Internal-Multi, Guest-Multi",
            zone_template="multi.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 2)
        returned_zone_ids = {result["zone"].id for result in results}
        self.assertEqual(returned_zone_ids, {internal_zone.id, guest_zone.id})

    def test_view_template_resolves_views_per_ip_record(self):
        """Test that view_template can choose different views for each IP-derived record."""
        restricted_view = DNSView.objects.create(name="RestrictedView")
        internal_view = DNSView.objects.create(name="InternalView")
        restricted_zone = DNSZone.objects.create(name="split.example.com", dns_view=restricted_view)
        internal_zone = DNSZone.objects.create(name="split.example.com", dns_view=internal_view)

        restricted_prefix = Prefix.objects.create(
            network="172.1.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        internal_prefix = Prefix.objects.create(
            network="10.1.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )

        restricted_ip = IPAddress.objects.create(
            address="172.1.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=restricted_prefix,
        )
        internal_ip = IPAddress.objects.create(
            address="10.1.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=internal_prefix,
        )

        self.interface.ip_addresses.set([restricted_ip, internal_ip])
        rule = DNSRule.objects.create(
            name="interface-zone-per-record-view",
            content_type=self.interface_content_type,
            record_type="A",
            view_template=(
                "{{ 'RestrictedView' if ip.parent.id|string == '" f"{restricted_prefix.id}" "' else 'InternalView' }}"
            ),
            zone_template="split.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 2)
        expected_zone_by_address = {
            restricted_ip.id: restricted_zone.id,
            internal_ip.id: internal_zone.id,
        }
        returned_zone_by_address = {result["address_id"]: result["zone"].id for result in results}
        self.assertEqual(returned_zone_by_address, expected_zone_by_address)

    def test_view_template_per_record_error_skips_only_invalid_candidate(self):
        """Test per-record template failures skip only the failing candidate."""
        restricted_view = DNSView.objects.create(name="RestrictedView-Partial")
        restricted_zone = DNSZone.objects.create(name="partial.example.com", dns_view=restricted_view)

        restricted_prefix = Prefix.objects.create(
            network="172.2.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        unmatched_prefix = Prefix.objects.create(
            network="10.2.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )

        restricted_ip = IPAddress.objects.create(
            address="172.2.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=restricted_prefix,
        )
        unmatched_ip = IPAddress.objects.create(
            address="10.2.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=unmatched_prefix,
        )

        self.interface.ip_addresses.set([restricted_ip, unmatched_ip])
        rule = DNSRule.objects.create(
            name="interface-zone-per-record-partial",
            content_type=self.interface_content_type,
            record_type="A",
            view_template=(
                "{{ 'RestrictedView-Partial' if ip.parent.id|string == '" f"{restricted_prefix.id}" "' else '' }}"
            ),
            zone_template="partial.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["address_id"], restricted_ip.id)
        self.assertEqual(results[0]["zone"].id, restricted_zone.id)

    def test_view_template_unknown_view_skips_only_invalid_candidate(self):
        """Test per-candidate unknown view resolution skips only the failing candidate."""
        valid_view = DNSView.objects.create(name="KnownView-UnknownMix")
        valid_zone = DNSZone.objects.create(name="unknownmix.example.com", dns_view=valid_view)

        valid_prefix = Prefix.objects.create(
            network="172.4.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        invalid_prefix = Prefix.objects.create(
            network="10.4.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )

        valid_ip = IPAddress.objects.create(
            address="172.4.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=valid_prefix,
        )
        invalid_ip = IPAddress.objects.create(
            address="10.4.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=invalid_prefix,
        )

        self.interface.ip_addresses.set([valid_ip, invalid_ip])
        rule = DNSRule.objects.create(
            name="interface-zone-per-record-unknown-view",
            content_type=self.interface_content_type,
            record_type="A",
            view_template=(
                "{{ 'KnownView-UnknownMix' if ip.parent.id|string == '"
                f"{valid_prefix.id}"
                "' else 'MissingView-UnknownMix' }}"
            ),
            zone_template="unknownmix.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["address_id"], valid_ip.id)
        self.assertEqual(results[0]["zone"].id, valid_zone.id)

    def test_zone_template_missing_in_selected_view_skips_only_invalid_candidate(self):
        """Test per-candidate zone misses skip only the failing candidate."""
        valid_view = DNSView.objects.create(name="KnownView-ZoneMissMix")
        missing_zone_view = DNSView.objects.create(name="MissingZoneView-ZoneMissMix")
        valid_zone = DNSZone.objects.create(name="zonemissmix.example.com", dns_view=valid_view)
        DNSZone.objects.create(name="different.example.com", dns_view=missing_zone_view)

        valid_prefix = Prefix.objects.create(
            network="172.5.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        invalid_prefix = Prefix.objects.create(
            network="10.5.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )

        valid_ip = IPAddress.objects.create(
            address="172.5.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=valid_prefix,
        )
        invalid_ip = IPAddress.objects.create(
            address="10.5.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=invalid_prefix,
        )

        self.interface.ip_addresses.set([valid_ip, invalid_ip])
        rule = DNSRule.objects.create(
            name="interface-zone-per-record-zone-miss",
            content_type=self.interface_content_type,
            record_type="A",
            view_template=(
                "{{ 'KnownView-ZoneMissMix' if ip.parent.id|string == '"
                f"{valid_prefix.id}"
                "' else 'MissingZoneView-ZoneMissMix' }}"
            ),
            zone_template="zonemissmix.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["address_id"], valid_ip.id)
        self.assertEqual(results[0]["zone"].id, valid_zone.id)

    def test_view_template_rendered_empty_skips_candidate(self):
        """Test that a configured view_template rendering empty skips the candidate record."""
        restricted_view = DNSView.objects.create(name="RestrictedView-Empty")
        DNSZone.objects.create(name="empty.example.com", dns_view=restricted_view)

        restricted_prefix = Prefix.objects.create(
            network="172.3.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        restricted_ip = IPAddress.objects.create(
            address="172.3.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=restricted_prefix,
        )

        self.interface.ip_addresses.set([restricted_ip])
        rule = DNSRule.objects.create(
            name="interface-zone-empty-view-template",
            content_type=self.interface_content_type,
            record_type="A",
            view_template="{{ '' }}",
            zone_template="empty.example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        results = self._calc_desired_record_data(rule, self.interface)
        self.assertEqual(results, [])


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

    def test_get_object_tenant_device(self):
        """Test _get_object_tenant returns device.tenant for Device objects."""
        self.device.tenant = self.tenant
        self.device.validated_save()

        result = self._get_object_tenant(self.device)
        self.assertEqual(result, self.tenant)

    def test_get_object_location_interface(self):
        """Test _get_object_location returns interface.device.location for Interface objects."""
        # Test location extraction from interface
        result = self._get_object_location(self.interface)
        self.assertEqual(result, self.location)

    def test_get_object_tenant_interface(self):
        """Test _get_object_tenant returns interface.device.tenant for Interface objects."""
        self.device.tenant = self.tenant
        self.device.validated_save()

        result = self._get_object_tenant(self.interface)
        self.assertEqual(result, self.tenant)

    def test_get_object_location_device_module_interface(self):
        """Module-backed interface should resolve location from parent Device fallback."""
        module_interface = Interface(
            name="eth0-module-location",
            device=None,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        with (
            patch.object(Interface, "module", new_callable=PropertyMock) as module_property,
            patch.object(Interface, "parent", new_callable=PropertyMock) as parent_property,
        ):
            module_property.return_value = Mock(tenant=None)
            parent_property.return_value = self.device
            location = self._get_object_location(module_interface)

        self.assertEqual(location, self.location)

    def test_get_object_tenant_device_module_interface(self):
        """Module-backed interface should resolve tenant from parent Device when module tenant is absent."""
        self.device.tenant = self.tenant
        self.device.validated_save()

        module_interface = Interface(
            name="eth0-module-tenant",
            device=None,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        with (
            patch.object(Interface, "module", new_callable=PropertyMock) as module_property,
            patch.object(Interface, "parent", new_callable=PropertyMock) as parent_property,
        ):
            module_property.return_value = Mock(tenant=None)
            parent_property.return_value = self.device
            tenant = self._get_object_tenant(module_interface)

        self.assertEqual(tenant, self.tenant)

    def test_get_object_location_device_module_module_interface(self):
        """Nested module-backed interface should resolve location from parent Device fallback."""
        nested_module_interface = Interface(
            name="eth0-nested-module-location",
            device=None,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        with (
            patch.object(Interface, "module", new_callable=PropertyMock) as module_property,
            patch.object(Interface, "parent", new_callable=PropertyMock) as parent_property,
        ):
            module_property.return_value = Mock(tenant=None, parent_module=Mock(tenant=None, parent_module=None))
            parent_property.return_value = self.device
            location = self._get_object_location(nested_module_interface)

        self.assertEqual(location, self.location)

    def test_get_object_tenant_device_module_module_interface(self):
        """Nested module-backed interface should resolve tenant from parent Device when module tenant is absent."""
        self.device.tenant = self.tenant
        self.device.validated_save()

        nested_module_interface = Interface(
            name="eth0-nested-module-tenant",
            device=None,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        with (
            patch.object(Interface, "module", new_callable=PropertyMock) as module_property,
            patch.object(Interface, "parent", new_callable=PropertyMock) as parent_property,
        ):
            module_property.return_value = Mock(tenant=None, parent_module=Mock(tenant=None, parent_module=None))
            parent_property.return_value = self.device
            tenant = self._get_object_tenant(nested_module_interface)

        self.assertEqual(tenant, self.tenant)

    def test_get_object_tenant_interface_module_tenant_overrides_parent_device_tenant(self):
        """Module-backed interface should prefer module tenant over parent device tenant."""
        parent_tenant = Tenant.objects.create(name="Parent Device Tenant")
        module_tenant = Tenant.objects.create(name="Module Tenant")
        self.device.tenant = parent_tenant
        self.device.validated_save()

        child_interface = Interface(
            name="eth0-child-module-tenant",
            device=None,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        with (
            patch.object(Interface, "module", new_callable=PropertyMock) as module_property,
            patch.object(Interface, "parent", new_callable=PropertyMock) as parent_property,
        ):
            module_property.return_value = Mock(tenant=module_tenant)
            parent_property.return_value = self.device
            tenant = self._get_object_tenant(child_interface)

        self.assertEqual(tenant, module_tenant)

    def test_get_object_location_and_tenant_interface_parent_non_device_logs_warning(self):
        """Module-backed interface should log and return None when parent is not a Device."""
        child_interface = Interface(
            name="eth0-child-parent-non-device",
            device=None,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )

        with (
            patch("nautobot_dns_models.rules.engine.logging.logger.warning") as mock_warning,
            patch.object(Interface, "module", new_callable=PropertyMock) as module_property,
            patch.object(Interface, "parent", new_callable=PropertyMock) as parent_property,
        ):
            module_property.return_value = Mock(tenant=None)
            parent_property.return_value = Mock()
            location = self._get_object_location(child_interface)
            tenant = self._get_object_tenant(child_interface)

        self.assertIsNone(location)
        self.assertIsNone(tenant)
        self.assertEqual(mock_warning.call_count, 2)

        warning_messages = [str(call.args[0]) for call in mock_warning.call_args_list]
        self.assertTrue(all("dnsrule_interface_parent_fallback_failed" in message for message in warning_messages))

    def test_get_object_location_virtualmachine_uses_cluster_location(self):
        """Test _get_object_location returns VM location (resolved via cluster.location)."""
        cluster_type = ClusterType.objects.create(name="test-cluster-type")
        location_type = LocationType.objects.create(name="vm-test-location-type")
        location = Location.objects.create(
            name="vm-test-location",
            location_type=location_type,
            status=Status.objects.get_for_model(Location).first(),
        )
        cluster = Cluster.objects.create(
            name="test-cluster",
            cluster_type=cluster_type,
            location=location,
        )

        vm = VirtualMachine.objects.create(
            name="test-vm",
            cluster=cluster,
            status=Status.objects.get_for_model(VirtualMachine).first(),
        )

        result = self._get_object_location(vm)
        self.assertEqual(result, cluster.location)

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

        rules = self.engine.get_applicable_rules(self.device)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0], location_rule)

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

        rules = self.engine.get_applicable_rules(self.device)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0], global_rule)

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

        rules = self.engine.get_applicable_rules(vm)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0], global_rule)

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

        rules = self.engine.get_applicable_rules(self.device)

        # Should get location-specific A rule + global AAAA rule (2 rules total)
        self.assertEqual(len(rules), 2)

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

        rules = self.engine.get_applicable_rules(self.device)

        # Should only get location-specific rule
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, location_rule.name)

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

        rules = self.engine.get_applicable_rules(self.device)

        # Should get both location-specific rules
        self.assertEqual(len(rules), 2)
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

        rules = self.engine.get_applicable_rules(device_with_both)

        # Should get the most specific rule (location+tenant)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, location_tenant_rule.name)

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

        rules = self.engine.get_applicable_rules(device_with_both)

        # Should get both rules (different record types)
        self.assertEqual(len(rules), 2)
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

        rules = self.engine.get_applicable_rules(device_location_only)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, global_rule.name)

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

        rules = self.engine.get_applicable_rules(device_tenant_only)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, global_rule.name)

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

    def test_virtualmachine_tenant_extraction_with_cluster_fallback(self):
        """Test VirtualMachine tenant extraction falls back to cluster tenant."""
        cluster_with_tenant = Cluster.objects.create(
            name="Tenant Cluster VM", cluster_type=self.cluster_type, location=self.location, tenant=self.tenant
        )
        vm_no_tenant = VirtualMachine.objects.create(
            cluster=cluster_with_tenant,
            name="VM No Tenant Direct",
            status=self.vm_status,
        )

        tenant = self._get_object_tenant(vm_no_tenant)
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

    def test_interface_a_record_created_in_each_selected_dns_view(self):
        """Test that one interface rule can create records in multiple selected DNS views."""
        internal_view = DNSView.objects.create(name="Internal-Integration")
        internal_zone = DNSZone.objects.create(name="example.com", dns_view=internal_view)
        default_view = DNSView.objects.get(name="Default")

        dns_rule = self._create_dns_rule_for_interface_a_record(name="interface-a-record-multiview")
        dns_rule.view_template = f"{default_view.name}, {internal_view.name}"
        dns_rule.validated_save()

        self.interface.ip_addresses.add(self.ip_addresses[0])

        records = ARecord.objects.filter(
            name="eth0.test-device", address=self.ip_addresses[0], zone__name="example.com"
        )
        self.assertEqual(records.count(), 2)
        self.assertEqual({record.zone.id for record in records}, {self.dns_zone.id, internal_zone.id})

        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 2)

    def test_interface_a_record_created_in_case_distinct_views_with_same_name(self):
        """Test one rule can create records in two views whose names differ only by case."""
        upper_view = DNSView.objects.create(name="CaseView")
        lower_view = DNSView.objects.create(name="caseview")
        upper_zone = DNSZone.objects.create(name="example.com", dns_view=upper_view)
        lower_zone = DNSZone.objects.create(name="example.com", dns_view=lower_view)

        dns_rule = self._create_dns_rule_for_interface_a_record(name="interface-a-record-case-distinct-views")
        dns_rule.view_template = f"{upper_view.name}, {lower_view.name}"
        dns_rule.validated_save()

        self.interface.ip_addresses.add(self.ip_addresses[0])

        records = ARecord.objects.filter(
            name="eth0.test-device", address=self.ip_addresses[0], zone__name="example.com"
        )

        # One record should be created per selected view.
        self.assertEqual(records.count(), 2)

        # The two records should map exactly to the two case-distinct view zones.
        self.assertEqual({record.zone.id for record in records}, {upper_zone.id, lower_zone.id})

        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        # Tracking records should mirror created DNS records one-for-one.
        self.assertEqual(rule_records.count(), 2)

    def test_interface_a_record_defaults_to_default_view_when_view_template_unset(self):
        """Test empty view_template selection creates records only in the Default view."""
        guest_view = DNSView.objects.create(name="Guest-Integration")
        guest_zone = DNSZone.objects.create(name="example.com", dns_view=guest_view)

        self._create_dns_rule_for_interface_a_record(name="interface-a-record-default-view-fallback")
        self.interface.ip_addresses.add(self.ip_addresses[0])

        default_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        guest_records = ARecord.objects.filter(name="eth0.test-device", zone=guest_zone)
        self.assertEqual(default_records.count(), 1)
        self.assertEqual(guest_records.count(), 0)

    def test_all_candidates_fail_on_create_leaves_no_records_or_tracking(self):
        """Test create path with all candidates failing does not persist records or tracking rows."""
        dns_rule = DNSRule.objects.create(
            name="interface-all-candidates-fail-create",
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            view_template="MissingView-AllCandidatesFail",
            enabled=True,
        )

        self.interface.ip_addresses.add(self.ip_addresses[0], self.ip_addresses[1])

        a_records = ARecord.objects.filter(name="eth0.test-device", zone=self.dns_zone)
        self.assertEqual(a_records.count(), 0, "No A records should be created when all candidates fail")

        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 0, "No tracking rows should be created when all candidates fail")

    def test_update_reconcile_mixed_candidate_failures_cleanup_only_failed_candidates(self):
        """Test update reconciliation removes only failed candidates and preserves valid ones."""
        view_a = DNSView.objects.create(name="UpdateMixViewA")
        view_b = DNSView.objects.create(name="UpdateMixViewB")
        zone_name = "update-mix.example.com"
        zone_a = DNSZone.objects.create(name=zone_name, dns_view=view_a)
        zone_b = DNSZone.objects.create(name=zone_name, dns_view=view_b)

        prefix_a = Prefix.objects.create(
            network="172.6.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        prefix_b = Prefix.objects.create(
            network="10.6.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        prefix_c = Prefix.objects.create(
            network="192.0.6.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )

        ip_a = IPAddress.objects.create(
            address="172.6.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=prefix_a,
        )
        ip_b = IPAddress.objects.create(
            address="10.6.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=prefix_b,
        )
        ip_c = IPAddress.objects.create(
            address="192.0.6.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=prefix_c,
        )

        dns_rule = DNSRule.objects.create(
            name="interface-update-mixed-candidates",
            description="Reconcile mixed candidate failures",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template=zone_name,
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            view_template=(
                "{{ 'UpdateMixViewA' if ip.parent.id|string == '"
                f"{prefix_a.id}"
                "' else ('UpdateMixViewB' if ip.parent.id|string == '"
                f"{prefix_b.id}"
                "' else 'MissingView-UpdateMix') }}"
            ),
            enabled=True,
        )

        # Initial create path: two valid candidates -> two records.
        self.interface.ip_addresses.set([ip_a, ip_b])
        initial_records = ARecord.objects.filter(name="eth0.test-device", zone__name=zone_name)
        self.assertEqual(initial_records.count(), 2, "Expected two initial records for two valid candidates")
        self.assertEqual(
            {record.zone.id for record in initial_records},
            {zone_a.id, zone_b.id},
            "Expected one initial record in each selected valid view",
        )
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(),
            2,
            "Expected two tracking rows for initial valid candidates",
        )

        # Update path: replace one valid candidate with one that resolves to an unknown view.
        self.interface.ip_addresses.set([ip_a, ip_c])

        final_records = ARecord.objects.filter(name="eth0.test-device", zone__name=zone_name)
        self.assertEqual(final_records.count(), 1, "Only the valid candidate should remain after reconciliation")
        remaining_record = final_records.first()
        self.assertEqual(str(remaining_record.address_id), str(ip_a.id))
        self.assertEqual(remaining_record.zone.id, zone_a.id)

        final_rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(final_rule_records.count(), 1, "Tracking should be cleaned up for failed candidate")
        self.assertEqual(str(final_rule_records.first().dns_record_object_id), str(remaining_record.id))

    def test_update_reconcile_all_candidates_fail_cleans_up_existing_records_and_tracking(self):
        """Test update reconciliation deletes existing records when all candidates begin failing."""
        valid_view = DNSView.objects.create(name="AllFailUpdateKnownView")
        zone_name = "all-fail-update.example.com"
        valid_zone = DNSZone.objects.create(name=zone_name, dns_view=valid_view)

        valid_prefix_1 = Prefix.objects.create(
            network="172.7.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        valid_prefix_2 = Prefix.objects.create(
            network="10.7.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        invalid_prefix_1 = Prefix.objects.create(
            network="192.0.7.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        invalid_prefix_2 = Prefix.objects.create(
            network="198.51.7.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )

        valid_ip_1 = IPAddress.objects.create(
            address="172.7.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=valid_prefix_1,
        )
        valid_ip_2 = IPAddress.objects.create(
            address="10.7.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=valid_prefix_2,
        )
        invalid_ip_1 = IPAddress.objects.create(
            address="192.0.7.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=invalid_prefix_1,
        )
        invalid_ip_2 = IPAddress.objects.create(
            address="198.51.7.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=invalid_prefix_2,
        )

        dns_rule = DNSRule.objects.create(
            name="interface-update-all-candidates-fail",
            description="Reconcile all candidates failing",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template=zone_name,
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            view_template=(
                "{{ 'AllFailUpdateKnownView' if ip.parent.id|string in ['"
                f"{valid_prefix_1.id}"
                "', '"
                f"{valid_prefix_2.id}"
                "'] else 'MissingView-AllFailUpdate' }}"
            ),
            enabled=True,
        )

        # Initial create path: two valid candidates.
        self.interface.ip_addresses.set([valid_ip_1, valid_ip_2])
        self.assertEqual(
            ARecord.objects.filter(name="eth0.test-device", zone=valid_zone).count(),
            2,
            "Expected initial records to exist before all-fail update",
        )
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(),
            2,
            "Expected initial tracking rows to exist before all-fail update",
        )

        # Update path: all candidates now fail due to unknown views.
        self.interface.ip_addresses.set([invalid_ip_1, invalid_ip_2])

        self.assertEqual(
            ARecord.objects.filter(name="eth0.test-device", zone=valid_zone).count(),
            0,
            "All existing records should be removed when all candidates fail on update",
        )
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(),
            0,
            "All tracking rows should be removed when all candidates fail on update",
        )

    def test_update_reconcile_empty_view_render_cleans_up_failed_candidate_only(self):
        """Test update reconciliation with empty view render removes only the failing candidate."""
        view_a = DNSView.objects.create(name="UpdateEmptyViewA")
        view_b = DNSView.objects.create(name="UpdateEmptyViewB")
        zone_name = "update-empty.example.com"
        zone_a = DNSZone.objects.create(name=zone_name, dns_view=view_a)
        zone_b = DNSZone.objects.create(name=zone_name, dns_view=view_b)

        candidate_specs = {
            "survive": "172.8.1.0",
            "initial_valid": "10.8.1.0",
            "empty_on_update": "192.0.8.0",
        }
        candidates = {}
        for role, network in candidate_specs.items():
            prefix = Prefix.objects.create(
                network=network,
                prefix_length=24,
                namespace=self.namespace,
                status=self.prefix_status,
            )
            ip = IPAddress.objects.create(
                address=f"{network[:-1]}10/24",
                status=self.ip_status,
                namespace=self.namespace,
                parent=prefix,
            )
            candidates[role] = {"prefix": prefix, "ip": ip}

        dns_rule = DNSRule.objects.create(
            name="interface-update-empty-render-candidate",
            description="Reconcile empty render candidate failure",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template=zone_name,
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            view_template=(
                "{{ 'UpdateEmptyViewA' if ip.parent.id|string == '"
                f"{candidates['survive']['prefix'].id}"
                "' else ('UpdateEmptyViewB' if ip.parent.id|string == '"
                f"{candidates['initial_valid']['prefix'].id}"
                "' else '') }}"
            ),
            enabled=True,
        )

        # Initial create path: two valid candidates.
        self.interface.ip_addresses.set([candidates["survive"]["ip"], candidates["initial_valid"]["ip"]])
        self.assertEqual(ARecord.objects.filter(name="eth0.test-device", zone__name=zone_name).count(), 2)
        self.assertEqual(DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(), 2)

        # Update path: second candidate now renders empty view template and should be cleaned up.
        self.interface.ip_addresses.set([candidates["survive"]["ip"], candidates["empty_on_update"]["ip"]])

        final_records = ARecord.objects.filter(name="eth0.test-device", zone__name=zone_name)
        self.assertEqual(final_records.count(), 1, "Only non-empty candidate should remain after update")
        remaining = final_records.first()
        self.assertEqual(str(remaining.address_id), str(candidates["survive"]["ip"].id))
        self.assertEqual(remaining.zone.id, zone_a.id)

        final_tracking = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(final_tracking.count(), 1, "Tracking should be removed for empty-render candidate")
        self.assertEqual(str(final_tracking.first().dns_record_object_id), str(remaining.id))
        self.assertNotEqual(zone_b.id, remaining.zone.id)

    def test_update_reconcile_in_place_context_change_to_empty_view_cleans_up_records(self):
        """Test in-place context mutation to empty view render cleans up existing records."""
        in_place_view = DNSView.objects.create(name="InPlaceView-Empty")
        zone_name = "in-place-empty.example.com"
        zone = DNSZone.objects.create(name=zone_name, dns_view=in_place_view)

        view_selector_cf = CustomField.objects.create(
            key="dns_view_selector_in_place",
            label="DNS View Selector In Place",
            type="text",
        )
        view_selector_cf.content_types.add(ContentType.objects.get_for_model(Prefix))

        prefix = Prefix.objects.create(
            network="172.10.1.0",
            prefix_length=24,
            namespace=self.namespace,
            status=self.prefix_status,
        )
        prefix.cf["dns_view_selector_in_place"] = in_place_view.name
        prefix.validated_save()

        ip = IPAddress.objects.create(
            address="172.10.1.10/24",
            status=self.ip_status,
            namespace=self.namespace,
            parent=prefix,
        )

        dns_rule = DNSRule.objects.create(
            name="interface-in-place-empty-view-context",
            description="In-place context mutation for view_template",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template=zone_name,
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            view_template="{{ ip.parent.cf.dns_view_selector_in_place }}",
            enabled=True,
        )

        # Initial create path with same attached IP candidate.
        self.interface.ip_addresses.set([ip])
        self.assertEqual(ARecord.objects.filter(name="eth0.test-device", zone=zone).count(), 1)
        self.assertEqual(DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(), 1)

        # In-place mutation: same attached IP, but view context now renders empty.
        prefix.cf["dns_view_selector_in_place"] = ""
        prefix.validated_save()
        self.engine.process_object(self.interface, created=False)

        self.assertEqual(
            ARecord.objects.filter(name="eth0.test-device", zone=zone).count(),
            0,
            "Existing record should be removed after in-place context changes render view empty",
        )
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(),
            0,
            "Tracking rows should be removed after in-place context changes render view empty",
        )

    def test_update_reconcile_zone_miss_cleans_up_failed_candidate_only(self):
        """Test update reconciliation with zone miss removes only the failing candidate."""
        view_a = DNSView.objects.create(name="UpdateZoneMissViewA")
        view_b = DNSView.objects.create(name="UpdateZoneMissViewB")
        view_c = DNSView.objects.create(name="UpdateZoneMissViewC")
        zone_name = "update-zonemiss.example.com"
        zone_a = DNSZone.objects.create(name=zone_name, dns_view=view_a)
        zone_b = DNSZone.objects.create(name=zone_name, dns_view=view_b)

        # View C intentionally lacks zone_name so zone resolution fails when selected.
        DNSZone.objects.create(name="other-update-zonemiss.example.com", dns_view=view_c)

        candidate_specs = {
            "survive": "172.9.1.0",
            "initial_valid": "10.9.1.0",
            "zone_miss_on_update": "192.0.9.0",
        }
        candidates = {}
        for role, network in candidate_specs.items():
            prefix = Prefix.objects.create(
                network=network,
                prefix_length=24,
                namespace=self.namespace,
                status=self.prefix_status,
            )
            ip = IPAddress.objects.create(
                address=f"{network[:-1]}10/24",
                status=self.ip_status,
                namespace=self.namespace,
                parent=prefix,
            )
            candidates[role] = {"prefix": prefix, "ip": ip}

        dns_rule = DNSRule.objects.create(
            name="interface-update-zone-miss-candidate",
            description="Reconcile zone miss candidate failure",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template=zone_name,
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            view_template=(
                "{{ 'UpdateZoneMissViewA' if ip.parent.id|string == '"
                f"{candidates['survive']['prefix'].id}"
                "' else ('UpdateZoneMissViewB' if ip.parent.id|string in ['"
                f"{candidates['initial_valid']['prefix'].id}"
                "'] else 'UpdateZoneMissViewC') }}"
            ),
            enabled=True,
        )

        # Initial create path: two valid candidates.
        self.interface.ip_addresses.set([candidates["survive"]["ip"], candidates["initial_valid"]["ip"]])
        self.assertEqual(ARecord.objects.filter(name="eth0.test-device", zone__name=zone_name).count(), 2)
        self.assertEqual(
            {record.zone.id for record in ARecord.objects.filter(name="eth0.test-device", zone__name=zone_name)},
            {zone_a.id, zone_b.id},
        )
        self.assertEqual(DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(), 2)

        # Update path: candidate in view B now points to a view without the requested zone.
        self.interface.ip_addresses.set([candidates["survive"]["ip"], candidates["zone_miss_on_update"]["ip"]])

        final_records = ARecord.objects.filter(name="eth0.test-device", zone__name=zone_name)
        self.assertEqual(final_records.count(), 1, "Only non-zone-miss candidate should remain after update")
        remaining = final_records.first()
        self.assertEqual(str(remaining.address_id), str(candidates["survive"]["ip"].id))
        self.assertEqual(remaining.zone.id, zone_a.id)

        final_tracking = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(final_tracking.count(), 1, "Tracking should be removed for zone-miss candidate")
        self.assertEqual(str(final_tracking.first().dns_record_object_id), str(remaining.id))

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

        # Force tracking-row insert to fail to simulate uniqueness/constraint failure.
        with patch(
            "nautobot_dns_models.rules.engine.core.DNSRuleRecord.objects.create",
            side_effect=IntegrityError("dup"),
        ):
            # Assign IPv4 to trigger engine
            self.interface.ip_addresses.add(self.ip_addresses[0])

        # Assert DNSRecord was not persisted due to atomic rollback
        self.assertEqual(ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(), 0)

    def test_atomicity_tracking_uniqueness_collision_rolls_back(self):
        """
        Validate rollback on real tracking-row uniqueness collision.

        This pre-seeds a conflicting DNSRuleRecord tuple and then calls the singleton create
        path with a deterministic DNS record UUID to trigger a DB-enforced IntegrityError.
        """

        rule = DNSRule.objects.create(
            name="iface-a-atomicity-no-patch",
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        source_content_type = ContentType.objects.get_for_model(self.interface)
        dns_record_content_type = ContentType.objects.get_for_model(ARecord)
        expected_name = f"{self.interface.name}.{self.device.name}"
        forced_record_id = uuid.uuid4()

        DNSRuleRecord.objects.create(
            rule=rule,
            content_type=source_content_type,
            object_id=self.interface.id,
            dns_record_content_type=dns_record_content_type,
            dns_record_object_id=forced_record_id,
        )

        self.assertEqual(ARecord.objects.filter(id=forced_record_id).count(), 0)

        created_records = self.engine._writer._create_records_for_object(  # pylint: disable=protected-access
            rule=rule,
            source_obj=self.interface,
            record_data_list=[
                {
                    "id": forced_record_id,
                    "name": expected_name,
                    "zone": self.dns_zone,
                    "address": self.ip_addresses[0],
                }
            ],
        )

        # First, assert that no new ARecord was created in the database.
        self.assertEqual(created_records, [])
        self.assertEqual(ARecord.objects.filter(id=forced_record_id).count(), 0)

        # Next, verify that no duplicate tracking row was created.
        self.assertEqual(
            DNSRuleRecord.objects.filter(
                content_type=source_content_type,
                object_id=self.interface.id,
                dns_record_content_type=dns_record_content_type,
                dns_record_object_id=forced_record_id,
            ).count(),
            1,
        )

    def test_signal_path_does_not_use_bulk_create_fast(self):
        """Signal-driven processing should not use the pipeline batched-create queue."""

        self.interface.ip_addresses.set([])
        DNSRule.objects.create(
            name="singleton-signal-no-bulk-fast",
            description="Validate signal path skips fast bulk create",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        expected_name = f"{self.interface.name}.{self.device.name}"
        self.assertEqual(ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(), 0)

        with patch.object(
            type(self.engine._writer),  # pylint: disable=protected-access
            "_queue_records_for_batched_create",
            autospec=True,
            wraps=type(self.engine._writer)._queue_records_for_batched_create,  # pylint: disable=protected-access
        ) as batched_queue_mock:
            self.interface.ip_addresses.add(self.ip_addresses[0])

        batched_queue_mock.assert_not_called()
        self.assertEqual(ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(), 1)

    def test_update_tracked_dns_record_name_integrity_error_does_not_poison_outer_transaction(self):
        """Writer update should return FAILED and keep the outer transaction usable."""
        rule = self._create_dns_rule_for_interface_a_record(name="writer-update-savepoint-isolation")
        self.interface.ip_addresses.add(self.ip_addresses[0])

        tracking_record = DNSRuleRecord.objects.get(rule=rule, object_id=self.interface.id)
        original_record = tracking_record.dns_record
        desired_name = "conflicting.target.name"
        ARecord.objects.create(name=desired_name, zone=self.dns_zone, address=self.ip_addresses[0])

        with transaction.atomic():
            result = self.engine._writer._update_tracked_dns_record_name(  # pylint: disable=protected-access
                rule=rule,
                source_obj=self.interface,
                tracking_record=tracking_record,
                desired_record_data={
                    "name": desired_name,
                    "zone": self.dns_zone,
                    "address_id": self.ip_addresses[0].id,
                },
                phase="test_update_reconcile",
            )
            self.assertEqual(result, UpdateResult.FAILED)
            self.assertEqual(ARecord.objects.filter(pk=original_record.pk).count(), 1)

        original_record.refresh_from_db()
        self.assertEqual(original_record.name, f"{self.interface.name}.{self.device.name}")

    def test_process_objects_pipeline_continues_after_conflicting_object_update_failure(self):
        """Pipeline should continue processing later objects after one update conflict failure."""
        DNSRule.objects.create(
            name="pipeline-batch-continue-on-update-failure",
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}-{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

        interface_name = "uplink0"
        source_a_device_name = "batch-continue-source-a"
        source_b_device_name = "batch-continue-source-b"

        source_a_device = Device(
            name=source_a_device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        source_a_device.validated_save()
        source_a_interface = Interface(
            name=interface_name,
            device=source_a_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        source_a_interface.validated_save()

        tenant_b = Tenant.objects.create(name="Batch Continue Tenant B", tenant_group=self.tenant_group)
        source_b_device = Device(
            name=source_b_device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=tenant_b,
            role=self.device_role,
            status=self.device_status,
        )
        source_b_device.validated_save()
        source_b_interface = Interface(
            name=interface_name,
            device=source_b_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        source_b_interface.validated_save()

        success_device = Device(
            name="batch-continue-success-old",
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        success_device.validated_save()
        success_interface = Interface(
            name="uplink1",
            device=success_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        success_interface.validated_save()

        shared_ip = self.ip_addresses[0]
        success_ip = self.ip_addresses[1]
        source_a_interface.ip_addresses.add(shared_ip)
        source_b_interface.ip_addresses.add(shared_ip)
        success_interface.ip_addresses.add(success_ip)

        Device.objects.filter(pk=source_b_device.pk).update(name=source_a_device_name)
        Device.objects.filter(pk=success_device.pk).update(name="batch-continue-success-new")

        source_b_interface.refresh_from_db()
        success_interface.refresh_from_db()

        with transaction.atomic():
            summaries = self.engine.process_objects_pipeline([source_b_interface, success_interface])
            self.assertEqual(Interface.objects.filter(pk=success_interface.pk).count(), 1)

        self.assertEqual(len(summaries), 2)
        # First summary entry is the conflict object; failed update applies no DNS mutations.
        self.assertEqual(summaries[0].changed_record_count, 0)
        # Second summary entry is the control object; one rename update succeeds.
        self.assertEqual(summaries[1].changed_record_count, 1)
        self.assertEqual(summaries[1].dns_record_update_count, 1)

        self.assertEqual(
            ARecord.objects.filter(
                name=f"{interface_name}-{source_b_device_name}", zone=self.dns_zone, address=shared_ip
            ).count(),
            1,
        )
        self.assertEqual(
            ARecord.objects.filter(
                name=f"{interface_name}-{source_a_device_name}", zone=self.dns_zone, address=shared_ip
            ).count(),
            1,
        )
        self.assertEqual(
            ARecord.objects.filter(
                name="uplink1-batch-continue-success-new", zone=self.dns_zone, address=success_ip
            ).count(),
            1,
        )
        self.assertEqual(
            ARecord.objects.filter(
                name="uplink1-batch-continue-success-old", zone=self.dns_zone, address=success_ip
            ).count(),
            0,
        )

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

    def test_device_rename_with_shared_ip_name_convergence_breaks_atomic_transaction(self):
        """Device rename with shared IP and converging names should complete without transaction breakage."""
        rule = DNSRule(
            name="shared-ip-device-rename-collision",
            description="Create A records for interfaces",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}-{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )
        rule.validated_save()

        source_a_device_name = "rename-collision-source-a"
        source_b_device_name = "rename-collision-source-b"
        interface_name = "uplink0"
        tenant_a = self.tenant
        tenant_b = Tenant.objects.create(
            name="Rename Collision Tenant B",
            tenant_group=self.tenant_group,
        )

        existing_device = Device(
            name=source_a_device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=tenant_a,
            role=self.device_role,
            status=self.device_status,
        )
        existing_device.validated_save()
        existing_interface = Interface(
            name=interface_name,
            device=existing_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        existing_interface.validated_save()

        renamed_device = Device(
            name=source_b_device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=tenant_b,
            role=self.device_role,
            status=self.device_status,
        )
        renamed_device.validated_save()
        renamed_interface = Interface(
            name=interface_name,
            device=renamed_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        renamed_interface.validated_save()

        shared_ip = self.ip_addresses[0]
        existing_interface.ip_addresses.add(shared_ip)
        renamed_interface.ip_addresses.add(shared_ip)

        self.assertEqual(
            ARecord.objects.filter(
                name=f"{interface_name}-{source_a_device_name}", address=shared_ip, zone=self.dns_zone
            ).count(),
            1,
        )
        self.assertEqual(
            ARecord.objects.filter(
                name=f"{interface_name}-{source_b_device_name}", address=shared_ip, zone=self.dns_zone
            ).count(),
            1,
        )

        with transaction.atomic():
            renamed_device.name = source_a_device_name
            renamed_device.validated_save()
            self.assertEqual(
                ARecord.objects.filter(
                    name=f"{interface_name}-{source_a_device_name}",
                    address=shared_ip,
                    zone=self.dns_zone,
                ).count(),
                1,
            )

    def test_a_records_cascade_when_device_renamed_many_interfaces_one_ip_each(self):
        """Cascade path: parent rename updates one A record per interface when each has a single IP.

        At least two interfaces are required to exercise batched cascade handling (all interfaces
        processed in one pipeline batch rather than only the trivial single-object case). Eight
        interfaces is enough to catch off-by-one or partial-batch bugs while keeping the test fast.
        """
        num_interfaces = 8
        self._create_dns_rule_for_interface_a_record(name="cascade-many-ifaces-one-ip")

        interfaces = [self.interface]
        for i in range(1, num_interfaces):
            interfaces.append(
                Interface.objects.create(
                    name=f"eth{i}",
                    device=self.device,
                    type=InterfaceTypeChoices.TYPE_1GE_FIXED,
                    status=self.interface_status,
                )
            )

        extra_ips = []
        for octet in range(20, 20 + num_interfaces):
            extra_ips.append(
                IPAddress.objects.create(
                    address=f"192.168.1.{octet}/24",
                    status=self.ip_status,
                    namespace=self.namespace,
                    parent=self.prefix,
                )
            )

        for iface, ip in zip(interfaces, extra_ips):
            iface.ip_addresses.add(ip)

        old_device_name = self.device.name
        new_device_name = f"{old_device_name}-cascade-1ip"
        self.device.name = new_device_name
        self.device.save()

        for iface in interfaces:
            expected_name = f"{iface.name}.{new_device_name}"
            stale_name = f"{iface.name}.{old_device_name}"
            self.assertEqual(
                ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(),
                1,
                msg=f"expected one A record for {expected_name}",
            )
            self.assertEqual(ARecord.objects.filter(name=stale_name, zone=self.dns_zone).count(), 0)

    def test_a_records_cascade_when_device_renamed_multiple_ips_per_interface(self):
        """Cascade path: parent rename updates all A records when each interface has multiple IPv4s."""
        num_interfaces = 4
        num_ips_per_interface = 2
        device = Device.objects.create(
            name="multi-ip-cascade-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )
        DNSRule.objects.create(
            name="cascade-multi-ip-per-iface",
            description="Multi-A per interface for cascade test",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        interfaces = []
        for i in range(num_interfaces):
            interfaces.append(
                Interface.objects.create(
                    name=f"multi-eth{i}",
                    device=device,
                    type=InterfaceTypeChoices.TYPE_1GE_FIXED,
                    status=self.interface_status,
                )
            )

        total_ips = num_interfaces * num_ips_per_interface
        extra_ips = []
        for octet in range(40, 40 + total_ips):
            extra_ips.append(
                IPAddress.objects.create(
                    address=f"192.168.1.{octet}/24",
                    status=self.ip_status,
                    namespace=self.namespace,
                    parent=self.prefix,
                )
            )

        ip_iter = iter(extra_ips)
        for iface in interfaces:
            iface.ip_addresses.add(next(ip_iter), next(ip_iter))

        old_device_name = device.name
        new_device_name = f"{old_device_name}-renamed"
        device.name = new_device_name
        device.save()

        for iface in interfaces:
            expected_name = f"{iface.name}.{new_device_name}"
            stale_name = f"{iface.name}.{old_device_name}"
            self.assertEqual(
                ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(),
                num_ips_per_interface,
                msg=f"expected {num_ips_per_interface} A records for {expected_name}",
            )
            self.assertEqual(ARecord.objects.filter(name=stale_name, zone=self.dns_zone).count(), 0)

    def test_a_and_aaaa_records_cascade_when_device_renamed_mixed_ip_per_interface(self):
        """Cascade path: parent rename applies every applicable rule (A and AAAA) per interface.

        Each interface has both IPv4 and IPv6; one A rule and one AAAA rule share the same name
        template. After rename, both record types must reflect the new device name for every
        interface (validates multi-rule reconciliation on the batched cascade path).
        """
        num_interfaces = 3
        device = Device.objects.create(
            name="mixed-ip-cascade-device",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )
        DNSRule.objects.create(
            name="cascade-mixed-a",
            description="A records for mixed v4/v6 cascade test",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )
        DNSRule.objects.create(
            name="cascade-mixed-aaaa",
            description="AAAA records for mixed v4/v6 cascade test",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="AAAA",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
            enabled=True,
        )

        interfaces = []
        for i in range(num_interfaces):
            interfaces.append(
                Interface.objects.create(
                    name=f"mix-eth{i}",
                    device=device,
                    type=InterfaceTypeChoices.TYPE_1GE_FIXED,
                    status=self.interface_status,
                )
            )

        for i, iface in enumerate(interfaces):
            v4 = IPAddress.objects.create(
                address=f"192.168.1.{60 + i}/24",
                status=self.ip_status,
                namespace=self.namespace,
                parent=self.prefix,
            )
            v6 = IPAddress.objects.create(
                address=f"2001:db8::{60 + i}/64",
                status=self.ip_status,
                namespace=self.namespace,
                parent=self.ipv6_prefix,
            )
            iface.ip_addresses.add(v4, v6)

        old_device_name = device.name
        new_device_name = f"{old_device_name}-renamed"
        device.name = new_device_name
        device.save()

        for iface in interfaces:
            expected_name = f"{iface.name}.{new_device_name}"
            stale_name = f"{iface.name}.{old_device_name}"
            self.assertEqual(
                ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(),
                1,
                msg=f"expected one A record for {expected_name}",
            )
            self.assertEqual(
                AAAARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(),
                1,
                msg=f"expected one AAAA record for {expected_name}",
            )
            self.assertEqual(ARecord.objects.filter(name=stale_name, zone=self.dns_zone).count(), 0)
            self.assertEqual(AAAARecord.objects.filter(name=stale_name, zone=self.dns_zone).count(), 0)

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

    def test_device_location_change_updates_dns_records_for_new_scope(self):
        """Test that location changes update DNS records to match the new scope."""
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

        # Initial state: device in location 1
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

        # Initial assertions
        loc1_records = ARecord.objects.filter(name="test-moving-device-loc1")
        loc2_records = ARecord.objects.filter(name="test-moving-device-loc2")
        self.assertEqual(loc1_records.count(), 1)
        self.assertEqual(loc2_records.count(), 0)

        # Scope change: move to location 2
        device.location = location_2
        device.save()

        # Post-change assertions
        loc1_records = ARecord.objects.filter(name="test-moving-device-loc1")
        loc2_records = ARecord.objects.filter(name="test-moving-device-loc2")
        self.assertEqual(loc1_records.count(), 0)
        self.assertEqual(loc2_records.count(), 1)

    def test_device_location_change_uses_global_fallback_when_new_location_has_no_specific_rule(self):
        """Test that location changes use global fallback when the new location has no specific rule."""
        location_type_2 = LocationType.objects.create(name="Site Fallback 2")
        location_type_2.content_types.add(ContentType.objects.get_for_model(Device))
        location_2 = Location.objects.create(
            name="Test Site Fallback 2",
            location_type=location_type_2,
            status=Status.objects.get_for_model(Location).first(),
        )

        # Global fallback rule.
        DNSRule.objects.create(
            name="global-device-fallback-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Location-1-specific rule should override global while in location 1.
        DNSRule.objects.create(
            name="location-1-specific-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=self.location,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-loc1",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Initial state: device in location 1
        device = Device.objects.create(
            name="test-moving-device-fallback",
            device_type=self.device_type,
            location=self.location,
            role=self.device_role,
            status=self.device_status,
        )
        device.primary_ip4 = self.ip_addresses[0]
        device.save()

        # Initial assertions
        self.assertEqual(ARecord.objects.filter(name="test-moving-device-fallback-loc1").count(), 1)
        self.assertEqual(ARecord.objects.filter(name="test-moving-device-fallback-global").count(), 0)

        # Scope change: move to location 2 with no location-specific rule
        device.location = location_2
        device.save()

        # Post-change assertions
        self.assertEqual(ARecord.objects.filter(name="test-moving-device-fallback-loc1").count(), 0)
        self.assertEqual(ARecord.objects.filter(name="test-moving-device-fallback-global").count(), 1)

    def test_device_tenant_change_updates_dns_records_for_new_scope(self):
        """Test that tenant changes update DNS records to match the new scope."""
        tenant_2 = Tenant.objects.create(name="Test Tenant 2")

        DNSRule.objects.create(
            name="tenant-1-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            tenant=self.tenant,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-tenant1",
            value_template="{{ obj.primary_ip4 }}",
        )
        DNSRule.objects.create(
            name="tenant-2-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            tenant=tenant_2,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-tenant2",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Initial state: device in tenant 1
        device = Device.objects.create(
            name="test-moving-tenant-device",
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        device.primary_ip4 = self.ip_addresses[0]
        device.save()

        # Initial assertions
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-device-tenant1").count(), 1)
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-device-tenant2").count(), 0)

        # Scope change: move to tenant 2
        device.tenant = tenant_2
        device.save()

        # Post-change assertions
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-device-tenant1").count(), 0)
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-device-tenant2").count(), 1)

    def test_device_tenant_change_uses_global_fallback_when_new_tenant_has_no_specific_rule(self):
        """Test that tenant changes use global fallback when the new tenant has no specific rule."""
        tenant_2 = Tenant.objects.create(name="Test Tenant Fallback 2")

        DNSRule.objects.create(
            name="global-device-tenant-fallback-rule",
            content_type=ContentType.objects.get_for_model(Device),
            location=None,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-global",
            value_template="{{ obj.primary_ip4 }}",
        )
        DNSRule.objects.create(
            name="tenant-1-specific-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            tenant=self.tenant,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-tenant1",
            value_template="{{ obj.primary_ip4 }}",
        )

        # Initial state: device in tenant 1
        device = Device.objects.create(
            name="test-moving-tenant-fallback-device",
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        device.primary_ip4 = self.ip_addresses[0]
        device.save()

        # Initial assertions
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-fallback-device-tenant1").count(), 1)
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-fallback-device-global").count(), 0)

        # Scope change: move to tenant 2 with no tenant-specific rule
        device.tenant = tenant_2
        device.save()

        # Post-change assertions
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-fallback-device-tenant1").count(), 0)
        self.assertEqual(ARecord.objects.filter(name="test-moving-tenant-fallback-device-global").count(), 1)

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
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

        # Assign IP to service and verify initial DNS record
        self.service_device_attached.ip_addresses.add(self.ip_addresses[0])

        # Verify initial DNS record with original service name
        dns_records_before_update = ARecord.objects.filter(name="web-service", zone=self.dns_zone)
        self.assertEqual(dns_records_before_update.count(), 1, "Initial DNS record should be created")

        # Keep the initial record ID to verify update-in-place semantics
        initial_record_id = dns_records_before_update.first().id

        # Change the service name
        self.service_device_attached.name = "api-gateway"
        self.service_device_attached.save()

        # Verify no record remains under the original rendered name
        self.assertEqual(ARecord.objects.filter(name="web-service", zone=self.dns_zone).count(), 0)

        # Verify a DNS record exists under the updated name
        dns_records_after_update = ARecord.objects.filter(name="api-gateway", zone=self.dns_zone)
        self.assertEqual(dns_records_after_update.count(), 1, "Updated name should resolve to exactly one DNS record")
        new_record = dns_records_after_update.first()

        # Verify it points to the same IP
        self.assertEqual(new_record.address_id, self.ip_addresses[0].id, "Should point to same IP")

        # Verify update-in-place behavior: record identity is preserved across rename
        self.assertEqual(new_record.id, initial_record_id, "Record should be updated in place, not recreated")

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

    def test_reconciliation_preserves_untracked_manual_record_with_matching_name(self):
        """Reconciliation should not delete manual records that are not tracked by DNSRuleRecord."""
        dns_rule = self._create_dns_rule_for_interface_a_record(name="preserve-untracked-manual-record")
        expected_name = f"{self.interface.name}.{self.device.name}"

        manual_record = ARecord.objects.create(
            name=expected_name,
            zone=self.dns_zone,
            address=self.ip_addresses[1],
        )

        # Trigger managed record creation for the interface/rule pair.
        self.interface.ip_addresses.add(self.ip_addresses[0])

        created_records = ARecord.objects.filter(name=expected_name, zone=self.dns_zone)
        self.assertEqual(created_records.count(), 2)
        self.assertEqual(
            {record.address_id for record in created_records}, {self.ip_addresses[0].id, self.ip_addresses[1].id}
        )

        # Reconcile through update path and verify manual record remains untouched.
        self.engine.process_object(self.interface, created=False)

        records_after_reconcile = ARecord.objects.filter(name=expected_name, zone=self.dns_zone)
        self.assertEqual(records_after_reconcile.count(), 2)
        self.assertEqual(
            {record.address_id for record in records_after_reconcile},
            {self.ip_addresses[0].id, self.ip_addresses[1].id},
        )
        self.assertTrue(records_after_reconcile.filter(id=manual_record.id).exists())

        # Only the managed record should be tracked by DNSRuleRecord.
        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)
        self.assertEqual(rule_records.first().dns_record.address_id, self.ip_addresses[0].id)

        # Remove managed IP and reconcile again; tracked record should be removed, manual record preserved.
        self.interface.ip_addresses.remove(self.ip_addresses[0])
        self.engine.process_object(self.interface, created=False)

        final_records = ARecord.objects.filter(name=expected_name, zone=self.dns_zone)
        self.assertEqual(final_records.count(), 1)
        self.assertTrue(final_records.filter(id=manual_record.id).exists())
        self.assertEqual(final_records.first().address_id, self.ip_addresses[1].id)
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(),
            0,
        )

    def test_fast_pipeline_preserves_untracked_manual_record_with_matching_name(self):
        """Fast pipeline rename should preserve untracked manual same-name records."""
        dns_rule = self._create_dns_rule_for_interface_a_record(name="preserve-untracked-manual-record-fast")
        old_name = f"{self.interface.name}.{self.device.name}"

        # Ensure managed record exists first.
        self.interface.ip_addresses.add(self.ip_addresses[0])

        manual_record = ARecord.objects.create(
            name=old_name,
            zone=self.dns_zone,
            address=self.ip_addresses[1],
        )
        self.assertEqual(ARecord.objects.filter(name=old_name, zone=self.dns_zone).count(), 2)

        new_device_name = "test-device-fast-renamed"
        Device.objects.filter(pk=self.device.pk).update(name=new_device_name)
        self.interface.refresh_from_db()

        fast_engine = DNSRuleEngine(execution_mode=ExecutionMode.FAST)
        summaries = fast_engine.process_objects_pipeline([self.interface])
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].dns_record_update_count, 1)

        new_name = f"{self.interface.name}.{new_device_name}"
        self.assertEqual(
            ARecord.objects.filter(name=new_name, zone=self.dns_zone, address=self.ip_addresses[0]).count(),
            1,
        )
        self.assertEqual(
            ARecord.objects.filter(name=old_name, zone=self.dns_zone, address=self.ip_addresses[0]).count(),
            0,
        )
        self.assertTrue(ARecord.objects.filter(id=manual_record.id, name=old_name, zone=self.dns_zone).exists())

        rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id)
        self.assertEqual(rule_records.count(), 1)
        self.assertEqual(rule_records.first().dns_record.address_id, self.ip_addresses[0].id)
        self.assertEqual(rule_records.first().dns_record.name, new_name)

        # Remove managed IP and reconcile again through fast pipeline.
        self.interface.ip_addresses.remove(self.ip_addresses[0])
        self.interface.refresh_from_db()
        delete_summaries = fast_engine.process_objects_pipeline([self.interface])
        self.assertEqual(len(delete_summaries), 1)

        # Managed record should be cleaned up, manual same-name record should remain untouched.
        final_records = ARecord.objects.filter(name=old_name, zone=self.dns_zone)
        self.assertEqual(final_records.count(), 1)
        self.assertTrue(final_records.filter(id=manual_record.id).exists())
        self.assertEqual(final_records.first().address_id, self.ip_addresses[1].id)
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=dns_rule, object_id=self.interface.id).count(),
            0,
        )

    def test_fast_pipeline_update_fallback_partial_failure_records_state_and_keeps_success(self):
        """Fast fallback should isolate one failing rename and apply other updates."""
        dns_rule = self._create_dns_rule_for_interface_a_record(name="fast-fallback-partial-failure")
        self.interface.ip_addresses.add(self.ip_addresses[0])

        success_device = Device.objects.create(
            name="fast-fallback-success-old",
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        success_interface = Interface.objects.create(
            name="fast-fallback-success-intf",
            device=success_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        success_interface.ip_addresses.add(self.ip_addresses[1])
        self.engine.process_object(success_interface, created=True)

        old_failing_name = f"{self.interface.name}.{self.device.name}"
        old_success_name = f"{success_interface.name}.{success_device.name}"
        Device.objects.filter(pk=self.device.pk).update(name="fast-fallback-failing-new")
        Device.objects.filter(pk=success_device.pk).update(name="fast-fallback-success-new")
        self.interface.refresh_from_db()
        success_interface.refresh_from_db()

        failing_new_name = f"{self.interface.name}.fast-fallback-failing-new"
        success_new_name = f"{success_interface.name}.fast-fallback-success-new"
        ARecord.objects.create(name=failing_new_name, zone=self.dns_zone, address=self.ip_addresses[0])

        fast_engine = DNSRuleEngine(execution_mode=ExecutionMode.FAST)
        summaries = fast_engine.process_objects_pipeline([self.interface, success_interface])
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0].dns_record_update_count, 0)
        self.assertEqual(summaries[0].changed_record_count, 0)
        self.assertEqual(summaries[1].dns_record_update_count, 1)

        self.assertTrue(
            ARecord.objects.filter(name=old_failing_name, zone=self.dns_zone, address=self.ip_addresses[0]).exists()
        )
        self.assertTrue(
            ARecord.objects.filter(name=success_new_name, zone=self.dns_zone, address=self.ip_addresses[1]).exists()
        )
        self.assertFalse(
            ARecord.objects.filter(name=old_success_name, zone=self.dns_zone, address=self.ip_addresses[1]).exists()
        )

        failure_state = DNSRuleFailureState.objects.get(
            source_object_id=self.interface.id,
            rule=dns_rule,
            candidate_record_type="A",
            candidate_name=failing_new_name,
            candidate_zone_id=self.dns_zone.id,
            candidate_address_id=self.ip_addresses[0].id,
        )
        self.assertEqual(failure_state.attempt_count, 1)
        self.assertEqual(failure_state.consecutive_failures, 1)

    def test_fast_pipeline_update_fallback_all_failure_records_all_states(self):
        """Fast fallback should persist one failure-state row per failed singleton update."""
        dns_rule = self._create_dns_rule_for_interface_a_record(name="fast-fallback-all-failure")
        interfaces = []
        for index, address in enumerate(self.ip_addresses[:3], start=1):
            device = Device.objects.create(
                name=f"fast-fallback-all-failure-{index}-old",
                device_type=self.device_type,
                location=self.location,
                tenant=self.tenant,
                role=self.device_role,
                status=self.device_status,
            )
            interface = Interface.objects.create(
                name=f"fast-fallback-all-failure-intf-{index}",
                device=device,
                type=InterfaceTypeChoices.TYPE_1GE_FIXED,
                status=self.interface_status,
            )
            interface.ip_addresses.add(address)

            Device.objects.filter(pk=device.pk).update(name=f"fast-fallback-all-failure-{index}-new")
            interface.refresh_from_db()
            conflicting_name = f"{interface.name}.fast-fallback-all-failure-{index}-new"
            ARecord.objects.create(name=conflicting_name, zone=self.dns_zone, address=address)
            interfaces.append(interface)

        fast_engine = DNSRuleEngine(execution_mode=ExecutionMode.FAST)
        summaries = fast_engine.process_objects_pipeline(interfaces)

        self.assertEqual(len(summaries), 3)
        self.assertTrue(all(summary.changed_record_count == 0 for summary in summaries))
        self.assertEqual(DNSRuleFailureState.objects.filter(rule=dns_rule).count(), 3)
        self.assertTrue(all(state.attempt_count >= 1 for state in DNSRuleFailureState.objects.filter(rule=dns_rule)))

    def test_fast_pipeline_update_without_failure_keeps_fallback_counters_zero(self):
        """Fast pipeline metrics should show zero fallback counters when no rename fails."""
        self._create_dns_rule_for_interface_a_record(name="fast-fallback-no-failure")
        self.interface.ip_addresses.add(self.ip_addresses[0])
        Device.objects.filter(pk=self.device.pk).update(name="fast-fallback-no-failure-new")
        self.interface.refresh_from_db()

        fast_engine = DNSRuleEngine(execution_mode=ExecutionMode.FAST)
        summaries = fast_engine.process_objects_pipeline([self.interface])
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].dns_record_update_count, 1)
        metrics = fast_engine.get_pipeline_metrics()
        self.assertEqual(metrics["fallback_chunk_attempt_count_total"], 0)
        self.assertEqual(metrics["fallback_singleton_attempt_count_total"], 0)
        self.assertEqual(metrics["fallback_singleton_failure_count_total"], 0)
        self.assertEqual(metrics["update_failure_recorded_count_total"], 0)

    def test_fast_pipeline_update_failure_state_resolves_after_successful_retry(self):
        """Open failure state should move to resolved when later update succeeds."""
        dns_rule = self._create_dns_rule_for_interface_a_record(name="fast-fallback-recovery")
        self.interface.ip_addresses.add(self.ip_addresses[0])
        Device.objects.filter(pk=self.device.pk).update(name="fast-fallback-recovery-new")
        self.interface.refresh_from_db()
        failing_name = f"{self.interface.name}.fast-fallback-recovery-new"
        blocker = ARecord.objects.create(name=failing_name, zone=self.dns_zone, address=self.ip_addresses[0])

        fast_engine = DNSRuleEngine(execution_mode=ExecutionMode.FAST)
        first_run = fast_engine.process_objects_pipeline([self.interface])
        self.assertEqual(first_run[0].dns_record_update_count, 0)

        failure_state = DNSRuleFailureState.objects.get(
            source_object_id=self.interface.id,
            rule=dns_rule,
            candidate_record_type="A",
            candidate_name=failing_name,
            candidate_zone_id=self.dns_zone.id,
            candidate_address_id=self.ip_addresses[0].id,
        )
        self.assertEqual(failure_state.attempt_count, 1)

        blocker.delete()
        second_run = fast_engine.process_objects_pipeline([self.interface])
        self.assertEqual(second_run[0].dns_record_update_count, 1)
        self.assertFalse(DNSRuleFailureState.objects.filter(pk=failure_state.pk).exists())

    def test_create_failure_state_resolves_after_successful_retry(self):
        """Create-path failure state resolves when same candidate later succeeds."""
        tenant_b = Tenant.objects.create(name="create-failure-tenant-b")
        device_name = "create-failure-device"
        interface_name = "create-failure-intf"
        shared_ip = self.ip_addresses[0]

        source_a_device = Device.objects.create(
            name=device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        source_b_device = Device.objects.create(
            name=device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=tenant_b,
            role=self.device_role,
            status=self.device_status,
        )
        source_a_interface = Interface.objects.create(
            name=interface_name,
            device=source_a_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        source_b_interface = Interface.objects.create(
            name=interface_name,
            device=source_b_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        source_a_interface.ip_addresses.add(shared_ip)
        source_b_interface.ip_addresses.add(shared_ip)

        dns_rule = self._create_dns_rule_for_interface_a_record(name="create-failure-recovery")
        candidate_name = f"{interface_name}.{device_name}"
        standard_engine = DNSRuleEngine()
        first_run = standard_engine.process_objects_pipeline([source_a_interface, source_b_interface])
        self.assertEqual(len(first_run), 2)
        self.assertEqual(DNSRuleFailureState.objects.filter(rule=dns_rule).count(), 1)
        self.assertEqual(DNSRuleRecord.objects.filter(rule=dns_rule).count(), 1)

        failure_state = DNSRuleFailureState.objects.get(
            rule=dns_rule,
            candidate_record_type="A",
            candidate_name=candidate_name,
            candidate_zone_id=self.dns_zone.id,
            candidate_address_id=shared_ip.id,
        )
        self.assertEqual(failure_state.attempt_count, 1)

        failed_source_id = failure_state.source_object_id
        if failed_source_id == source_a_interface.id:
            winner_interface = source_b_interface
            failed_interface = source_a_interface
        else:
            winner_interface = source_a_interface
            failed_interface = source_b_interface

        winner_interface.delete()
        failed_interface.refresh_from_db()
        second_run = standard_engine.process_object(failed_interface, created=False)
        self.assertEqual(second_run.dns_record_create_count, 1)
        self.assertFalse(DNSRuleFailureState.objects.filter(pk=failure_state.pk).exists())

    def test_fast_pipeline_create_fallback_partial_failure_records_and_resolves_state(self):
        """Fast batched-create fallback isolates conflict and resolves on retry."""
        tenant_b = Tenant.objects.create(name="fast-create-failure-tenant-b")
        device_name = "fast-create-failure-device"
        interface_name = "fast-create-failure-intf"
        shared_ip = self.ip_addresses[0]

        source_a_device = Device.objects.create(
            name=device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=self.tenant,
            role=self.device_role,
            status=self.device_status,
        )
        source_b_device = Device.objects.create(
            name=device_name,
            device_type=self.device_type,
            location=self.location,
            tenant=tenant_b,
            role=self.device_role,
            status=self.device_status,
        )
        source_a_interface = Interface.objects.create(
            name=interface_name,
            device=source_a_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        source_b_interface = Interface.objects.create(
            name=interface_name,
            device=source_b_device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=self.interface_status,
        )
        source_a_interface.ip_addresses.add(shared_ip)
        source_b_interface.ip_addresses.add(shared_ip)

        dns_rule = self._create_dns_rule_for_interface_a_record(name="fast-create-fallback-partial")
        candidate_name = f"{interface_name}.{device_name}"
        fast_engine = DNSRuleEngine(execution_mode=ExecutionMode.FAST)
        first_run = fast_engine.process_objects_pipeline([source_a_interface, source_b_interface])
        self.assertEqual(len(first_run), 2)
        self.assertEqual(DNSRuleFailureState.objects.filter(rule=dns_rule).count(), 1)
        self.assertEqual(DNSRuleRecord.objects.filter(rule=dns_rule).count(), 1)

        failure_state = DNSRuleFailureState.objects.get(
            rule=dns_rule,
            candidate_record_type="A",
            candidate_name=candidate_name,
            candidate_zone_id=self.dns_zone.id,
            candidate_address_id=shared_ip.id,
        )
        self.assertEqual(failure_state.attempt_count, 1)

        failed_source_id = failure_state.source_object_id
        if failed_source_id == source_a_interface.id:
            winner_interface = source_b_interface
            failed_interface = source_a_interface
        else:
            winner_interface = source_a_interface
            failed_interface = source_b_interface

        winner_interface.delete()
        failed_interface.refresh_from_db()
        second_run = fast_engine.process_objects_pipeline([failed_interface])
        self.assertEqual(len(second_run), 1)
        self.assertEqual(DNSRuleRecord.objects.filter(rule=dns_rule, object_id=failed_interface.id).count(), 1)
        self.assertFalse(DNSRuleFailureState.objects.filter(pk=failure_state.pk).exists())

    def test_multiple_ips_preserve_existing_records(self):
        """Test reconciliation preserves existing records when adding a second matching IP."""
        cases = [
            {
                "record_type": "A",
                "ip_pool": self.ip_addresses,
                "record_model": ARecord,
            },
            {
                "record_type": "AAAA",
                "ip_pool": self.ipv6_addresses,
                "record_model": AAAARecord,
            },
        ]

        for case in cases:
            record_type = case["record_type"]
            ip_pool = case["ip_pool"]
            record_model = case["record_model"]

            with self.subTest(record_type=record_type):
                dns_rule = DNSRule.objects.create(
                    name=f"interface-multi-ip-{record_type.lower()}-rule",
                    description=f"Create {record_type} records from interface IPs",
                    content_type=ContentType.objects.get_for_model(Interface),
                    record_type=record_type,
                    zone_template="example.com",
                    name_template="{{ obj.name }}.{{ obj.device.name }}",
                    value_template="{{ obj.ip_addresses.all() }}",
                    enabled=True,
                )

                test_device = Device.objects.create(
                    name=f"multi-ip-{record_type.lower()}-device",
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

                test_interface.ip_addresses.add(ip_pool[0])

                records = record_model.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
                self.assertEqual(records.count(), 1, f"First {record_type} record should be created")
                first_record = records.first()
                first_record_id = first_record.id

                test_interface.ip_addresses.add(ip_pool[1])

                records_after = record_model.objects.filter(name=f"eth0.{test_device.name}", zone=self.dns_zone)
                self.assertEqual(records_after.count(), 2, f"Should have two {record_type} records (one per IP)")

                record_for_ip1 = records_after.filter(address_id=ip_pool[0].id).first()
                record_for_ip2 = records_after.filter(address_id=ip_pool[1].id).first()
                self.assertIsNotNone(record_for_ip1, f"Should have {record_type} record for first IP")
                self.assertIsNotNone(record_for_ip2, f"Should have {record_type} record for second IP")

                self.assertEqual(
                    record_for_ip1.id,
                    first_record_id,
                    f"First {record_type} record should NOT be deleted and recreated",
                )

                rule_records = DNSRuleRecord.objects.filter(rule=dns_rule, object_id=test_interface.id)
                self.assertEqual(rule_records.count(), 2, f"Should have two tracking records for {record_type}")


class LoggingObservabilityTestCase(BaseRuleEngineMixin, TestCase):
    """Structured logging field coverage for DNS rule engine helpers."""

    def setUp(self):
        """Set test-local logger handle for helper assertions and patches."""
        super().setUp()
        self._engine_logger = DEFAULT_ENGINE_LOGGER

    def test_build_log_extra_exposes_candidate_and_error_fields(self):
        """Ensure structured extra contains documented candidate/error fields."""
        rule = DNSRule.objects.create(
            name="logging-extra-fields-rule",
            description="Structured logging field coverage",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )
        record_data = {"address_id": str(self.ip_addresses[0].pk), "name": "eth0.test-device", "zone": self.dns_zone}
        exc = ValidationError("test logging error")

        # pylint: disable=protected-access
        extra = self._engine_logger._build_log_extra(  # pylint: disable=protected-access
            rule=rule,
            source_obj=self.interface,
            reason_code="TEST_REASON",
            phase="create",
            exc=exc,
            record_data=record_data,
            cleanup=False,
        )

        expected_keys = {
            "event",
            "reason_code",
            "phase",
            "rule_id",
            "rule_name",
            "record_type",
            "source_ct",
            "source_id",
            "source_repr",
            "exception_type",
            "error",
            "cleanup",
            "candidate_address_id",
            "candidate_name",
            "candidate_zone_id",
        }
        self.assertEqual(set(extra.keys()), expected_keys)

    def test_infer_reason_code_template_error_maps_to_candidate_template_error(self):
        """TemplateError should map to CANDIDATE_TEMPLATE_ERROR reason code."""
        # pylint: disable=protected-access
        reason = self._engine_logger._infer_reason_code(TemplateError("template failure"), "DEFAULT")  # pylint: disable=protected-access
        self.assertEqual(reason, "CANDIDATE_TEMPLATE_ERROR")

    def test_infer_reason_code_view_and_zone_validation_mappings(self):
        """ValidationError message_dict values should map to stable reason codes."""
        # pylint: disable=protected-access
        view_empty_reason = self._engine_logger._infer_reason_code(  # pylint: disable=protected-access
            ValidationError({"view_template": "view_template rendered no DNS view names."}), "DEFAULT"
        )
        view_missing_reason = self._engine_logger._infer_reason_code(  # pylint: disable=protected-access
            ValidationError({"view_template": "DNS view(s) not found from view_template: MissingView"}), "DEFAULT"
        )
        zone_missing_reason = self._engine_logger._infer_reason_code(  # pylint: disable=protected-access
            ValidationError({"zone_template": "Zone 'x' does not exist in selected DNS view(s): Default"}), "DEFAULT"
        )

        self.assertEqual(view_empty_reason, REASON_VIEW_TEMPLATE_EMPTY)
        self.assertEqual(view_missing_reason, REASON_VIEW_NOT_FOUND)
        self.assertEqual(zone_missing_reason, REASON_ZONE_NOT_FOUND)

    # TODO Is this test overkill?
    def test_update_path_top_level_template_error_logs_and_cleans_up(self):
        """
        Verify defensive error handling when update reconciliation raises at top level.

        What this test covers:
        - The exception branch in ``_update_dns_records_for_object()`` where
          ``_reconcile_records_for_rule()`` raises ``TemplateError``.
        - Correct side effects for that branch:
          1) orphan cleanup is still invoked,
          2) rule-processing error is logged with update-phase metadata,
          3) rule/object cleanup is executed.

        Why this can happen in real runs:
        - Most template/view/zone issues are handled per-candidate and skipped, but
          unexpected errors can still escape from reconciliation orchestration (for
          example, internal state drift, edge-case data, or behavior changes in
          underlying model/query operations). This branch is the fail-safe path for
          those escaped exceptions.

        Why this uses mocks instead of a pure end-to-end setup:
        - The exact top-level branch is hard to trigger deterministically through
          public object mutations because normal candidate failures are intentionally
          swallowed and converted into per-candidate skips.
        - Mocking ``_reconcile_records_for_rule()`` gives a stable, focused unit test
          of control flow and side effects without coupling to unrelated template/data
          mechanics that are validated elsewhere by integration tests.
        """
        rule = DNSRule.objects.create(
            name="logging-update-top-level-error",
            description="Top-level reconcile exception handling",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

        source_content_type = ContentType.objects.get_for_model(self.interface)
        dns_record_content_type = ContentType.objects.get_for_model(ARecord)
        DNSRuleRecord.objects.create(
            rule=rule,
            content_type=source_content_type,
            object_id=self.interface.id,
            dns_record_content_type=dns_record_content_type,
            dns_record_object_id=uuid.uuid4(),
        )

        with (
            patch.object(self.engine, "get_applicable_rules", return_value=[rule]),
            patch.object(RecordWriter, "cleanup_orphaned_records", return_value=0) as cleanup_orphaned_mock,
            patch.object(RuleResolver, "object_needs_dns_records_for_rule", return_value=True),
            patch.object(RecordWriter, "reconcile_records_for_rule", side_effect=TemplateError("boom")),
            patch.object(self._engine_logger, "log_rule_processing_error") as log_error_mock,
            patch.object(RecordWriter, "_cleanup_records_for_rule", return_value=0) as cleanup_rule_mock,
        ):
            self.engine.process_object(self.interface, created=False)

        cleanup_orphaned_mock.assert_called_once()
        log_error_mock.assert_called_once()
        cleanup_rule_mock.assert_called_once_with(rule, self.interface)
        _, kwargs = log_error_mock.call_args
        self.assertEqual(kwargs["phase"], PHASE_UPDATE_RECONCILE)
        self.assertTrue(kwargs["cleanup"])

    def test_get_dns_views_for_rule_empty_rendered_names_raises_validation_error(self):
        """View template that renders only separators should raise view_template ValidationError."""
        rule = DNSRule.objects.create(
            name="view-template-empty-names",
            description="View template empty names path",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            view_template="{{ ',,,' }}",
            enabled=True,
        )
        context = {"obj": wrap_for_template(self.interface)}

        # pylint: disable=protected-access
        with self.assertRaises(DNSRuleRenderedValueLookupError) as exc:
            self.engine._materializer.get_dns_views_for_rule(rule, context)

        self.assertEqual(exc.exception.field_name, "view_template")
        self.assertEqual(exc.exception.reason_code, REASON_VIEW_TEMPLATE_EMPTY)
        self.assertIn("rendered no DNS view names", str(exc.exception))

    def test_get_record_data_variations_for_rule_missing_value_template_raises(self):
        """A/AAAA rule without value_template should raise DNSRuleTemplateRenderedEmptyError in variations builder."""
        rule = DNSRule.objects.create(
            name="missing-value-template-runtime",
            description="Missing value template runtime path",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="",
            enabled=True,
        )
        context = {"obj": wrap_for_template(self.interface)}
        base_record_data = {"name": "eth0.test-device"}

        # pylint: disable=protected-access
        with self.assertRaises(DNSRuleTemplateRenderedEmptyError) as exc:
            self.engine._materializer.get_record_data_variations_for_rule(rule, context, base_record_data)  # pylint: disable=protected-access
        self.assertIn("Template value_template rendered empty", str(exc.exception))


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

    @override_config(nautobot_dns_models__NORMALIZE_DNS_RECORDS=False)
    def test_engine_record_creation_requires_pre_normalized_name_when_normalization_disabled(self):
        """Engine path should not normalize candidate names when config is disabled."""
        rule = DNSRule.objects.create(
            name="engine-normalization-disabled",
            description="Engine should preserve non-normalized candidate names when disabled",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            # device.role.name contains spaces/uppercase in shared fixtures
            name_template="{{ obj.device.role.name }}.{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

        self.engine.process_object(self.interface, created=False)

        expected_name = normalize_dns_name(f"{self.device_role.name}.{self.interface.name}.{self.device.name}")
        self.assertEqual(
            ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(),
            0,
            "Engine should not create a normalized record when normalization config is disabled",
        )
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=rule, object_id=self.interface.id).count(),
            0,
            "Tracking row should not be created when candidate fails normalization validation",
        )

    @override_config(nautobot_dns_models__NORMALIZE_DNS_RECORDS=True)
    def test_engine_record_creation_normalizes_name_when_enabled(self):
        """Engine path should normalize candidate names when config is enabled."""
        rule = DNSRule.objects.create(
            name="engine-normalization-enabled",
            description="Engine should normalize candidate names when enabled",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            # device.role.name contains spaces/uppercase in shared fixtures
            name_template="{{ obj.device.role.name }}.{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

        self.engine.process_object(self.interface, created=False)

        expected_name = normalize_dns_name(f"{self.device_role.name}.{self.interface.name}.{self.device.name}")
        self.assertEqual(
            ARecord.objects.filter(name=expected_name, zone=self.dns_zone).count(),
            1,
            "Engine should create a normalized record when normalization config is enabled",
        )
        self.assertEqual(
            DNSRuleRecord.objects.filter(rule=rule, object_id=self.interface.id).count(),
            1,
            "Tracking row should be created for successful normalized candidate",
        )

        rule_record = DNSRuleRecord.objects.get(rule=rule, object_id=self.interface.id)
        self.assertEqual(
            rule_record.dns_record,
            ARecord.objects.get(name=expected_name, zone=self.dns_zone),
            "Tracking row should point to the correct A record",
        )

    @override_settings(
        DEBUG=True,
        LOGGING=TEST_LOGGING_CONFIG,
    )
    @override_config(
        nautobot_dns_models__NORMALIZE_DNS_RECORDS=True,
    )
    def test_template_failure_preserves_existing_records(self):  # pylint: disable=too-many-locals
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
        self.assertEqual(results[0]["address_id"], self.ip_addresses[0].pk)

    def test_interface_last_empty(self):
        """Interface last() should raise DNSRuleTemplateRenderedEmptyError when no IPs exist."""
        rule = DNSRule.objects.create(
            name="interface-last-empty",
            content_type=self.interface_content_type,
            record_type="A",
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.ip_addresses.last() }}",
        )
        self.interface.ip_addresses.clear()

        with self.assertRaises(DNSRuleTemplateRenderedEmptyError) as context:
            self._calc_desired_record_data(rule, self.interface)

        self.assertIn("Template value_template rendered empty", str(context.exception))

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
        expected_ids = {self.ip_addresses[0].pk, self.ip_addresses[1].pk}
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
        expected_ids = {self.ip_addresses[0].pk, self.ip_addresses[1].pk}
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
        expected_ids = {self.ip_addresses[0].pk, self.ip_addresses[1].pk}
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
        self.assertEqual(results[0]["address_id"], self.ip_addresses[0].pk)
