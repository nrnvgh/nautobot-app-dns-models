"""Tests for DNS Jinja2 helper functions."""

from django.test import TestCase
from nautobot.extras.models import Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_dns_models.jinja_filters import ip_address


class JinjaHelpersTestCase(TestCase):
    """Test cases for DNS Jinja2 helper functions."""

    @classmethod
    def setUpTestData(cls):
        """Create test data for real IPAddress objects."""
        # Create namespace and prefix infrastructure for real IP addresses
        cls.namespace = Namespace.objects.create(name="Test Namespace")
        cls.prefix_v4 = Prefix.objects.create(
            prefix="192.168.1.0/24", namespace=cls.namespace, status=Status.objects.get_for_model(Prefix).first()
        )
        cls.prefix_v6 = Prefix.objects.create(
            prefix="2001:db8::/64", namespace=cls.namespace, status=Status.objects.get_for_model(Prefix).first()
        )

        # Create multiple IP addresses for collection testing (read-only usage)
        cls.ipv4_address_1 = IPAddress.objects.create(
            address="192.168.1.100/24", namespace=cls.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )
        cls.ipv4_address_2 = IPAddress.objects.create(
            address="192.168.1.101/24", namespace=cls.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )
        cls.ipv6_address_1 = IPAddress.objects.create(
            address="2001:db8::100/64", namespace=cls.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )
        cls.ipv6_address_2 = IPAddress.objects.create(
            address="2001:db8::101/64", namespace=cls.namespace, status=Status.objects.get_for_model(IPAddress).first()
        )

        # For backward compatibility with existing tests
        cls.ipv4_address = cls.ipv4_address_1
        cls.ipv6_address = cls.ipv6_address_1

    def test_ip_address_ipv4_object(self):
        """Test ip_address with IPv4 IPAddress object."""
        result = ip_address(self.ipv4_address)
        self.assertEqual(result, str(self.ipv4_address.id))

    def test_ip_address_ipv6_object(self):
        """Test ip_address with IPv6 IPAddress object."""
        result = ip_address(self.ipv6_address)
        self.assertEqual(result, str(self.ipv6_address.id))

    def test_ip_address_with_version_4_match(self):
        """Test ip_address with version=4 and IPv4 object."""
        result = ip_address(self.ipv4_address, 4)
        self.assertEqual(result, str(self.ipv4_address.id))

    def test_ip_address_with_version_6_match(self):
        """Test ip_address with version=6 and IPv6 object."""
        result = ip_address(self.ipv6_address, 6)
        self.assertEqual(result, str(self.ipv6_address.id))

    def test_ip_address_version_4_rejects_ipv6(self):
        """Test ip_address with version=4 rejects IPv6 objects."""
        with self.assertRaises(ValueError) as cm:
            ip_address(self.ipv6_address, 4)
        self.assertIn("IP address is IPv6, not IPv4", str(cm.exception))

    def test_ip_address_version_6_rejects_ipv4(self):
        """Test ip_address with version=6 rejects IPv4 objects."""
        with self.assertRaises(ValueError) as cm:
            ip_address(self.ipv4_address, 6)
        self.assertIn("IP address is IPv4, not IPv6", str(cm.exception))

    def test_ip_address_none_value(self):
        """Test ip_address with None value raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            ip_address(None)
        self.assertIn("Cannot extract IP address from None", str(cm.exception))

    def test_ip_address_invalid_version(self):
        """Test ip_address with invalid version parameter."""
        with self.assertRaises(ValueError) as cm:
            ip_address(self.ipv4_address, 5)
        self.assertIn("Invalid IP version: 5", str(cm.exception))

    def test_ip_address_any_version_accepts_both(self):
        """Test ip_address without version parameter accepts both IPv4 and IPv6."""
        # Test IPv4
        result_ipv4 = ip_address(self.ipv4_address)
        self.assertEqual(result_ipv4, str(self.ipv4_address.id))

        # Test IPv6
        result_ipv6 = ip_address(self.ipv6_address)
        self.assertEqual(result_ipv6, str(self.ipv6_address.id))

    def test_ip_address_multiple_ipv4_addresses(self):
        """Test ip_address with multiple IPv4 addresses returns space-delimited UUIDs."""
        # Get IPv4 addresses as QuerySet (Django test isolation ensures only our test data)
        ipv4_queryset = IPAddress.objects.filter(ip_version=4)

        result = ip_address(ipv4_queryset)

        # Should return space-delimited UUIDs
        expected_uuids = [str(self.ipv4_address_1.id), str(self.ipv4_address_2.id)]
        expected = " ".join(expected_uuids)

        self.assertEqual(result, expected)
        self.assertIn(" ", result, "Multiple IPs should be space-delimited")

        # Verify each UUID is present
        for uuid_str in expected_uuids:
            self.assertIn(uuid_str, result)

    def test_ip_address_multiple_ipv6_addresses(self):
        """Test ip_address with multiple IPv6 addresses returns space-delimited UUIDs."""
        # Get IPv6 addresses as QuerySet (Django test isolation ensures only our test data)
        ipv6_queryset = IPAddress.objects.filter(ip_version=6)

        result = ip_address(ipv6_queryset)

        # Should return space-delimited UUIDs
        expected_uuids = [str(self.ipv6_address_1.id), str(self.ipv6_address_2.id)]
        expected = " ".join(expected_uuids)

        self.assertEqual(result, expected)
        self.assertIn(" ", result, "Multiple IPs should be space-delimited")

        # Verify each UUID is present
        for uuid_str in expected_uuids:
            self.assertIn(uuid_str, result)
