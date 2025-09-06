
"""Test DnsZoneModel."""

from constance.test import override_config
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from nautobot.apps.testing import ModelTestCases, TestCase
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_dns_models.models import (
    AAAARecordModel,
    ARecordModel,
    CNAMERecordModel,
    DNSRule,
    DNSRuleComponent,
    DNSRuleRecord,
    DNSZoneModel,
    MXRecordModel,
    NSRecordModel,
    PTRRecordModel,
    SRVRecordModel,
    TXTRecordModel,
    dns_wire_label_length,
)
from nautobot_dns_models.tests import fixtures

# Helper for generating unicode labels of a specific IDNA-encoded length


def _make_unicode_label_with_idna_length(char, target_length):
    """Return a string of repeated `char` whose IDNA-encoded length is exactly `target_length` bytes."""
    label = ""
    while dns_wire_label_length(label) < target_length:
        label += char
    if dns_wire_label_length(label) > target_length:
        label = label[:-1]
    if dns_wire_label_length(label) != target_length:
        raise ValueError(f"Could not generate label of exactly {target_length} bytes in IDNA.")
    return label


class TestDnsZoneModel(ModelTestCases.BaseModelTestCase):
    """Test DnsZoneModel."""

    model = DNSZoneModel

    @classmethod
    def setUpTestData(cls):
        """Create test data for DnsZoneModel Model."""
        super().setUpTestData()
        # Create 3 objects for the model test cases.
        fixtures.create_dnszonemodel()

    def test_create_dnszonemodel_only_required(self):
        """Create with only required fields, and validate null description and __str__."""
        dnszonemodel = DNSZoneModel.objects.create(name="Development")
        self.assertEqual(dnszonemodel.name, "Development")
        self.assertEqual(dnszonemodel.description, "")
        self.assertEqual(str(dnszonemodel), "Development")

    def test_create_dnszonemodel_all_fields_success(self):
        """Create DnsZoneModel with all fields."""
        dnszonemodel = DNSZoneModel.objects.create(name="Development", description="Development Test")
        self.assertEqual(dnszonemodel.name, "Development")
        self.assertEqual(dnszonemodel.description, "Development Test")

    def test_get_absolute_url(self):
        dns_zone_model = DNSZoneModel(name="example.com")
        self.assertEqual(dns_zone_model.get_absolute_url(), f"/plugins/dns/dns-zones/{dns_zone_model.id}/")


class NSRecordModelTestCase(TestCase):
    """Test the NSRecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com")

    def test_create_nsrecordmodel(self):
        ns_record = NSRecordModel.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)

        self.assertEqual(ns_record.name, "primary")
        self.assertEqual(ns_record.server, "example-server.com.")
        self.assertEqual(str(ns_record), ns_record.name)

    def test_get_absolute_url(self):
        ns_record = NSRecordModel.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)
        self.assertEqual(ns_record.get_absolute_url(), f"/plugins/dns/ns-records/{ns_record.id}/")


class ARecordModelTestCase(TestCase):
    """Test the ARecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=status)
        # IPv6 Test data
        Prefix.objects.create(prefix="2001:db8:abcd:99::/64", namespace=namespace, type="Pool", status=status)
        cls.ipv6_address = IPAddress.objects.create(
            address="2001:db8:abcd:99::1/128", namespace=namespace, status=status
        )

    def test_create_arecordmodel(self):
        a_record = ARecordModel.objects.create(name="site.example.com", address=self.ip_address, zone=self.dns_zone)

        self.assertEqual(a_record.name, "site.example.com")
        self.assertEqual(a_record.address, self.ip_address)
        self.assertEqual(a_record.ttl, 3600)
        self.assertEqual(str(a_record), a_record.name)

    def test_create_ipv6_arecord_fails(self):
        # Test that creating an IPv6 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = ARecordModel(name="invalid.example.com", address=self.ipv6_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_get_absolute_url(self):
        a_record = ARecordModel.objects.create(name="site.example.com", address=self.ip_address, zone=self.dns_zone)
        self.assertEqual(a_record.get_absolute_url(), f"/plugins/dns/a-records/{a_record.id}/")


