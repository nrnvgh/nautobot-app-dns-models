"""Test cases for nautobot_dns_models signals."""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.ipam.models import IPAddress, IPAddressToInterface, Namespace, Prefix
from nautobot.extras.models import Status, Role

from nautobot_dns_models.models import (
    AAAARecordModel,
    ARecordModel,
    DNSRule,
    DNSZoneModel,
    TXTRecordModel,
)


class TestInterfaceIPChanges(TestCase):
    """Test cases for interface IP change signal handling."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data that won't be modified during tests."""
        # Get statuses
        cls.active_status = Status.objects.get(name="Active")
        
        # Create a location type
        cls.location_type = LocationType.objects.create(name="Test Location Type")
        
        # Create a manufacturer and device type
        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_type = DeviceType.objects.create(
            manufacturer=cls.manufacturer,
            model="Test Model"
        )
        
        # Create a role
        device_ct = ContentType.objects.get_for_model(Device)
        cls.role = Role.objects.create(
            name="Test Role",
            color="ff0000"
        )
        cls.role.content_types.add(device_ct)
        
        # Create a zone
        cls.zone = DNSZoneModel.objects.create(
            name="test.example.com",
            filename="test.example.com",
            soa_mname="ns1.test.example.com",
            soa_rname="admin@test.example.com"
        )
        
        # Create namespace for IP addresses
        cls.namespace = Namespace.objects.get(name="Global")
        
        # Create prefixes for IP addresses
        cls.ipv4_prefix = Prefix.objects.create(
            prefix="192.0.2.0/24",
            namespace=cls.namespace,
            status=cls.active_status
        )
        cls.ipv6_prefix = Prefix.objects.create(
            prefix="2001:db8::/64",
            namespace=cls.namespace,
            status=cls.active_status
        )
        
        # Create some IP addresses
        cls.ipv4 = IPAddress.objects.create(
            address="192.0.2.1/24",
            namespace=cls.namespace,
            status=cls.active_status
        )
        cls.ipv6 = IPAddress.objects.create(
            address="2001:db8::1/64",
            namespace=cls.namespace,
            status=cls.active_status
        )

    def setUp(self):
        """Set up test data that might be modified during tests."""
        # Create a location
        self.location = Location.objects.create(
            name="Test Location",
            location_type=self.location_type,
            status=self.active_status
        )
        
        # Create a device
        self.device = Device.objects.create(
            name="test-device",
            device_type=self.device_type,
            role=self.role,
            location=self.location,
            status=self.active_status
        )
        
        # Create an interface
        self.interface = Interface.objects.create(
            device=self.device,
            name="eth0",
            type="1000base-t",
            status=self.active_status
        )

    def test_add_ip_to_interface(self):
        """Test adding an IP address to an interface."""
        # Create rule
        rule = DNSRule.objects.create(
            name="Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="test.example.com",
            name_template="{{ object.device.name }}.{{ object.name }}",
            value_template="{{ object.ip_addresses.first().id }}",
            record_type="A",
            ttl=300
        )
        
        # Add IP to interface
        self.interface.ip_addresses.add(self.ipv4)
        
        # Check that A record was created
        record = ARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(record.address, self.ipv4)
        self.assertEqual(record.ttl, 300)

    def test_remove_ip_from_interface(self):
        """Test removing an IP address from an interface."""
        # Create rule
        rule = DNSRule.objects.create(
            name="Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="test.example.com",
            name_template="{{ object.device.name }}.{{ object.name }}",
            value_template="{{ object.ip_addresses.first().id }}",
            record_type="A",
            ttl=300
        )
        
        # Add IP to interface
        self.interface.ip_addresses.add(self.ipv4)
        self.assertEqual(self.interface.ip_addresses.count(), 1)
        
        # Remove IP from interface
        self.interface.ip_addresses.remove(self.ipv4)
        
        # Check that A record was deleted
        self.assertFalse(
            ARecordModel.objects.filter(
                name="test-device.eth0",
                zone=self.zone
            ).exists()
        )

    def test_change_interface_ip(self):
        """Test changing an interface's IP address."""
        # Create rule
        rule = DNSRule.objects.create(
            name="Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="test.example.com",
            name_template="{{ object.device.name }}.{{ object.name }}",
            value_template="{{ object.ip_addresses.first().id }}",
            record_type="A",
            ttl=300
        )
        
        # Create another IPv4 address
        ipv4_2 = IPAddress.objects.create(
            address="192.0.2.2/24",
            namespace=self.namespace,
            status=self.active_status
        )
        
        # Add first IP
        self.interface.ip_addresses.set([self.ipv4])
        
        # Verify first record was created
        record1 = ARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(record1.address, self.ipv4)
        
        # Change to second IP (atomic operation)
        self.interface.ip_addresses.set([ipv4_2])
        
        # Check that old record was deleted
        self.assertFalse(
            ARecordModel.objects.filter(
                name="test-device.eth0",
                zone=self.zone,
                address=self.ipv4
            ).exists()
        )
        
        # Check that new record was created
        record2 = ARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(record2.address, ipv4_2)
        self.assertEqual(record2.ttl, 300)

    def test_invalid_zone(self):
        """Test behavior when zone doesn't exist."""
        # Create rule with non-existent zone
        rule = DNSRule.objects.create(
            name="Invalid Zone Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="nonexistent.example.com",
            name_template="{{ object.device.name }}.{{ object.name }}",
            value_template="Interface {{ object.name }} on device {{ object.device.name }}",
            record_type="TXT",
            ttl=300
        )
        
        # Add IP to interface
        self.interface.ip_addresses.add(self.ipv4)
        
        # Check that no record was created
        self.assertFalse(
            TXTRecordModel.objects.filter(
                name="test-device.eth0",
                zone__name="nonexistent.example.com"
            ).exists()
        )

    def test_missing_ip(self):
        """Test behavior when IP address doesn't exist."""
        # Create rule with non-existent IP
        rule = DNSRule.objects.create(
            name="Invalid IP Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="test.example.com",
            name_template="{{ object.device.name }}.{{ object.name }}",
            value_template="00000000-0000-0000-0000-000000000000",
            record_type="A",
            ttl=300
        )
        
        # Add IP to interface
        self.interface.ip_addresses.add(self.ipv4)
        
        # Check that no record was created
        self.assertFalse(
            ARecordModel.objects.filter(
                name="test-device.eth0",
                zone=self.zone
            ).exists()
        )

    def test_interface_ip_combinations(self):
        """Test various combinations of IPv4 and IPv6 addresses."""
        # Create rules for both record types
        a_rule = DNSRule.objects.create(
            name="A Record Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="test.example.com",
            name_template="{{ object.device.name }}.{{ object.name }}",
            value_template="{{ object.ip_addresses.filter(ip_version=4).first().id }}",
            record_type="A",
            ttl=300
        )
        aaaa_rule = DNSRule.objects.create(
            name="AAAA Record Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            zone_template="test.example.com",
            name_template="{{ object.device.name }}.{{ object.name }}",
            value_template="{{ object.ip_addresses.filter(ip_version=6).first().id }}",
            record_type="AAAA",
            ttl=300
        )
        
        # Create another IPv4 address
        ipv4_2 = IPAddress.objects.create(
            address="192.0.2.2/24",
            namespace=self.namespace,
            status=self.active_status
        )
        
        # Create another IPv6 address
        ipv6_2 = IPAddress.objects.create(
            address="2001:db8::2/64",
            namespace=self.namespace,
            status=self.active_status
        )
        
        # 1. Set both IPv4 and IPv6
        self.interface.ip_addresses.set([self.ipv4, self.ipv6])
        self.assertEqual(self.interface.ip_addresses.count(), 2)
        
        # Verify both records exist
        a_record = ARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone,
            address__ip_version=4
        )
        self.assertEqual(a_record.address, self.ipv4)
        
        aaaa_record = AAAARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone,
            address__ip_version=6
        )
        self.assertEqual(aaaa_record.address, self.ipv6)
        
        # 2. Change IPv4 while keeping IPv6
        self.interface.ip_addresses.set([ipv4_2, self.ipv6])
        self.assertEqual(self.interface.ip_addresses.count(), 2)
        
        # Verify IPv4 record changed, IPv6 unchanged
        a_record = ARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(a_record.address, ipv4_2)
        
        aaaa_record = AAAARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(aaaa_record.address, self.ipv6)
        
        # 3. Change IPv6 while keeping IPv4
        self.interface.ip_addresses.set([ipv4_2, ipv6_2])
        self.assertEqual(self.interface.ip_addresses.count(), 2)
        
        # Verify IPv6 record changed, IPv4 unchanged
        a_record = ARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(a_record.address, ipv4_2)
        
        aaaa_record = AAAARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(aaaa_record.address, ipv6_2)
        
        # 4. Remove IPv4, keep IPv6
        self.interface.ip_addresses.set([ipv6_2])
        self.assertEqual(self.interface.ip_addresses.count(), 1)
        
        # Verify IPv4 record deleted, IPv6 unchanged
        self.assertFalse(
            ARecordModel.objects.filter(
                name="test-device.eth0",
                zone=self.zone
            ).exists()
        )
        
        aaaa_record = AAAARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(aaaa_record.address, ipv6_2)
        
        # 5. Remove IPv6, keep IPv4
        self.interface.ip_addresses.set([ipv4_2])
        self.assertEqual(self.interface.ip_addresses.count(), 1)
        
        # Verify IPv6 record deleted, IPv4 unchanged
        self.assertFalse(
            AAAARecordModel.objects.filter(
                name="test-device.eth0",
                zone=self.zone
            ).exists()
        )
        
        a_record = ARecordModel.objects.get(
            name="test-device.eth0",
            zone=self.zone
        )
        self.assertEqual(a_record.address, ipv4_2)
        
        # 6. Remove both
        self.interface.ip_addresses.set([])
        self.assertEqual(self.interface.ip_addresses.count(), 0)
        
        # Verify both records deleted
        self.assertFalse(
            ARecordModel.objects.filter(
                name="test-device.eth0",
                zone=self.zone
            ).exists()
        )
        self.assertFalse(
            AAAARecordModel.objects.filter(
                name="test-device.eth0",
                zone=self.zone
            ).exists()
        ) 