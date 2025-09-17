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
            prefix="192.168.1.0/24",
            namespace=cls.namespace,
            status=Status.objects.get_for_model(Prefix).first()
        )
        cls.prefix_v6 = Prefix.objects.create(
            prefix="2001:db8::/64",
            namespace=cls.namespace,
            status=Status.objects.get_for_model(Prefix).first()
        )
        
        # Create shared IP addresses for tests (read-only usage)
        cls.ipv4_address = IPAddress.objects.create(
            address="192.168.1.100/32",
            namespace=cls.namespace,
            status=Status.objects.get_for_model(IPAddress).first()
        )
        cls.ipv6_address = IPAddress.objects.create(
            address="2001:db8::100/128",
            namespace=cls.namespace,
            status=Status.objects.get_for_model(IPAddress).first()
        )

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