class AAAARecordModelTestCase(TestCase):
    """Test the AAAARecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="2001:db8:abcd:12::/64", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="2001:db8:abcd:12::1/128", namespace=namespace, status=status)
        # IPv4 Test Data
        Prefix.objects.create(prefix="10.1.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ipv4_address = IPAddress.objects.create(address="10.1.0.1/32", namespace=namespace, status=status)

    def test_create_aaaarecordmodel(self):
        aaaa_record = AAAARecordModel.objects.create(
            name="site.example.com", address=self.ip_address, zone=self.dns_zone
        )

        self.assertEqual(aaaa_record.name, "site.example.com")
        self.assertEqual(aaaa_record.address, self.ip_address)
        self.assertEqual(aaaa_record.ttl, 3600)
        self.assertEqual(str(aaaa_record), aaaa_record.name)

    def test_create_ipv4_aaaarecord_fails(self):
        # Test that creating an IPv4 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = AAAARecordModel(name="invalid.example.com", address=self.ipv4_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_get_absolute_url(self):
        aaaa_record = AAAARecordModel.objects.create(
            name="site.example.com", address=self.ip_address, zone=self.dns_zone
        )
        self.assertEqual(aaaa_record.get_absolute_url(), f"/plugins/dns/aaaa-records/{aaaa_record.id}/")


class CNAMERecordModelTestCase(TestCase):
    """Test the CNAMERecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com")

    def test_create_cnamerecordmodel(self):
        cname_record = CNAMERecordModel.objects.create(
            name="www.example.com", alias="site.example.com", zone=self.dns_zone
        )

        self.assertEqual(cname_record.name, "www.example.com")
        self.assertEqual(cname_record.alias, "site.example.com")
        self.assertEqual(str(cname_record), cname_record.name)

    def test_get_absolute_url(self):
        cname_record = CNAMERecordModel.objects.create(
            name="www.example.com", alias="site.example.com", zone=self.dns_zone
        )
        self.assertEqual(cname_record.get_absolute_url(), f"/plugins/dns/cname-records/{cname_record.id}/")


class MXRecordModelTestCase(TestCase):
    """Test the MXRecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com")

    def test_create_mxrecordmodel(self):
        mx_record = MXRecordModel.objects.create(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)

        self.assertEqual(mx_record.name, "mail-record")
        self.assertEqual(mx_record.preference, 10)
        self.assertEqual(mx_record.mail_server, "mail.example.com")
        self.assertEqual(str(mx_record), mx_record.name)

    def test_get_absolute_url(self):
        mx_record = MXRecordModel.objects.create(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)
        self.assertEqual(mx_record.get_absolute_url(), f"/plugins/dns/mx-records/{mx_record.id}/")


class TXTRecordModelTestCase(TestCase):
    """Test the TXTRecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com")

    def test_create_txtrecordmodel(self):
        txt_record = TXTRecordModel.objects.create(name="txt-record", text="spf-record", zone=self.dns_zone)

        self.assertEqual(txt_record.name, "txt-record")
        self.assertEqual(txt_record.text, "spf-record")
        self.assertEqual(str(txt_record), txt_record.name)

    def test_get_absolute_url(self):
        txt_record = TXTRecordModel.objects.create(name="txt-record", text="spf-record", zone=self.dns_zone)
        self.assertEqual(txt_record.get_absolute_url(), f"/plugins/dns/txt-records/{txt_record.id}/")


