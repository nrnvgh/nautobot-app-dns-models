"""Unit tests for nautobot_dns_models."""

import logging

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from nautobot.apps.testing import APITestCase, APIViewTestCases
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role
from nautobot.extras.models.statuses import Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix
from rest_framework import status

from nautobot_dns_models import models
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CNAMERecord,
    DNSRule,
    DNSView,
    DNSViewPrefixAssignment,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
)

User = get_user_model()


class DNSViewAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot DNSView API."""

    model = DNSView
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
    ]

    @classmethod
    def setUpTestData(cls):
        DNSView.objects.create(name="View 1", description="First DNS View")
        DNSView.objects.create(name="View 2", description="Second DNS View")
        DNSView.objects.create(name="View 3", description="Third DNS View")

        cls.create_data = [
            {
                "name": "View 4",
                "description": "Fourth DNS View",
            },
            {
                "name": "View 5",
                "description": "Fifth DNS View",
            },
            {
                "name": "View 6",
                "description": "Sixth DNS View",
            },
        ]


class DNSViewPrefixAssignmentAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot DNSViewPrefixAssignment API."""

    model = DNSViewPrefixAssignment
    view_namespace = "plugins-api:nautobot_dns_models"

    brief_fields = [
        "dns_view",
        "prefix",
    ]

    @classmethod
    def setUpTestData(cls):
        namespace = Namespace.objects.get(name="Global")
        active_status = Status.objects.get(name="Active")
        prefixes = (
            Prefix.objects.create(prefix="192.0.2.0/24", namespace=namespace, status=active_status),
            Prefix.objects.create(prefix="192.0.2.0/25", namespace=namespace, status=active_status),
            Prefix.objects.create(prefix="192.0.3.0/24", namespace=namespace, status=active_status),
        )

        dns_views = (
            DNSView.objects.create(name="View 1", description="First DNS View"),
            DNSView.objects.create(name="View 2", description="Second DNS View"),
            DNSView.objects.create(name="View 3", description="Third DNS View"),
        )

        DNSViewPrefixAssignment.objects.create(dns_view=dns_views[0], prefix=prefixes[0])
        DNSViewPrefixAssignment.objects.create(dns_view=dns_views[0], prefix=prefixes[1])
        DNSViewPrefixAssignment.objects.create(dns_view=dns_views[2], prefix=prefixes[1])

        cls.create_data = [
            {
                "dns_view": dns_views[1].pk,
                "prefix": prefixes[0].pk,
            },
            {
                "dns_view": dns_views[1].pk,
                "prefix": prefixes[2].pk,
            },
        ]


class DNSZoneAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot DNSZone API."""

    model = DNSZone
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "filename",
        "soa_mname",
        "soa_rname",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_view = DNSView.objects.get(name="Default")
        DNSZone.objects.create(
            name="test.com",
            dns_view=dns_view,
            filename="test.com.zone",
            soa_mname="ns1.test.com",
            soa_rname="admin@test.com",
        )
        DNSZone.objects.create(
            name="test.org",
            dns_view=dns_view,
            filename="test.org.zone",
            soa_mname="ns1.test.org",
            soa_rname="admin@test.org",
        )
        DNSZone.objects.create(
            name="test.net",
            dns_view=dns_view,
            filename="test.net.zone",
            soa_mname="ns1.test.net",
            soa_rname="admin@test.net",
        )

        cls.create_data = [
            {
                "name": "example.com",
                "dns_view": dns_view.id,
                "filename": "example.com.zone",
                "soa_mname": "ns1.example.com",
                "soa_rname": "admin@example.com",
                "soa_refresh": 3600,
                "soa_retry": 600,
            },
            {
                "name": "example.org",
                "dns_view": dns_view.id,
                "filename": "example.org.zone",
                "soa_mname": "ns1.example.org",
                "soa_rname": "admin@example.org",
            },
            {
                "name": "example.net",
                "dns_view": dns_view.id,
                "filename": "example.net.zone",
                "soa_mname": "ns1.example.net",
                "soa_rname": "admin@example.net",
            },
        ]


class NSRecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot NSRecord API."""

    model = NSRecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "server",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_zone = DNSZone.objects.create(
            name="example.com", filename="example.com.zone", soa_mname="ns1.example.com", soa_rname="admin@example.com"
        )

        NSRecord.objects.create(name="ns1", server="ns1.example.com.", zone=dns_zone)
        NSRecord.objects.create(name="ns2", server="ns2.example.com.", zone=dns_zone)
        NSRecord.objects.create(name="ns3", server="ns3.example.com.", zone=dns_zone)

        cls.create_data = [
            {
                "name": "ns4",
                "server": "ns4.example.com.",
                "zone": dns_zone.id,
            },
            {
                "name": "ns5",
                "server": "ns5.example.com.",
                "zone": dns_zone.id,
            },
            {
                "name": "ns6",
                "server": "ns6.example.com.",
                "zone": dns_zone.id,
            },
        ]


class ARecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot ARecord API."""

    model = ARecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "address",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_zone = DNSZone.objects.create(
            name="example.com", filename="example.com.zone", soa_mname="ns1.example.com", soa_rname="admin@example.com"
        )

        namespace = Namespace.objects.get(name="Global")
        active_status = Status.objects.get(name="Active")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=active_status)
        ip_addresses = (
            IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=active_status),
            IPAddress.objects.create(address="10.0.0.2/32", namespace=namespace, status=active_status),
        )

        # IPv6 Test Data
        cls.ipv6_zone = DNSZone.objects.create(name="example_ipv6.com")
        Prefix.objects.create(prefix="2001:db8::/64", namespace=namespace, type="Pool", status=active_status)
        cls.invalid_ipv6 = IPAddress.objects.create(
            address="2001:db8::1/128", namespace=namespace, status=active_status
        )

        ARecord.objects.create(name="example.com", address=ip_addresses[0], zone=dns_zone)
        ARecord.objects.create(name="www.example.com", address=ip_addresses[0], zone=dns_zone)
        ARecord.objects.create(name="site.example.com", address=ip_addresses[0], zone=dns_zone)

        cls.create_data = [
            {
                "name": "example.com",
                "address": ip_addresses[1].id,
                "zone": dns_zone.id,
            },
            {
                "name": "www.example.com",
                "address": ip_addresses[1].id,
                "zone": dns_zone.id,
            },
            {
                "name": "site.example.com",
                "address": ip_addresses[1].id,
                "zone": dns_zone.id,
            },
        ]

    def test_create_arecord_with_invalid_ipv6_fails(self):
        """Attempt to create an ARecord using an IPv6 address should fail."""
        self.add_permissions("nautobot_dns_models.add_arecord")

        url = reverse("plugins-api:nautobot_dns_models-api:arecord-list")
        data = {
            "name": "invalid.example.com",
            "address": str(self.invalid_ipv6.id),
            "zone": str(self.ipv6_zone.id),
            "ttl": 3600,
        }

        response = self.client.post(url, data=data, format="json", **self.header)

        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)


class AAAARecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot AAAARecord API."""

    model = AAAARecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "address",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_zone = DNSZone.objects.create(
            name="example.com", filename="example.com.zone", soa_mname="ns1.example.com", soa_rname="admin@example.com"
        )

        active_status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="2001:db8:abcd:12::/64", namespace=namespace, type="Pool", status=active_status)
        ip_addresses = (
            IPAddress.objects.create(address="2001:db8:abcd:12::1/128", namespace=namespace, status=active_status),
            IPAddress.objects.create(address="2001:db8:abcd:12::2/128", namespace=namespace, status=active_status),
        )

        # IPv4 Test Data
        cls.zone = DNSZone.objects.create(name="example_ipv4.com")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=active_status)
        cls.invalid_ipv4 = IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=active_status)

        AAAARecord.objects.create(name="example.com", address=ip_addresses[0], zone=dns_zone)
        AAAARecord.objects.create(name="www.example.com", address=ip_addresses[0], zone=dns_zone)
        AAAARecord.objects.create(name="site.example.com", address=ip_addresses[0], zone=dns_zone)

        cls.create_data = [
            {
                "name": "example.com",
                "address": ip_addresses[1].id,
                "zone": dns_zone.id,
            },
            {
                "name": "www.example.com",
                "address": ip_addresses[1].id,
                "zone": dns_zone.id,
            },
            {
                "name": "site.example.com",
                "address": ip_addresses[1].id,
                "zone": dns_zone.id,
            },
        ]

    def test_create_aaaarecord_with_invalid_ipv4_fails(self):
        """Attempt to create an AAAARecord using an IPv4 address should fail."""
        self.add_permissions("nautobot_dns_models.add_aaaarecord")

        url = reverse("plugins-api:nautobot_dns_models-api:aaaarecord-list")
        data = {
            "name": "invalid.example.com",
            "address": str(self.invalid_ipv4.id),
            "zone": str(self.zone.id),
            "ttl": 3600,
        }

        response = self.client.post(url, data=data, format="json", **self.header)

        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)


class CNAMERecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot CNAMERecord API."""

    model = CNAMERecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "alias",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_zone = DNSZone.objects.create(
            name="example.com", filename="example.com.zone", soa_mname="ns1.example.com", soa_rname="admin@example.com"
        )

        CNAMERecord.objects.create(name="www", alias="www.example.com", zone=dns_zone)
        CNAMERecord.objects.create(name="site", alias="site.example.com", zone=dns_zone)
        CNAMERecord.objects.create(name="blog", alias="blog.example.com", zone=dns_zone)

        cls.create_data = [
            {
                "name": "test01",
                "alias": "test01.example.com",
                "zone": dns_zone.id,
            },
            {
                "name": "test02",
                "alias": "test02.example.com",
                "zone": dns_zone.id,
            },
            {
                "name": "test03",
                "alias": "test03.example.com",
                "zone": dns_zone.id,
            },
        ]


class MXRecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot MXRecord API."""

    model = MXRecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "mail_server",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_zone = DNSZone.objects.create(
            name="example.com", filename="example.com.zone", soa_mname="ns1.example.com", soa_rname="admin@example.com"
        )

        MXRecord.objects.create(name="mail", mail_server="mail.example.com", zone=dns_zone)
        MXRecord.objects.create(name="mail2", mail_server="mail2.example.com", zone=dns_zone)
        MXRecord.objects.create(name="mail3", mail_server="mail3.example.com", zone=dns_zone)

        cls.create_data = [
            {
                "name": "mail4",
                "mail_server": "mail4.example.com",
                "zone": dns_zone.id,
            },
            {
                "name": "mail5",
                "mail_server": "mail5.example.com",
                "zone": dns_zone.id,
            },
            {
                "name": "mail6",
                "mail_server": "mail6.example.com",
                "zone": dns_zone.id,
            },
        ]


class TXTRecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot TXTRecord API."""

    model = TXTRecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "text",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_zone = DNSZone.objects.create(
            name="example.com", filename="example.com.zone", soa_mname="ns1.example.com", soa_rname="admin@example.com"
        )

        TXTRecord.objects.create(name="txt", text="spf-record-01", zone=dns_zone)
        TXTRecord.objects.create(name="txt2", text="spf-record-02", zone=dns_zone)
        TXTRecord.objects.create(name="txt3", text="spf-record-03", zone=dns_zone)

        cls.create_data = [
            {
                "name": "txt4",
                "text": "spf-record-04",
                "zone": dns_zone.id,
            },
            {
                "name": "txt5",
                "text": "spf-record-05",
                "zone": dns_zone.id,
            },
            {
                "name": "txt6",
                "text": "spf-record-06",
                "zone": dns_zone.id,
            },
        ]


class PTRRecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot PTRRecord API."""

    model = PTRRecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "ptrdname",
    ]

    @classmethod
    def setUpTestData(cls):
        dns_zone = DNSZone.objects.create(
            name="example.com", filename="example.com.zone", soa_mname="ns1.example.com", soa_rname="admin@example.com"
        )

        PTRRecord.objects.create(name="ptr-record-01", ptrdname="ptr-01", zone=dns_zone)
        PTRRecord.objects.create(name="ptr-record-02", ptrdname="ptr-02", zone=dns_zone)
        PTRRecord.objects.create(name="ptr-record-03", ptrdname="ptr-03", zone=dns_zone)

        cls.create_data = [
            {
                "name": "ptr-record-04",
                "ptrdname": "ptr-04",
                "zone": dns_zone.id,
            },
            {
                "name": "ptr-record-05",
                "ptrdname": "ptr-05",
                "zone": dns_zone.id,
            },
            {
                "name": "ptr-record-06",
                "ptrdname": "ptr-06",
                "zone": dns_zone.id,
            },
        ]


class SRVRecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot SRVRecord API."""

    model = SRVRecord
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "target",
    ]

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(name="example.com")
        SRVRecord.objects.create(
            name="_sip._tcp.example.com", priority=10, weight=5, port=5060, target="sip.example.com", zone=zone
        )
        SRVRecord.objects.create(
            name="_ldap._tcp.example.com", priority=20, weight=10, port=389, target="ldap.example.com", zone=zone
        )
        SRVRecord.objects.create(
            name="_xmpp._tcp.example.com", priority=30, weight=15, port=5222, target="xmpp.example.com", zone=zone
        )

        cls.create_data = [
            {
                "name": "_smtp._tcp.example.com",
                "priority": 40,
                "weight": 20,
                "port": 25,
                "target": "smtp.example.com",
                "zone": zone.id,
            },
            {
                "name": "_imap._tcp.example.com",
                "priority": 50,
                "weight": 25,
                "port": 143,
                "target": "imap.example.com",
                "zone": zone.id,
            },
            {
                "name": "_pop3._tcp.example.com",
                "priority": 60,
                "weight": 30,
                "port": 110,
                "target": "pop3.example.com",
                "zone": zone.id,
            },
        ]


class DNSRuleAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot DNSRule API."""

    model = models.DNSRule
    view_namespace = "plugins-api:nautobot_dns_models"
    bulk_update_data = {
        "description": "Example bulk description",
    }
    brief_fields = [
        "name",
        "enabled",
        "record_type",
    ]
    choices_fields = ["content_type", "record_type"]

    @classmethod
    def setUpTestData(cls):
        # Create test data for DNSRule
        content_type = ContentType.objects.get_for_model(Device)

        # Create location and related objects for testing
        active_status = Status.objects.get(name="Active")
        namespace = Namespace.objects.first()
        location_type = LocationType.objects.create(name="Site")
        location = Location.objects.create(name="Test Site", location_type=location_type, status=active_status)

        # Create sample Device objects for template validation
        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_role, _ = Role.objects.get_or_create(name="Test Device Role", defaults={"color": "ff0000"})
        cls.device_role.content_types.add(ContentType.objects.get_for_model(Device))
        cls.device_type = DeviceType.objects.create(manufacturer=cls.manufacturer, model="Test Device Type")

        # Create IP addresses for the devices
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=active_status)
        Prefix.objects.create(prefix="2001:db8::/64", namespace=namespace, type="Pool", status=active_status)

        cls.ip4 = IPAddress.objects.create(address="10.0.0.10/32", namespace=namespace, status=active_status)
        cls.ip6 = IPAddress.objects.create(address="2001:db8::10/128", namespace=namespace, status=active_status)

        # Create sample device with IP addresses for template validation
        cls.sample_device = Device.objects.create(
            name="sample-device",
            device_type=cls.device_type,
            role=cls.device_role,
            location=location,
            status=active_status,
            primary_ip4=cls.ip4,
            primary_ip6=cls.ip6,
        )

        DNSRule.objects.create(
            name="Test Rule 1",
            description="Test DNS rule for devices",
            enabled=True,
            content_type=content_type,
            location=location,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

        DNSRule.objects.create(
            name="Test Rule 2",
            description="Another test DNS rule",
            enabled=False,
            content_type=content_type,
            zone_template="test.com",
            record_type="CNAME",
            name_template="{{ obj.name }}-alias",
            value_template="{{ obj.name }}.test.com",
        )

        DNSRule.objects.create(
            name="Test Rule 3",
            description="Third test DNS rule",
            enabled=True,
            content_type=content_type,
            zone_template="internal.com",
            record_type="AAAA",
            name_template="{{ obj.name }}-internal",
            value_template="{{ obj.primary_ip6 }}",
        )

        cls.create_data = [
            {
                "name": "New Test Rule 1",
                "description": "New DNS rule via API",
                "enabled": True,
                "content_type": "dcim.device",
                "zone_template": "api.com",
                "record_type": "TXT",
                "name_template": "{{ obj.name }}-api",
                "value_template": "v=spf1 include:_spf.google.com ~all",
            },
            {
                "name": "New Test Rule 2",
                "description": "Another new DNS rule via API",
                "enabled": False,
                "content_type": "dcim.device",
                "zone_template": "api2.com",
                "record_type": "NS",
                "name_template": "{{ obj.name }}-ns",
                "value_template": "ns1.api2.com",
            },
            {
                "name": "New Test Rule 3",
                "description": "Third new DNS rule via API",
                "enabled": True,
                "content_type": "dcim.device",
                "zone_template": "api3.com",
                "record_type": "MX",
                "name_template": "{{ obj.name }}-mail",
                "value_template": "mail.api3.com",
                "preference_template": "10",
            },
        ]


class DNSRuleRecordAPITestCase(APIViewTestCases.APIViewTestCase):
    """Test the Nautobot DNSRuleRecord API."""

    model = models.DNSRuleRecord
    view_namespace = "plugins-api:nautobot_dns_models"

    # Since DNSRuleRecord is a BaseModel (like PrefixLocationAssignment),
    # it doesn't support bulk operations the same way
    bulk_update_data = {}

    brief_fields = [
        "rule",
        "source_object",
        "dns_record",
        "display",
        "id",
        "url",
    ]

    # Exclude UUID fields that have different representations between model and API
    validation_excluded_fields = [
        "object_id",
        "dns_record_object_id",
    ]

    choices_fields = ["content_type", "dns_record_content_type"]

    @classmethod
    def setUpTestData(cls):
        """Set up test data for DNSRuleRecord API tests."""
        super().setUpTestData()

        device_content_type = ContentType.objects.get_for_model(Device)
        ip_address_status = Status.objects.get_for_model(IPAddress).first()
        prefix_status = Status.objects.get_for_model(Prefix).first()

        # Create namespace, prefix and IP addresses for DNS testing
        namespace = Namespace.objects.create(name="Test Namespace")
        Prefix.objects.create(prefix="192.168.1.0/24", namespace=namespace, status=prefix_status)
        cls.ip_address = IPAddress.objects.create(
            address="192.168.1.100/24", namespace=namespace, status=ip_address_status
        )

        # Create required objects for Device creation
        manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        device_type = DeviceType.objects.create(manufacturer=manufacturer, model="Test Device Type")
        location_type = LocationType.objects.create(name="Test Location Type")
        location = Location.objects.create(
            name="Test Location", location_type=location_type, status=Status.objects.get_for_model(Location).first()
        )
        device_role = Role.objects.create(
            name="Test Device Role",
        )
        device_role.content_types.add(device_content_type)

        # Create test data needed for DNSRuleRecord
        cls.dns_zone = DNSZone.objects.create(
            name="example.com",
            filename="example.com.zone",
            soa_mname="ns1.example.com",
            soa_rname="admin@example.com",
        )

        cls.dns_rule = models.DNSRule.objects.create(
            name="test-rule",
            content_type=device_content_type,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
            enabled=True,
        )

        cls.device = Device.objects.create(
            name="test-device",
            device_type=device_type,
            role=device_role,
            status=Status.objects.get_for_model(Device).first(),
            location=location,
            primary_ip4=cls.ip_address,
        )

        cls.a_record = ARecord.objects.create(
            name="test-device.example.com",
            zone=cls.dns_zone,
            address=cls.ip_address,
        )

        # Create additional IP addresses for other devices
        cls.ip_address2 = IPAddress.objects.create(
            address="192.168.1.101/24", namespace=namespace, status=ip_address_status
        )

        cls.ip_address3 = IPAddress.objects.create(
            address="192.168.1.102/24", namespace=namespace, status=ip_address_status
        )

        # Create additional devices and records for testing
        cls.device2 = Device.objects.create(
            name="test-device-2",
            device_type=device_type,
            role=device_role,
            status=Status.objects.get_for_model(Device).first(),
            location=location,
            primary_ip4=cls.ip_address2,
        )

        cls.device3 = Device.objects.create(
            name="test-device-3",
            device_type=device_type,
            role=device_role,
            status=Status.objects.get_for_model(Device).first(),
            location=location,
            primary_ip4=cls.ip_address3,
        )

        cls.a_record2 = ARecord.objects.create(
            name="test-device-2.example.com",
            zone=cls.dns_zone,
            address=cls.ip_address2,
        )

        cls.a_record3 = ARecord.objects.create(
            name="test-device-3.example.com",
            zone=cls.dns_zone,
            address=cls.ip_address3,
        )

        # Create test DNSRuleRecord instances
        cls.create_data = [
            {
                "rule": cls.dns_rule.id,
                "content_type": "dcim.device",
                "object_id": str(cls.device.id),
                "dns_record_content_type": "nautobot_dns_models.arecord",
                "dns_record_object_id": str(cls.a_record.id),
            },
            {
                "rule": cls.dns_rule.id,
                "content_type": "dcim.device",
                "object_id": str(cls.device2.id),
                "dns_record_content_type": "nautobot_dns_models.arecord",
                "dns_record_object_id": str(cls.a_record2.id),
            },
            {
                "rule": cls.dns_rule.id,
                "content_type": "dcim.device",
                "object_id": str(cls.device3.id),
                "dns_record_content_type": "nautobot_dns_models.arecord",
                "dns_record_object_id": str(cls.a_record3.id),
            },
        ]


#
# TODO: delete this when we're done debugging
class DebugLoggingMixin:
    """Mixin for enabling DEBUG logging for plugin internals during these tests."""

    @classmethod
    def setUpClass(cls):  # noqa: D401
        """Enable DEBUG logging for plugin internals during these tests."""
        import sys

        super().setUpClass()
        cls._log_handler = logging.StreamHandler(sys.stdout)
        cls._log_handler.setLevel(logging.DEBUG)
        cls._signal_logger = logging.getLogger("nautobot_dns_models.signals")
        cls._engine_logger = logging.getLogger("nautobot_dns_models.rules.engine")
        for lg in (cls._signal_logger, cls._engine_logger):
            lg.setLevel(logging.DEBUG)
            lg.addHandler(cls._log_handler)

    @classmethod
    def tearDownClass(cls):  # noqa: D401
        """Disable DEBUG logging added in setUpClass."""
        try:
            for lg in (cls._signal_logger, cls._engine_logger):
                lg.removeHandler(cls._log_handler)
        finally:
            super().tearDownClass()


class RuleEngineInterfaceIPAssignmentMixin(DebugLoggingMixin):
    """Base setup for assigning IPs to interfaces via the API and verifying DNS records."""

    model = None

    @classmethod
    def setUpTestData(cls):  # noqa: D401 - standard Nautobot test setup method
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


class RuleEngineDeviceIPAssignmentMixin(DebugLoggingMixin):
    """Base setup for assigning IPs to devices via the API and verifying DNS records."""

    model = None

    @classmethod
    def setUpTestData(cls):  # noqa: D401 - standard Nautobot test setup method
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


class RuleEngineInterfaceIPAssignmentV4APITestCase(RuleEngineInterfaceIPAssignmentMixin, APITestCase):
    model = models.ARecord

    def setUp(self):
        super().setUp()

        # Address pools
        Prefix.objects.create(prefix="192.0.2.0/24", namespace=self.namespace, type="Pool", status=self.active_status)

        # IPs to assign
        self.ip_address_1 = IPAddress.objects.create(
            address="192.0.2.10/32", namespace=self.namespace, status=self.active_status
        )
        self.ip_address_2 = IPAddress.objects.create(
            address="192.0.2.11/32", namespace=self.namespace, status=self.active_status
        )


class RuleEngineInterfaceIPAssignmentV6APITestCase(RuleEngineInterfaceIPAssignmentMixin, APITestCase):
    model = models.AAAARecord

    def setUp(self):
        super().setUp()

        # Address pools
        Prefix.objects.create(
            prefix="2001:db8:100::/64", namespace=self.namespace, type="Pool", status=self.active_status
        )

        # IPs to assign
        self.ip_address_1 = IPAddress.objects.create(
            address="2001:db8:100::10/128", namespace=self.namespace, status=self.active_status
        )
        self.ip_address_2 = IPAddress.objects.create(
            address="2001:db8:100::11/128", namespace=self.namespace, status=self.active_status
        )


class RuleEngineDeviceIPAssignmentV4APITestCase(RuleEngineDeviceIPAssignmentMixin, APITestCase):
    model = models.ARecord

    def setUp(self):
        super().setUp()

        # Address pools
        Prefix.objects.create(prefix="192.0.2.0/24", namespace=self.namespace, type="Pool", status=self.active_status)

        # IPs to assign
        self.ip_address_1 = IPAddress.objects.create(
            address="192.0.2.10/32", namespace=self.namespace, status=self.active_status
        )
        self.device_ip_field = "primary_ip4"


class RuleEngineDeviceIPAssignmentV6APITestCase(RuleEngineDeviceIPAssignmentMixin, APITestCase):
    model = models.AAAARecord

    def setUp(self):
        super().setUp()

        # Address pools
        Prefix.objects.create(
            prefix="2001:db8:100::/64", namespace=self.namespace, type="Pool", status=self.active_status
        )

        # IPs to assign
        self.ip_address_1 = IPAddress.objects.create(
            address="2001:db8:100::10/128", namespace=self.namespace, status=self.active_status
        )

        self.device_ip_field = "primary_ip6"
