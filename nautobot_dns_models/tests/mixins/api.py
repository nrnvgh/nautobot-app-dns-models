from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import Namespace
from rest_framework import status

from nautobot_dns_models import models
from nautobot_dns_models.models import DNSZone


class RuleEngineInterfaceIPAssignmentAPIMixin:
    """Base setup for assigning IPs to interfaces via the API and verifying DNS records."""

    model = None

    @classmethod
    def setUpTestData(cls):  # pylint: disable=invalid-name
        """Create minimal objects: site/location, device/interface, IPs, zone, and a global ruleset."""
        super().setUpTestData()

        # Core objects
        cls.active_status = Status.objects.get(name="Active")
        cls.namespace = Namespace.objects.get(name="Global")

        # Location + Device + Interface
        location_type = LocationType.objects.create(name="Site")
        location = Location.objects.create(name="SiteA", location_type=location_type, status=cls.active_status)
        manufacturer = Manufacturer.objects.create(name="Acme")
        device_type = DeviceType.objects.create(manufacturer=manufacturer, model="Router1000")
        role, _ = Role.objects.get_or_create(name="Router", defaults={"color": "ff0000"})
        role.content_types.add(ContentType.objects.get_for_model(Device))
        cls.device = Device.objects.create(
            name="r1",
            device_type=device_type,
            role=role,
            status=cls.active_status,
            location=location,
        )

        # DNS zone
        cls.zone = DNSZone.objects.create(
            name="example.com",
            filename="example.com.zone",
            soa_mname="ns1.example.com",
            soa_rname="admin@example.com",
        )

        # Global rules (content_type: Interface) to generate A/AAAA on assignment
        iface_ct = ContentType.objects.get_for_model(Interface)
        models.DNSRule.objects.create(
            name="iface-A",
            enabled=True,
            content_type=iface_ct,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )
        models.DNSRule.objects.create(
            name="iface-AAAA",
            enabled=True,
            content_type=iface_ct,
            zone_template="example.com",
            record_type="AAAA",
            name_template="{{ obj.name }}.{{ obj.device.name }}",
            value_template="{{ obj.ip_addresses.all() }}",
        )

    def test_single_ip_assignment_creates_dns_record(self):
        """Test that a single IP assignment creates a DNS record."""
        self.add_permissions(
            "ipam.add_ipaddresstointerface",
            "nautobot_dns_models.view_arecord",
            "ipam.view_ipaddress",
            "dcim.view_interface",
        )

        url = reverse("ipam-api:ipaddresstointerface-list")

        interface = Interface.objects.create(name="eth0", device=self.device, status=self.active_status)

        payload = {
            "ip_address": str(self.ip_address_1.pk),
            "interface": str(interface.pk),
        }
        response = self.client.post(url, data=payload, format="json", **self.header)

        self.assertHttpStatus(response, status.HTTP_201_CREATED)

        self.assertEqual(self.model.objects.count(), 1)
        self.assertEqual(self.model.objects.first().address, self.ip_address_1)
        self.assertEqual(self.model.objects.first().name, f"{interface.name}.{self.device.name}")

    def test_multiple_ip_assignments_one_at_a_time_creates_dns_records(self):
        """Test that multiple IP assignments, one at a time, create DNS records."""

        self.add_permissions(
            "ipam.add_ipaddresstointerface",
            "nautobot_dns_models.view_arecord",
            "ipam.view_ipaddress",
            "dcim.view_interface",
        )

        interface = Interface.objects.create(name="eth0", device=self.device, status=self.active_status)

        url = reverse("ipam-api:ipaddresstointerface-list")
        for ip_address in [self.ip_address_1, self.ip_address_2]:
            payload = {
                "ip_address": str(ip_address.pk),
                "interface": str(interface.pk),
            }
            response = self.client.post(url, data=payload, format="json", **self.header)
            self.assertHttpStatus(response, status.HTTP_201_CREATED)

        self.assertEqual(self.model.objects.count(), 2)

        self.assertEqual(
            set(self.model.objects.values_list("address", flat=True)), {self.ip_address_1.pk, self.ip_address_2.pk}
        )

    def test_multiple_ip_assignments_in_one_call_creates_dns_records(self):
        """Test that multiple IP assignments, in one call, create DNS records."""
        self.add_permissions(
            "ipam.add_ipaddresstointerface",
            "nautobot_dns_models.view_arecord",
            "ipam.view_ipaddress",
            "dcim.view_interface",
        )

        interface = Interface.objects.create(name="eth0", device=self.device, status=self.active_status)

        url = reverse("ipam-api:ipaddresstointerface-list")
        payload = [
            {"interface": str(interface.pk), "ip_address": str(ip.pk)} for ip in [self.ip_address_1, self.ip_address_2]
        ]
        response = self.client.post(url, data=payload, format="json", **self.header)
        self.assertHttpStatus(response, status.HTTP_201_CREATED)
        self.assertEqual(self.model.objects.count(), 2)

        self.assertEqual(
            set(self.model.objects.values_list("address", flat=True)), {self.ip_address_1.pk, self.ip_address_2.pk}
        )