class PTRRecordModelTestCase(TestCase):
    """Test the PTRRecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com")

    def test_create_ptrrecordmodel(self):
        ptr_record = PTRRecordModel.objects.create(name="ptr-record", ptrdname="ptr-record", zone=self.dns_zone)

        self.assertEqual(ptr_record.ptrdname, "ptr-record")
        self.assertEqual(str(ptr_record), ptr_record.ptrdname)

    def test_get_absolute_url(self):
        ptr_record = PTRRecordModel.objects.create(ptrdname="ptr-record", zone=self.dns_zone)
        self.assertEqual(ptr_record.get_absolute_url(), f"/plugins/dns/ptr-records/{ptr_record.id}/")


class SRVRecordModelTestCase(TestCase):
    """Test the SRVRecordModel model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZoneModel.objects.create(name="example.com", ttl=7200)

    def test_create_srvrecordmodel(self):
        srv_record = SRVRecordModel.objects.create(
            name="_sip._tcp.example.com",
            priority=10,
            weight=5,
            port=5060,
            target="sip.example.com",
            zone=self.dns_zone,
            ttl=3600,
            description="SIP server",
            comment="Primary SIP server",
        )

        self.assertEqual(srv_record.name, "_sip._tcp.example.com")
        self.assertEqual(srv_record.priority, 10)
        self.assertEqual(srv_record.weight, 5)
        self.assertEqual(srv_record.port, 5060)
        self.assertEqual(srv_record.target, "sip.example.com")
        self.assertEqual(srv_record.ttl, 3600)
        self.assertEqual(srv_record.description, "SIP server")
        self.assertEqual(srv_record.comment, "Primary SIP server")
        self.assertEqual(str(srv_record), srv_record.name)

    def test_create_srvrecordmodel_wo_ttl(self):
        srv_record = SRVRecordModel.objects.create(
            name="_sip._tcp.example.com",
            priority=10,
            weight=5,
            port=5060,
            target="sip.example.com",
            zone=self.dns_zone,
            description="SIP server",
            comment="Primary SIP server",
        )

        self.assertEqual(srv_record.name, "_sip._tcp.example.com")
        self.assertEqual(srv_record.priority, 10)
        self.assertEqual(srv_record.weight, 5)
        self.assertEqual(srv_record.port, 5060)
        self.assertEqual(srv_record.target, "sip.example.com")
        self.assertEqual(srv_record.ttl, 7200)  # Inherits from DNSZoneModel
        self.assertEqual(srv_record.description, "SIP server")
        self.assertEqual(srv_record.comment, "Primary SIP server")
        self.assertEqual(str(srv_record), srv_record.name)

    def test_get_absolute_url(self):
        srv_record = SRVRecordModel.objects.create(
            name="_sip._tcp.example.com", priority=10, weight=5, port=5060, target="sip.example.com", zone=self.dns_zone
        )
        self.assertEqual(srv_record.get_absolute_url(), f"/plugins/dns/srv-records/{srv_record.id}/")


