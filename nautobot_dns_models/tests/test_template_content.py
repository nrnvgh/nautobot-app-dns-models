"""Tests for template-content reconcile button behavior."""

from urllib.parse import parse_qs, urlparse

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from nautobot.apps.choices import InterfaceTypeChoices
from nautobot.apps.testing import TestCase
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.management import populate_status_choices
from nautobot.extras.models import Role, Status

from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.template_content import DeviceReconcileDNSAction, InterfaceReconcileDNSAction

User = get_user_model()


class ReconcileButtonTemplateContentTestCase(TestCase):
    """Validate per-object reconcile button visibility and link construction."""

    def setUp(self):
        """Set up minimal real model fixtures for Device view rendering tests."""
        super().setUp()
        populate_status_choices(apps=apps, schema_editor=None)

        self.request_factory = RequestFactory()
        self.user = User.objects.create(username="reconcile-button-user", is_superuser=True, is_staff=True)

        self.location_type = LocationType.objects.create(name="Template Test Location Type")
        self.location_type.content_types.add(ContentType.objects.get_for_model(Device))
        self.location = Location.objects.create(
            name="Template Test Location",
            location_type=self.location_type,
            status=Status.objects.get_for_model(Location).first(),
        )

        manufacturer = Manufacturer.objects.create(name="Template Test Manufacturer")
        device_type = DeviceType.objects.create(manufacturer=manufacturer, model="Template Test Device Type")
        device_role = Role.objects.create(name="Template Test Device Role")
        device_role.content_types.add(ContentType.objects.get_for_model(Device))

        self.device = Device.objects.create(
            name="template-test-device",
            device_type=device_type,
            location=self.location,
            role=device_role,
            status=Status.objects.get_for_model(Device).first(),
        )
        self.interface = Interface.objects.create(
            name="eth0",
            device=self.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=Status.objects.get_for_model(Interface).first(),
        )

    def _get_context(self):
        """Build object-detail render context for Device view."""
        request = self.request_factory.get("/")
        request.user = self.user
        return {"object": self.device, "request": request, "active_tab": "main"}

    def test_button_hidden_when_no_rule_is_in_scope(self):
        """Button should not render on Device without applicable enabled DNS rules."""
        button = DeviceReconcileDNSAction.object_detail_buttons[0]

        self.assertFalse(button.should_render(self._get_context()))

    def test_button_renders_and_links_single_object_inputs(self):
        """Button should render and pre-populate single-object parent inputs in run URL."""
        DNSRule.objects.create(
            name="button-device-rule",
            content_type=ContentType.objects.get_for_model(Device),
            record_type="A",
            location=self.location,
            zone_template="example.com",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )
        button = DeviceReconcileDNSAction.object_detail_buttons[0]
        context = self._get_context()

        self.assertTrue(button.should_render(context))

        link = button.get_link(context)
        parsed = urlparse(link)
        query = parse_qs(parsed.query)

        self.assertIn("/extras/jobs/nautobot_dns_models.jobs.ReconcileDNSObjectJob/run/", parsed.path)
        self.assertEqual(query["object_model"], ["dcim.device"])
        self.assertEqual(query["object_id"], [str(self.device.pk)])
        self.assertEqual(query["object_name"], [str(self.device)])
        self.assertEqual(query["object_url"], [self.device.get_absolute_url()])
        self.assertEqual(query["include_children"], ["true"])

    def test_button_renders_for_parent_when_child_rule_is_in_scope(self):
        """Device button should render when only Interface rules are in scope."""
        DNSRule.objects.create(
            name="button-interface-rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            location=self.location,
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all | ip_address }}",
        )
        button = DeviceReconcileDNSAction.object_detail_buttons[0]
        context = self._get_context()

        self.assertTrue(button.should_render(context))

    def test_child_object_button_link_includes_parent_name(self):
        """Child-object button link should include parent object display name."""
        DNSRule.objects.create(
            name="button-interface-rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type="A",
            location=self.location,
            zone_template="example.com",
            name_template="{{ obj.device.name }}-{{ obj.name }}",
            value_template="{{ obj.ip_addresses.all | ip_address }}",
        )
        request = self.request_factory.get("/")
        request.user = self.user
        context = {"object": self.interface, "request": request, "active_tab": "main"}
        button = InterfaceReconcileDNSAction.object_detail_buttons[0]

        self.assertTrue(button.should_render(context))
        link = button.get_link(context)
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        self.assertEqual(query["parent_object_name"], [str(self.device)])