class RuleEngineDeviceIPAssignmentAPIMixin:
    """Base setup for assigning IPs to devices via the API and verifying DNS records."""

    model = None

    @classmethod
    def setUpTestData(cls):  # pylint: disable=invalid-name
        """Create minimal objects: site/location, device/interface, IPs, zone, and a global ruleset."""
        super().setUpTestData()

        # Core objects
        cls.active_status = Status.objects.get(name="Active")
        cls.namespace = Namespace.objects.get(name="Global")

        # Location + Device + Interface
        location_type = LocationType.objects.create(name="Site")
        location_type.content_types.add(ContentType.objects.get_for_model(Device))
        location = Location.objects.create(name="SiteA", location_type=location_type, status=cls.active_status)
        manufacturer = Manufacturer.objects.create(name="Acme")
        device_type = DeviceType.objects.create(manufacturer=manufacturer, model="Router1000")
        role, _ = Role.objects.get_or_create(name="Router", defaults={"color": "ff0000"})
        role.content_types.add(ContentType.objects.get_for_model(Device))
        cls.device = Device.objects.create(
            name="r1",
            device_type=device_type,
            role=role,
            status=cls.active_status,
            location=location,
        )

        # DNS zone
        cls.zone = DNSZone.objects.create(
            name="example.com",
            filename="example.com.zone",
            soa_mname="ns1.example.com",
            soa_rname="admin@example.com",
        )

        # Global rules (content_type: Device) to generate A/AAAA on assignment
        device_ct = ContentType.objects.get_for_model(Device)
        models.DNSRule.objects.create(
            name="device-A",
            enabled=True,
            content_type=device_ct,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )
        models.DNSRule.objects.create(
            name="device-AAAA",
            enabled=True,
            content_type=device_ct,
            zone_template="example.com",
            record_type="AAAA",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip6 }}",
        )

    def test_ip_assignment_creates_dns_record(self):
        """Test that an IP assignment creates a DNS record."""
        self.add_permissions(
            "ipam.add_ipaddress",
            "nautobot_dns_models.view_arecord",
            "ipam.view_ipaddress",
            "dcim.view_device",
            "dcim.change_device",
        )

        url = reverse("dcim-api:device-detail", args=[self.device.pk])

        # primary_ipX IPs must be first be assigned to an interface
        interface = Interface.objects.create(name="eth0", device=self.device, status=self.active_status)
        interface.ip_addresses.add(self.ip_address_1)

        payload = {
            self.device_ip_field: str(self.ip_address_1.pk),
        }

        response = self.client.patch(url, data=payload, format="json", **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)

        self.assertEqual(self.model.objects.count(), 1)
        self.assertEqual(self.model.objects.first().address, self.ip_address_1)
        self.assertEqual(self.model.objects.first().name, self.device.name)

    def test_ip_removal_deletes_dns_record(self):
        """Test that an IP removal deletes a DNS record."""
        self.add_permissions(
            "ipam.add_ipaddress",
            "nautobot_dns_models.view_arecord",
            "ipam.view_ipaddress",
            "dcim.view_device",
            "dcim.change_device",
        )

        url = reverse("dcim-api:device-detail", args=[self.device.pk])

        setattr(self.device, self.device_ip_field, self.ip_address_1)
        self.device.save()
        self.device.refresh_from_db()
        self.assertEqual(self.model.objects.count(), 1)
        self.assertEqual(getattr(self.device, self.device_ip_field), self.ip_address_1)

        payload = {
            self.device_ip_field: None,
        }

        response = self.client.patch(url, data=payload, format="json", **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)

        self.device.refresh_from_db()
        self.assertEqual(getattr(self.device, self.device_ip_field), None)

        self.assertEqual(self.model.objects.count(), 0)