class DNSRecordNameLengthValidationTest(TestCase):
    """Test DNS record name validation rules from RFC 1035 §3.1."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZoneModel.objects.create(name="example.com")

    # ASCII Label Tests
    def test_accepts_valid_ascii_label(self):
        record = TXTRecordModel(name="www", text="test", zone=self.zone)
        record.full_clean()  # Should not raise
        record = TXTRecordModel(name="www.subdomain", text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_accepts_ascii_label_of_63_bytes(self):
        label_63 = "a" * 63
        record = TXTRecordModel(name=label_63, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_ascii_label_of_64_bytes(self):
        label_64 = "a" * 64
        record = TXTRecordModel(name=label_64, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            f"Label '{label_64}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Unicode Label Tests
    def test_accepts_valid_unicode_label(self):
        label = "ü"
        record = TXTRecordModel(name=label, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_accepts_unicode_label_of_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63)
        record = TXTRecordModel(name=label, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_unicode_label_exceeding_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63) + "ü"
        record = TXTRecordModel(name=label, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            f"Label '{label}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Enforcement Flag Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_label_exceeding_63_bytes_when_enforcement_disabled(self):
        record = TXTRecordModel(name="a" * 64, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_label_exceeding_63_bytes_when_enforcement_enabled(self):
        record = TXTRecordModel(name="a" * 64, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            "Label 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' exceeds the maximum length of 63 bytes (octets) in wire format",
            str(context.exception),
        )

    # FQDN Length Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_fqdn_exceeding_255_bytes_when_enforcement_disabled(self):
        zone = DNSZoneModel.objects.create(
            name="x" * 63, filename="x" * 63 + ".zone", soa_mname="ns1." + "x" * 63 + ".", soa_rname="admin@example.com"
        )
        record = TXTRecordModel(name="x" * 63 + "." + "x" * 63 + "." + "x" * 63, text="test", zone=zone)
        record.full_clean()  # Should not raise

    def test_rejects_fqdn_exceeding_255_bytes_when_enforcement_enabled(self):
        zone_label = "z" * 63
        zone = DNSZoneModel.objects.create(
            name=zone_label,
            filename=zone_label + ".zone",
            soa_mname="ns1." + zone_label + ".",
            soa_rname="admin@example.com",
        )
        record = TXTRecordModel(name="a" * 63 + "." + "b" * 63, text="test", zone=zone)
        record.full_clean()  # Should not raise
        record = TXTRecordModel(name="a" * 63 + "." + "b" * 63 + "." + "c" * 63, text="test", zone=zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            "Total length of DNS name cannot exceed 255 bytes (octets) in wire format", str(context.exception)
        )

    # Structure/Format Tests
    def test_rejects_empty_label(self):
        record = TXTRecordModel(name="www..subdomain", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

    def test_rejects_label_with_leading_or_trailing_dot(self):
        # Leading dot
        record = TXTRecordModel(name=".example", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))
        # Trailing dot
        record = TXTRecordModel(name="example.", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))


class DNSZoneNameLengthValidationTest(TestCase):
    """Test DNS zone name validation rules from RFC 1035 §3.1.

    Note: We don't test wire format length for zones because the model's CharField
    max_length=200 constraint is stricter than the DNS wire format limit of 255 octets.
    The wire format test is only needed for records, which can have longer names
    when combined with their zone.
    """

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZoneModel.objects.create(name="example.com")

    # ASCII Label Tests
    def test_accepts_valid_ascii_label(self):
        zone = DNSZoneModel(name="test1", filename="test1.zone", soa_mname="ns1.test1.", soa_rname="admin@example.com")
        zone.full_clean()  # Should not raise
        zone = DNSZoneModel(
            name="test2.example.com",
            filename="test2.example.com.zone",
            soa_mname="ns1.test2.example.com.",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_accepts_ascii_label_of_63_bytes(self):
        label_63 = "a" * 63
        zone = DNSZoneModel(
            name=label_63,
            filename=label_63 + ".zone",
            soa_mname="ns1." + label_63 + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_rejects_ascii_label_of_64_bytes(self):
        label_64 = "a" * 64
        zone = DNSZoneModel(
            name=label_64,
            filename=label_64 + ".zone",
            soa_mname="ns1." + label_64 + ".",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn(
            f"Label '{label_64}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Unicode Label Tests
    def test_accepts_valid_unicode_label(self):
        label = "ü"
        zone = DNSZoneModel(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_accepts_unicode_label_of_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63)
        zone = DNSZoneModel(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_rejects_unicode_label_exceeding_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63) + "ü"
        zone = DNSZoneModel(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn(
            f"Label '{label}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Enforcement Flag Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_label_exceeding_63_bytes_when_enforcement_disabled(self):
        zone = DNSZoneModel(
            name="a" * 64, filename="a" * 64 + ".zone", soa_mname="ns1." + "a" * 64 + ".", soa_rname="admin@example.com"
        )
        zone.full_clean()  # Should not raise

    def test_rejects_label_exceeding_63_bytes_when_enforcement_enabled(self):
        zone = DNSZoneModel(
            name="a" * 64, filename="a" * 64 + ".zone", soa_mname="ns1." + "a" * 64 + ".", soa_rname="admin@example.com"
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn(
            "Label 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' exceeds the maximum length of 63 bytes (octets) in wire format",
            str(context.exception),
        )

    # Structure/Format Tests
    def test_rejects_empty_label(self):
        zone = DNSZoneModel(
            name="example..com",
            filename="example..com.zone",
            soa_mname="ns1.example..com.",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

    def test_rejects_label_with_leading_or_trailing_dot(self):
        # Leading dot
        zone = DNSZoneModel(
            name=".example",
            filename=".example.zone",
            soa_mname="ns1..example.",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))
        # Trailing dot
        zone = DNSZoneModel(
            name="example.",
            filename="example..zone",
            soa_mname="ns1.example..",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))


# =============================================================================
# GUI Rule Builder Model Tests
# =============================================================================

class GUIDNSRuleTestCase(ModelTestCases.BaseModelTestCase):
    """Test GUI-based DNSRule model."""

    model = DNSRule

    @classmethod
    def setUpTestData(cls):
        """Create test data for GUI DNSRule tests."""
        super().setUpTestData()
        
        # Create test zone
        cls.zone = DNSZoneModel.objects.create(name="test.local")
        
        # Get content types
        cls.interface_content_type = ContentType.objects.get_for_model(Interface)
        cls.device_content_type = ContentType.objects.get_for_model(Device)
        cls.arecord_content_type = ContentType.objects.get_for_model(ARecordModel)
        cls.txtrecord_content_type = ContentType.objects.get_for_model(TXTRecordModel)
        
        # Create 3 DNSRule instances for BaseModelTestCase framework
        DNSRule.objects.create(
            name="Test Rule One",
            description="First test rule",
            enabled=True,
            content_type=cls.interface_content_type,
            record_type=cls.arecord_content_type,
            zone_source="fixed",
            zone_fixed=cls.zone,
        )
        DNSRule.objects.create(
            name="Test Rule Two", 
            description="Second test rule",
            enabled=True,
            content_type=cls.device_content_type,
            record_type=cls.txtrecord_content_type,
            zone_source="fixed",
            zone_fixed=cls.zone,
        )
        DNSRule.objects.create(
            name="Test Rule Three",
            description="Third test rule", 
            enabled=False,
            content_type=cls.interface_content_type,
            record_type=cls.arecord_content_type,
            zone_source="field_reference",
            zone_field_path="device.location.zone",
        )

    def test_create_basic_rule(self):
        """Test creating a basic GUI DNS rule."""
        rule = DNSRule.objects.create(
            name="Test Interface Rule",
            description="Creates A records for interfaces",
            enabled=True,
            content_type=self.interface_content_type,
            record_type=self.arecord_content_type,
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        self.assertEqual(rule.name, "Test Interface Rule")
        self.assertTrue(rule.enabled)
        self.assertEqual(rule.content_type, self.interface_content_type)
        self.assertEqual(rule.record_type, self.arecord_content_type)
        self.assertEqual(rule.zone_source, "fixed")
        self.assertEqual(rule.zone_fixed, self.zone)

    def test_zone_validation(self):
        """Test zone configuration validation."""
        # Test fixed zone requires zone_fixed
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="Bad Rule",
                content_type=self.interface_content_type,
                record_type=self.arecord_content_type,
                zone_source="fixed",
                zone_fixed=None,  # Missing required field
            )
            rule.full_clean()

        # Test field_reference requires zone_field_path
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="Bad Rule 2",
                content_type=self.interface_content_type,
                record_type=self.arecord_content_type,
                zone_source="field_reference",
                zone_field_path="",  # Missing required field
            )
            rule.full_clean()

        # Test custom_field requires zone_custom_field
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="Bad Rule 3",
                content_type=self.interface_content_type,
                record_type=self.arecord_content_type,
                zone_source="custom_field",
                zone_custom_field="",  # Missing required field
            )
            rule.full_clean()

    def test_get_zone_for_object_fixed(self):
        """Test fixed zone resolution."""
        rule = DNSRule.objects.create(
            name="Fixed Zone Rule",
            content_type=self.interface_content_type,
            record_type=self.arecord_content_type,
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        # Mock interface object - actual object doesn't matter for fixed zones
        mock_interface = Interface()
        resolved_zone = rule.get_zone_for_object(mock_interface)
        self.assertEqual(resolved_zone, self.zone)

    def test_record_type_constraint(self):
        """Test that record_type is properly constrained to DNS record models."""
        # Valid record type should work
        rule = DNSRule.objects.create(
            name="Valid Record Type",
            content_type=self.interface_content_type,
            record_type=self.arecord_content_type,  # Valid DNS record type
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        self.assertEqual(rule.record_type, self.arecord_content_type)

    def test_string_representation(self):
        """Test string representation includes zone info."""
        # Fixed zone
        rule = DNSRule.objects.create(
            name="Test Rule",
            content_type=self.interface_content_type,
            record_type=self.arecord_content_type,
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        str_repr = str(rule)
        self.assertIn("Test Rule", str_repr)
        self.assertIn("A Record", str_repr)
        self.assertIn("interface", str_repr)
        self.assertIn("test.local", str_repr)

        # Field reference zone
        rule2 = DNSRule.objects.create(
            name="Field Rule",
            content_type=self.device_content_type,
            record_type=self.txtrecord_content_type,
            zone_source="field_reference",
            zone_field_path="location.zone",
        )
        str_repr2 = str(rule2)
        self.assertIn("Field Rule", str_repr2)
        self.assertIn("TXT Record", str_repr2)
        self.assertIn("device", str_repr2)
        self.assertIn("location.zone", str_repr2)


class DNSRuleComponentTestCase(ModelTestCases.BaseModelTestCase):
    """Test GUI DNSRuleComponent model."""

    model = DNSRuleComponent

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSRuleComponent tests."""
        super().setUpTestData()
        
        # Create test zone and rule
        cls.zone = DNSZoneModel.objects.create(name="component.test")
        interface_ct = ContentType.objects.get_for_model(Interface)
        arecord_ct = ContentType.objects.get_for_model(ARecordModel)
        
        cls.rule = DNSRule.objects.create(
            name="Component Test Rule",
            content_type=interface_ct,
            record_type=arecord_ct,
            zone_source="fixed",
            zone_fixed=cls.zone,
        )
        
        # Create 3 DNSRuleComponent instances for BaseModelTestCase framework
        DNSRuleComponent.objects.create(
            rule=cls.rule,
            order=1,
            target_field="name",
            component_type="field_reference",
            field_path="device.name",
        )
        DNSRuleComponent.objects.create(
            rule=cls.rule,
            order=2,
            target_field="name",
            component_type="literal",
            literal_value=".example.com",
        )
        DNSRuleComponent.objects.create(
            rule=cls.rule,
            order=3,
            target_field="value",
            component_type="field_reference",
            field_path="ip_addresses.first",
            transform_function="normalize",
        )

    def test_create_field_reference_component(self):
        """Test creating field reference component."""
        # Create separate rule for this test
        test_rule = DNSRule.objects.create(
            name="Field Reference Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        component = DNSRuleComponent.objects.create(
            rule=test_rule,
            order=1,
            target_field="name",
            component_type="field_reference",
            field_path="device.name",
            transform_function="normalize",
        )
        
        self.assertEqual(component.rule, test_rule)
        self.assertEqual(component.order, 1)
        self.assertEqual(component.target_field, "name")
        self.assertEqual(component.component_type, "field_reference")
        self.assertEqual(component.field_path, "device.name")
        self.assertEqual(component.transform_function, "normalize")

    def test_create_literal_component(self):
        """Test creating literal component."""
        # Create separate rule for this test
        test_rule = DNSRule.objects.create(
            name="Literal Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        component = DNSRuleComponent.objects.create(
            rule=test_rule,
            order=1,
            target_field="name",
            component_type="literal",
            literal_value=".example.com",
        )
        
        self.assertEqual(component.component_type, "literal")
        self.assertEqual(component.literal_value, ".example.com")

    def test_component_validation(self):
        """Test component validation based on type."""
        # Create separate rule for validation tests
        validation_rule = DNSRule.objects.create(
            name="Validation Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        # Field reference requires field_path
        with self.assertRaises(ValidationError):
            component = DNSRuleComponent(
                rule=validation_rule,
                order=1,
                target_field="name",
                component_type="field_reference",
                field_path="",  # Missing required field
            )
            component.full_clean()

        # Literal requires literal_value
        with self.assertRaises(ValidationError):
            component = DNSRuleComponent(
                rule=validation_rule,
                order=2,
                target_field="name",
                component_type="literal",
                literal_value="",  # Missing required field
            )
            component.full_clean()

    def test_get_transform_choices(self):
        """Test dynamic transform choices generation."""
        choices = DNSRuleComponent.get_transform_choices()
        
        # Should have "No Transform" option
        choice_values = [choice[0] for choice in choices]
        choice_labels = [choice[1] for choice in choices]
        
        self.assertIn("", choice_values)  # Empty string for no transform
        self.assertIn("No Transform", choice_labels)
        
        # Should have registered transforms
        self.assertIn("normalize", choice_values)
        self.assertIn("replace_slashes", choice_values)

    def test_string_representation(self):
        """Test component string representation."""
        # Use existing field reference component from setup (order=1, device.name)
        # but update it to have normalize transform for this test
        component1 = DNSRuleComponent.objects.get(rule=self.rule, order=1)
        component1.transform_function = "normalize"
        component1.save()
        
        str_repr = str(component1)
        self.assertIn("Component Test Rule[1]", str_repr)
        self.assertIn("device.name", str_repr)
        self.assertIn("Record Name", str_repr)
        self.assertIn("Normalize", str_repr)

        # Create new literal component with different order and specific test value
        component2 = DNSRuleComponent.objects.create(
            rule=self.rule,
            order=30,  # Avoid conflict with setup data (1, 2, 3)
            target_field="value",
            component_type="literal",
            literal_value="test-value",
        )
        str_repr2 = str(component2)
        self.assertIn("Component Test Rule[30]", str_repr2)
        self.assertIn("'test-value'", str_repr2)
        self.assertIn("Record Value", str_repr2)

    def test_ordering_constraint(self):
        """Test unique ordering constraint within a rule."""
        # Create separate rule for this constraint test
        constraint_rule = DNSRule.objects.create(
            name="Constraint Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        # Create first component
        DNSRuleComponent.objects.create(
            rule=constraint_rule,
            order=1,
            target_field="name",
            component_type="literal",
            literal_value="first",
        )
        
        # Duplicate order should fail
        with self.assertRaises(IntegrityError):
            DNSRuleComponent.objects.create(
                rule=constraint_rule,
                order=1,  # Duplicate order on same rule
                target_field="name",
                component_type="literal",
                literal_value="second",
            )


class GUIDNSRuleRecordTestCase(ModelTestCases.BaseModelTestCase):
    """Test GUI DNSRuleRecord tracking model."""

    model = DNSRuleRecord

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSRuleRecord tests."""
        super().setUpTestData()
        
        # Create test zone
        cls.zone = DNSZoneModel.objects.create(name="record-test.local")
        
        # Create basic test objects manually
        cls.namespace = Namespace.objects.create(name="Test Namespace")
        cls.prefix_status = Status.objects.get_for_model(Prefix).first()
        cls.prefix = Prefix.objects.create(
            prefix="192.168.1.0/24",
            namespace=cls.namespace,
            status=cls.prefix_status,
        )
        
        cls.ip_status = Status.objects.get_for_model(IPAddress).first()
        cls.ip_address = IPAddress.objects.create(
            address="192.168.1.10/24",
            namespace=cls.namespace,
            parent=cls.prefix,
            status=cls.ip_status,
        )
        
        # Create test device and interface  
        cls.location_type = LocationType.objects.create(name="Building")
        cls.location_status = Status.objects.get_for_model(Location).first()
        cls.location = Location.objects.create(
            name="Test Building",
            location_type=cls.location_type,
            status=cls.location_status,
        )
        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_type = DeviceType.objects.create(
            manufacturer=cls.manufacturer,
            model="Test Switch",
        )
        cls.device_role = Role.objects.create(name="Test Switch Role") 
        cls.device_status = Status.objects.get_for_model(Device).first()
        
        cls.device = Device.objects.create(
            name="test-switch",
            device_type=cls.device_type,
            role=cls.device_role,
            status=cls.device_status,
            location=cls.location,
        )
        
        cls.interface_status = Status.objects.get_for_model(Interface).first()
        cls.interface = Interface.objects.create(
            name="eth0",
            device=cls.device,
            type="1000base-t",
            status=cls.interface_status,
        )
        
        # Create A record
        cls.a_record = ARecordModel.objects.create(
            name="test-interface.example.com",
            zone=cls.zone,
            address=cls.ip_address,
        )
        
        # Create GUI rule
        interface_ct = ContentType.objects.get_for_model(Interface)
        arecord_ct = ContentType.objects.get_for_model(ARecordModel)
        
        cls.gui_rule = DNSRule.objects.create(
            name="GUI Test Rule",
            content_type=interface_ct,
            record_type=arecord_ct,
            zone_source="fixed",
            zone_fixed=cls.zone,
        )
        
        # Create 3 DNSRuleRecord instances for BaseModelTestCase framework
        DNSRuleRecord.objects.create(
            rule=cls.gui_rule,
            source_object=cls.device,
            dns_record_object_id=cls.a_record.id,
        )
        DNSRuleRecord.objects.create(
            rule=cls.gui_rule,
            source_object=cls.interface,
            dns_record_object_id=cls.a_record.id,
        )
        # Create another A record for the third instance
        a_record2 = ARecordModel.objects.create(
            name="test-interface2.example.com",
            zone=cls.zone,
            address=cls.ip_address,
        )
        DNSRuleRecord.objects.create(
            rule=cls.gui_rule,
            source_object=cls.device,
            dns_record_object_id=a_record2.id,
        )

    def test_create_tracking_record(self):
        """Test creating a rule record tracking entry."""
        # Create separate rule for this test
        test_rule = DNSRule.objects.create(
            name="Tracking Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        rule_record = DNSRuleRecord.objects.create(
            rule=test_rule,
            source_object=self.interface,
            dns_record_object_id=self.a_record.id,
        )
        
        self.assertEqual(rule_record.rule, test_rule)
        self.assertEqual(rule_record.source_object, self.interface)
        self.assertEqual(rule_record.dns_record_object_id, self.a_record.id)

    def test_dns_record_content_type_property(self):
        """Test dns_record_content_type property derives from rule."""
        # Create separate rule for this test
        property_rule = DNSRule.objects.create(
            name="Property Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        rule_record = DNSRuleRecord.objects.create(
            rule=property_rule,
            source_object=self.interface,
            dns_record_object_id=self.a_record.id,
        )
        
        # Should get content type from rule.record_type
        self.assertEqual(rule_record.dns_record_content_type, property_rule.record_type)

    def test_dns_record_object_property(self):
        """Test dns_record_object property fetches actual record."""
        # Create separate rule for this test
        object_rule = DNSRule.objects.create(
            name="Object Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        rule_record = DNSRuleRecord.objects.create(
            rule=object_rule,
            source_object=self.interface,
            dns_record_object_id=self.a_record.id,
        )
        
        # Should fetch the actual A record
        self.assertEqual(rule_record.dns_record_object, self.a_record)

    def test_string_representation(self):
        """Test rule record string representation."""
        # Create separate rule for this test
        string_rule = DNSRule.objects.create(
            name="String Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        rule_record = DNSRuleRecord.objects.create(
            rule=string_rule,
            source_object=self.interface,
            dns_record_object_id=self.a_record.id,
        )
        
        str_repr = str(rule_record)
        self.assertIn("String Test Rule", str_repr)
        self.assertIn(str(self.interface), str_repr)
        self.assertIn(str(self.a_record), str_repr)

    def test_cascade_deletion(self):
        """Test cascade deletion behavior."""
        # Create separate rule for this test
        cascade_rule = DNSRule.objects.create(
            name="Cascade Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        rule_record = DNSRuleRecord.objects.create(
            rule=cascade_rule,
            source_object=self.interface,
            dns_record_object_id=self.a_record.id,
        )
        
        # Deleting rule should delete tracking record
        rule_id = cascade_rule.id
        cascade_rule.delete()
        
        with self.assertRaises(DNSRuleRecord.DoesNotExist):
            DNSRuleRecord.objects.get(rule_id=rule_id)

    def test_unique_constraint(self):
        """Test unique constraint on rule + source + dns_record."""
        # Create separate rule for this constraint test
        constraint_rule = DNSRule.objects.create(
            name="Constraint Test Rule",
            content_type=ContentType.objects.get_for_model(Interface),
            record_type=ContentType.objects.get_for_model(ARecordModel),
            zone_source="fixed",
            zone_fixed=self.zone,
        )
        
        # Create first tracking record
        DNSRuleRecord.objects.create(
            rule=constraint_rule,
            source_object=self.interface,
            dns_record_object_id=self.a_record.id,
        )
        
        # Duplicate should fail
        with self.assertRaises(IntegrityError):
            DNSRuleRecord.objects.create(
                rule=constraint_rule,
                source_object=self.interface,
                dns_record_object_id=self.a_record.id,
            )


