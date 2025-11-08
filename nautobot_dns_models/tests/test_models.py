"""Test DNS Models (DNS zones, records, and rules)."""
# pylint: disable=too-many-lines

from unittest import skip

from constance.test import override_config
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from nautobot.apps.models import BaseModel
from nautobot.apps.testing import ModelTestCases, TestCase
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_dns_models.choices import DNSRecordTypeChoices
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CNAMERecord,
    DNSRule,
    DNSRuleRecord,
    DNSView,
    DNSViewPrefixAssignment,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
    dns_wire_label_length,
)

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


class RecordNameNormalizationMixin:
    """
    Mixin for testing record normalization.

    This mixin is used to test that the record name is normalized when the constance config is set to True and
    that the record fails validation when the constance config is set to False.

    It expected the following attributes to be set:
    - model: The model to test
    - normalization_data: A list of dictionaries, each containing the following keys:
        - name: The name of the record to create
        - expected_name: The expected normalized name
        - other keys are the fields of the model to create the record with

    TODO: allow tests with all good data to be used for both tests; currently, the second test
    TODO: will fail if the name doesn't require normalization.
    """

    model = None

    @classmethod
    def _strip_expected(cls, normalization_data: dict) -> tuple[str, dict]:
        expected_name = normalization_data["expected_name"]
        payload = {k: v for k, v in normalization_data.items() if k != "expected_name"}
        return expected_name, payload

    @override_config(nautobot_dns_models__NORMALIZE_DNS_RECORDS=True)
    def test_record_name_normalized_on_save_with_constance_config_normalize_true(self):
        """Record.name should be normalized when the constance config is set to True."""

        for normalization_data in self.normalization_data:
            with self.subTest(normalization_data=normalization_data):
                expected_name, record_create_data = self._strip_expected(normalization_data)
                record = self.model(**record_create_data)  # pylint: disable=not-callable
                record.full_clean()

                self.assertEqual(record.name, expected_name)

    @override_config(nautobot_dns_models__NORMALIZE_DNS_RECORDS=False)
    def test_record_fails_validation_on_save_with_constance_config_normalize_false(self):
        """Invalid record.name values should fail validation when the constance config is set to False."""

        for normalization_data in self.normalization_data:
            _, record_create_data = self._strip_expected(normalization_data)
            record = self.model(**record_create_data)  # pylint: disable=not-callable
            with self.assertRaises(ValidationError) as context:
                record.full_clean()

            self.assertIn(
                "Field is not normalized.",
                str(context.exception),
            )


class TestDNSView(ModelTestCases.BaseModelTestCase):
    """Test DNSView model."""

    model = DNSView

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSView Model."""
        super().setUpTestData()
        # Create 3 objects for the model test cases.
        DNSView.objects.create(name="View 1", description="First DNS View")
        DNSView.objects.create(name="View 2", description="Second DNS View")
        DNSView.objects.create(name="View 3", description="Third DNS View")

    def test_create_dnsview_only_required(self):
        """Create with only required fields, and validate null description and __str__."""
        dnsview = DNSView.objects.create(name="Test View")
        self.assertEqual(dnsview.name, "Test View")
        self.assertEqual(dnsview.description, "")
        self.assertEqual(str(dnsview), "Test View")

    def test_create_dnsview_all_fields_success(self):
        """Create DNSViewModel with all fields."""
        dnsview = DNSView.objects.create(name="Test View", description="Test Description")
        self.assertEqual(dnsview.name, "Test View")
        self.assertEqual(dnsview.description, "Test Description")

    def test_get_absolute_url(self):
        dns_view_model = DNSView.objects.get(name="View 1")
        self.assertEqual(dns_view_model.get_absolute_url(), f"/plugins/dns/dns-views/{dns_view_model.id}/")


class TestDNSViewPrefixAssignment(ModelTestCases.BaseModelTestCase):
    """Test DNSViewPrefixAssignment model."""

    model = DNSViewPrefixAssignment

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSViewPrefixAssignment Model."""
        super().setUpTestData()
        # Create Prefixes
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        cls.prefixes = (
            Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, status=status),
            Prefix.objects.create(prefix="2001:db8:abcd:99::/64", namespace=namespace, status=status),
        )
        # Create DNS Views
        cls.dns_views = (
            DNSView.objects.create(name="View 1", description="First DNS View"),
            DNSView.objects.create(name="View 2", description="Second DNS View"),
        )

        # Create DNSViewPrefixAssignment
        DNSViewPrefixAssignment.objects.create(dns_view=cls.dns_views[0], prefix=cls.prefixes[0])

    def test_create_dnsviewprefixassignment(self):
        """Create DNSViewPrefixAssignment with all fields."""
        assignment = DNSViewPrefixAssignment.objects.create(dns_view=self.dns_views[1], prefix=self.prefixes[1])
        self.assertEqual(assignment.dns_view, self.dns_views[1])
        self.assertEqual(assignment.prefix, self.prefixes[1])


class TestDnsZone(ModelTestCases.BaseModelTestCase):
    """Test DNSZone."""

    model = DNSZone

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSZone Model."""
        super().setUpTestData()
        # Create 3 objects for the model test cases.
        DNSZone.objects.create(name="Test One")
        DNSZone.objects.create(name="Test Two")
        DNSZone.objects.create(name="Test Three")

    def test_create_dnszone_only_required(self):
        """Create with only required fields, and validate null description and __str__."""
        dnszone = DNSZone.objects.create(name="Development")
        self.assertEqual(dnszone.name, "Development")
        self.assertEqual(dnszone.description, "")
        self.assertEqual(str(dnszone), "Development")

    def test_create_dnszone_all_fields_success(self):
        """Create DNSZone with all fields."""
        dnszone = DNSZone.objects.create(name="Development", description="Development Test")
        self.assertEqual(dnszone.name, "Development")
        self.assertEqual(dnszone.description, "Development Test")

    def test_get_absolute_url(self):
        dns_zone_model = DNSZone.objects.create(name="example.com")
        self.assertEqual(dns_zone_model.get_absolute_url(), f"/plugins/dns/dns-zones/{dns_zone_model.id}/")


class NSRecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the NSRecord model."""

    model = NSRecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.normalization_data = [
            {
                "name": "Primary",
                "expected_name": "primary",
                "server": "example-server.com.",
                "zone": cls.dns_zone,
            },
            {
                "name": "Primary.Name",
                "expected_name": "primary.name",
                "server": "example-server.com.",
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "server": "example-server.com.",
                "zone": cls.dns_zone,
            },
        ]

    def test_create_nsrecord(self):
        ns_record = NSRecord.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)

        self.assertEqual(ns_record.name, "primary")
        self.assertEqual(ns_record.server, "example-server.com.")
        self.assertEqual(str(ns_record), ns_record.name)

    def test_get_absolute_url(self):
        ns_record = NSRecord.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)
        self.assertEqual(ns_record.get_absolute_url(), f"/plugins/dns/ns-records/{ns_record.id}/")


class ARecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the ARecord model."""

    model = ARecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=status)
        # IPv6 Test data
        Prefix.objects.create(prefix="2001:db8:abcd:99::/64", namespace=namespace, type="Pool", status=status)
        cls.ipv6_address = IPAddress.objects.create(
            address="2001:db8:abcd:99::1/128", namespace=namespace, status=status
        )

        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "expected_name": "web-app-01",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
            },
            {
                "name": "Web/ App _01.Name",
                "expected_name": "web-app-01.name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
            },
        ]

    def test_create_arecord(self):
        a_record = ARecord(name="site.example.com", address=self.ip_address, zone=self.dns_zone)
        a_record.validated_save()

        self.assertEqual(a_record.name, "site.example.com")
        self.assertEqual(a_record.address, self.ip_address)
        self.assertEqual(a_record.ttl, 3600)
        self.assertEqual(str(a_record), a_record.name)

    def test_create_ipv6_arecord_fails(self):
        # Test that creating an IPv6 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = ARecord(name="invalid.example.com", address=self.ipv6_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_create_ipv6_arecord_fails_on_save(self):
        """Creating via ORM should also fail due to save() calling clean()."""
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="invalid-save.example.com", address=self.ipv6_address, zone=self.dns_zone)

    def test_get_absolute_url(self):
        a_record = ARecord.objects.create(name="site.example.com", address=self.ip_address, zone=self.dns_zone)
        self.assertEqual(a_record.get_absolute_url(), f"/plugins/dns/a-records/{a_record.id}/")


class AAAARecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the AAAARecord model."""

    model = AAAARecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="2001:db8:abcd:12::/64", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="2001:db8:abcd:12::1/128", namespace=namespace, status=status)
        # IPv4 Test Data
        Prefix.objects.create(prefix="10.1.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ipv4_address = IPAddress.objects.create(address="10.1.0.1/32", namespace=namespace, status=status)

        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "expected_name": "web-app-01",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
            },
            {
                "name": "Web/ App _01.Name",
                "expected_name": "web-app-01.name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
            },
        ]

    def test_create_aaaarecord(self):
        aaaa_record = AAAARecord(name="site.example.com", address=self.ip_address, zone=self.dns_zone)
        aaaa_record.validated_save()

        self.assertEqual(aaaa_record.name, "site.example.com")
        self.assertEqual(aaaa_record.address, self.ip_address)
        self.assertEqual(aaaa_record.ttl, 3600)
        self.assertEqual(str(aaaa_record), aaaa_record.name)

    def test_create_ipv4_aaaarecord_fails(self):
        # Test that creating an IPv4 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = AAAARecord(name="invalid.example.com", address=self.ipv4_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_create_ipv4_aaaarecord_fails_on_save(self):
        """Creating via ORM should also fail due to save() calling clean()."""
        with self.assertRaises(ValidationError):
            AAAARecord.objects.create(
                name="invalid-save.example.com",
                address=self.ipv4_address,
                zone=self.dns_zone,
            )

    def test_get_absolute_url(self):
        aaaa_record = AAAARecord.objects.create(name="site.example.com", address=self.ip_address, zone=self.dns_zone)
        self.assertEqual(aaaa_record.get_absolute_url(), f"/plugins/dns/aaaa-records/{aaaa_record.id}/")


class CNAMERecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the CNAMERecord model."""

    model = CNAMERecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "expected_name": "web-app-01",
                "alias": "alias.example.com",
                "zone": cls.dns_zone,
            },
            {
                "name": "Web/ App _01.Name",
                "expected_name": "web-app-01.name",
                "alias": "alias.example.com",
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "alias": "alias.example.com",
                "zone": cls.dns_zone,
            },
        ]

    def test_create_cnamerecord(self):
        cname_record = CNAMERecord(name="www.example.com", alias="site.example.com", zone=self.dns_zone)
        cname_record.validated_save()

        self.assertEqual(cname_record.name, "www.example.com")
        self.assertEqual(cname_record.alias, "site.example.com")
        self.assertEqual(str(cname_record), cname_record.name)

    def test_get_absolute_url(self):
        cname_record = CNAMERecord.objects.create(name="www.example.com", alias="site.example.com", zone=self.dns_zone)
        self.assertEqual(cname_record.get_absolute_url(), f"/plugins/dns/cname-records/{cname_record.id}/")


class MXRecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the MXRecord model."""

    model = MXRecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.normalization_data = [
            {
                "name": "Mail/ App _01",
                "expected_name": "mail-app-01",
                "mail_server": "mail.example.com",
                "preference": 10,
                "zone": cls.dns_zone,
            },
            {
                "name": "mail-record.Name",
                "expected_name": "mail-record.name",
                "mail_server": "mail.example.com",
                "preference": 10,
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "mail_server": "mail.example.com",
                "preference": 10,
                "zone": cls.dns_zone,
            },
        ]

    def test_create_mxrecord(self):
        mx_record = MXRecord(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)
        mx_record.validated_save()

        self.assertEqual(mx_record.name, "mail-record")
        self.assertEqual(mx_record.preference, 10)
        self.assertEqual(mx_record.mail_server, "mail.example.com")
        self.assertEqual(str(mx_record), mx_record.name)

    def test_get_absolute_url(self):
        mx_record = MXRecord.objects.create(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)
        self.assertEqual(mx_record.get_absolute_url(), f"/plugins/dns/mx-records/{mx_record.id}/")


class TXTRecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the TXTRecord model."""

    model = TXTRecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.normalization_data = [
            {
                "name": "Txt/ App _01",
                "expected_name": "txt-app-01",
                "text": "spf-record",
                "zone": cls.dns_zone,
            },
            {
                "name": "Txt/ App _01.Name",
                "expected_name": "txt-app-01.name",
                "text": "spf-record",
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "text": "spf-record",
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "text": "spf-record with spaces",
                "zone": cls.dns_zone,
            },
        ]

    def test_create_txtrecord(self):
        txt_record = TXTRecord(name="txt-record", text="spf-record", zone=self.dns_zone)
        txt_record.validated_save()

        self.assertEqual(txt_record.name, "txt-record")
        self.assertEqual(txt_record.text, "spf-record")
        self.assertEqual(str(txt_record), txt_record.name)

    def test_get_absolute_url(self):
        txt_record = TXTRecord.objects.create(name="txt-record", text="spf-record", zone=self.dns_zone)
        self.assertEqual(txt_record.get_absolute_url(), f"/plugins/dns/txt-records/{txt_record.id}/")


class PTRRecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the PTRRecord model."""

    model = PTRRecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.normalization_data = [
            {
                "name": "Ptr/ App _01",
                "expected_name": "ptr-app-01",
                "ptrdname": "ptr-record",
                "zone": cls.dns_zone,
            },
            {
                "name": "Ptr/ App _01.Name",
                "expected_name": "ptr-app-01.name",
                "ptrdname": "ptr-record",
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "ptrdname": "ptr-record",
                "zone": cls.dns_zone,
            },
        ]

    def test_create_ptrrecord(self):
        ptr_record = PTRRecord(name="ptr-record", ptrdname="ptr-record", zone=self.dns_zone)
        ptr_record.validated_save()

        self.assertEqual(ptr_record.ptrdname, "ptr-record")
        self.assertEqual(str(ptr_record), ptr_record.ptrdname)

    def test_get_absolute_url(self):
        ptr_record = PTRRecord.objects.create(ptrdname="ptr-record", zone=self.dns_zone)
        self.assertEqual(ptr_record.get_absolute_url(), f"/plugins/dns/ptr-records/{ptr_record.id}/")


class SRVRecordTestCase(RecordNameNormalizationMixin, TestCase):
    """Test the SRVRecord model."""

    model = SRVRecord

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com", ttl=7200)
        cls.normalization_data = [
            {
                "name": "Sip/ App _01",
                "expected_name": "sip-app-01",
                "priority": 10,
                "weight": 5,
                "port": 5060,
                "target": "sip.example.com",
                "zone": cls.dns_zone,
            },
            {
                "name": "Sip/ App _01.Name",
                "expected_name": "sip-app-01.name",
                "priority": 10,
                "weight": 5,
                "port": 5060,
                "target": "sip.example.com",
                "zone": cls.dns_zone,
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "expected_name": "foo-bar-baz.quux.name",
                "priority": 10,
                "weight": 5,
                "port": 5060,
                "target": "sip.example.com",
                "zone": cls.dns_zone,
            },
        ]

    def test_create_srvrecord(self):
        srv_record = SRVRecord(
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
        srv_record.validated_save()

        self.assertEqual(srv_record.name, "_sip._tcp.example.com")
        self.assertEqual(srv_record.priority, 10)
        self.assertEqual(srv_record.weight, 5)
        self.assertEqual(srv_record.port, 5060)
        self.assertEqual(srv_record.target, "sip.example.com")
        self.assertEqual(srv_record.ttl, 3600)
        self.assertEqual(srv_record.description, "SIP server")
        self.assertEqual(srv_record.comment, "Primary SIP server")
        self.assertEqual(str(srv_record), srv_record.name)

    def test_create_srvrecord_wo_ttl(self):
        srv_record = SRVRecord(
            name="_sip._tcp.example.com",
            priority=10,
            weight=5,
            port=5060,
            target="sip.example.com",
            zone=self.dns_zone,
            description="SIP server",
            comment="Primary SIP server",
        )
        srv_record.validated_save()

        self.assertEqual(srv_record.name, "_sip._tcp.example.com")
        self.assertEqual(srv_record.priority, 10)
        self.assertEqual(srv_record.weight, 5)
        self.assertEqual(srv_record.port, 5060)
        self.assertEqual(srv_record.target, "sip.example.com")
        self.assertEqual(srv_record.ttl, 7200)  # Inherits from DNSZone
        self.assertEqual(srv_record.description, "SIP server")
        self.assertEqual(srv_record.comment, "Primary SIP server")
        self.assertEqual(str(srv_record), srv_record.name)

    def test_get_absolute_url(self):
        srv_record = SRVRecord.objects.create(
            name="_sip._tcp.example.com", priority=10, weight=5, port=5060, target="sip.example.com", zone=self.dns_zone
        )
        self.assertEqual(srv_record.get_absolute_url(), f"/plugins/dns/srv-records/{srv_record.id}/")


class DNSRecordNameLengthValidationTest(TestCase):
    """Test DNS record name validation rules from RFC 1035 §3.1."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(name="example.com")

    # ASCII Label Tests
    def test_accepts_valid_ascii_label(self):
        record = TXTRecord(name="www", text="test", zone=self.zone)
        record.full_clean()  # Should not raise
        record = TXTRecord(name="www.subdomain", text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_accepts_ascii_label_of_63_bytes(self):
        label_63 = "a" * 63
        record = TXTRecord(name=label_63, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_ascii_label_of_64_bytes(self):
        label_64 = "a" * 64
        record = TXTRecord(name=label_64, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            f"Label '{label_64}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Unicode Label Tests
    def test_accepts_valid_unicode_label(self):
        label = "ü"
        record = TXTRecord(name=label, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_accepts_unicode_label_of_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63)
        record = TXTRecord(name=label, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_unicode_label_exceeding_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63) + "ü"
        record = TXTRecord(name=label, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            f"Label '{label}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Enforcement Flag Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_label_exceeding_63_bytes_when_enforcement_disabled(self):
        record = TXTRecord(name="a" * 64, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL="wire-format")
    def test_rejects_label_exceeding_63_bytes_when_enforcement_enabled(self):
        record = TXTRecord(name="a" * 64, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            "Label 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' exceeds the maximum length of 63 bytes (octets) in wire format",
            str(context.exception),
        )

    # FQDN Length Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_fqdn_exceeding_255_bytes_when_enforcement_disabled(self):
        zone = DNSZone.objects.create(
            name="x" * 63, filename="x" * 63 + ".zone", soa_mname="ns1." + "x" * 63 + ".", soa_rname="admin@example.com"
        )
        record = TXTRecord(name="x" * 63 + "." + "x" * 63 + "." + "x" * 63, text="test", zone=zone)
        record.full_clean()  # Should not raise

    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL="wire-format")
    def test_rejects_fqdn_exceeding_255_bytes_when_enforcement_enabled(self):
        zone_label = "z" * 63
        zone = DNSZone.objects.create(
            name=zone_label,
            filename=zone_label + ".zone",
            soa_mname="ns1." + zone_label + ".",
            soa_rname="admin@example.com",
        )
        record = TXTRecord(name="a" * 63 + "." + "b" * 63, text="test", zone=zone)
        record.full_clean()  # Should not raise
        record = TXTRecord(name="a" * 63 + "." + "b" * 63 + "." + "c" * 63, text="test", zone=zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            "Total length of DNS name cannot exceed 255 bytes (octets) in wire format", str(context.exception)
        )

    # Structure/Format Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL="wire-format")
    def test_rejects_empty_label(self):
        record = TXTRecord(name="www..subdomain", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL="wire-format")
    def test_rejects_label_with_leading_or_trailing_dot(self):
        # Leading dot
        record = TXTRecord(name=".example", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))
        # Trailing dot
        record = TXTRecord(name="example.", text="test", zone=self.zone)
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
        cls.zone = DNSZone.objects.create(name="example.com")

    # ASCII Label Tests
    def test_accepts_valid_ascii_label(self):
        zone = DNSZone(name="test1", filename="test1.zone", soa_mname="ns1.test1.", soa_rname="admin@example.com")
        zone.full_clean()  # Should not raise
        zone = DNSZone(
            name="test2.example.com",
            filename="test2.example.com.zone",
            soa_mname="ns1.test2.example.com.",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_accepts_ascii_label_of_63_bytes(self):
        label_63 = "a" * 63
        zone = DNSZone(
            name=label_63,
            filename=label_63 + ".zone",
            soa_mname="ns1." + label_63 + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_rejects_ascii_label_of_64_bytes(self):
        label_64 = "a" * 64
        zone = DNSZone(
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
        zone = DNSZone(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_accepts_unicode_label_of_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63)
        zone = DNSZone(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_rejects_unicode_label_exceeding_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63) + "ü"
        zone = DNSZone(
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
        zone = DNSZone(
            name="a" * 64, filename="a" * 64 + ".zone", soa_mname="ns1." + "a" * 64 + ".", soa_rname="admin@example.com"
        )
        zone.full_clean()  # Should not raise

    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL="wire-format")
    def test_rejects_label_exceeding_63_bytes_when_enforcement_enabled(self):
        zone = DNSZone(
            name="a" * 64, filename="a" * 64 + ".zone", soa_mname="ns1." + "a" * 64 + ".", soa_rname="admin@example.com"
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn(
            "Label 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' exceeds the maximum length of 63 bytes (octets) in wire format",
            str(context.exception),
        )

    # Structure/Format Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL="wire-format")
    def test_rejects_empty_label(self):
        zone = DNSZone(
            name="example..com",
            filename="example..com.zone",
            soa_mname="ns1.example..com.",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL="wire-format")
    def test_rejects_label_with_leading_or_trailing_dot(self):
        # Leading dot
        zone = DNSZone(
            name=".example",
            filename=".example.zone",
            soa_mname="ns1..example.",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

        # Trailing dot
        zone = DNSZone(
            name="example.",
            filename="example..zone",
            soa_mname="ns1.example..",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))


class DNSRuleTestCase(ModelTestCases.BaseModelTestCase):
    """Test the DNSRule model."""

    model = DNSRule

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSRule model."""
        super().setUpTestData()
        # Create required objects
        cls.content_type_device = ContentType.objects.get_for_model(Device)
        cls.content_type_interface = ContentType.objects.get_for_model(Interface)

        # Create sample Device for template validation
        # (DNSRule.clean() needs at least one Device object to test templates against)

        # Create minimal infrastructure for Device
        location_type = LocationType.objects.create(name="Test Location Type")
        location_type.content_types.add(cls.content_type_device)

        cls.location = Location.objects.create(
            name="Test Location",
            location_type=location_type,
            status=Status.objects.get_for_model(Location).first(),
        )

        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_type = DeviceType.objects.create(
            manufacturer=cls.manufacturer,
            model="Test Device Type",
        )

        device_role = Role.objects.create(name="Test Device Role")
        device_role.content_types.add(cls.content_type_device)

        # Create sample Device for template validation
        cls.device = Device.objects.create(
            name="test-device",
            device_type=cls.device_type,
            location=cls.location,
            role=device_role,
            status=Status.objects.get_for_model(Device).first(),
        )

        # Create minimal rule for BaseModelTestCase (needs at least one object)
        # Use location-scoped rule to avoid conflicts with individual test cases
        DNSRule.objects.create(
            name="base-test-rule",
            description="Base test rule for BaseModelTestCase",
            enabled=True,
            content_type=cls.content_type_interface,  # Use Interface to avoid Device conflicts
            location=cls.location,  # Location-scoped to avoid global conflicts
            zone_template="base-test.com",
            record_type="CNAME",  # Use CNAME to avoid A/AAAA conflicts
            name_template="{{ obj.name }}",
            value_template="base.example.com",
        )

    def test_dnsrule_for_a_record(self):
        """Test DNSRule configured for A record type."""
        rule = DNSRule.objects.create(
            name="a-record-rule",
            description="A record rule for devices",
            content_type=self.content_type_device,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )

        self.assertEqual(rule.record_type, "A")
        self.assertEqual(rule.value_template, "{{ obj.primary_ip4.id }}")

    def test_dnsrule_for_aaaa_record(self):
        """Test DNSRule configured for AAAA record type."""
        rule = DNSRule.objects.create(
            name="aaaa-record-rule",
            content_type=self.content_type_device,
            zone_template="example.com",
            record_type="AAAA",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip6.id }}",
        )

        self.assertEqual(rule.record_type, "AAAA")
        self.assertEqual(rule.value_template, "{{ obj.primary_ip6.id }}")

    def test_dnsrule_for_cname_record(self):
        """Test DNSRule configured for CNAME record type."""
        rule = DNSRule.objects.create(
            name="cname-record-rule",
            content_type=self.content_type_device,
            zone_template="example.com",
            record_type="CNAME",
            name_template="www-{{ obj.name }}",
            value_template="{{ obj.name }}.example.com",
        )

        self.assertEqual(rule.record_type, "CNAME")
        self.assertEqual(rule.value_template, "{{ obj.name }}.example.com")

    def test_dnsrule_for_ptr_record(self):
        """Test DNSRule configured for PTR record type."""
        rule = DNSRule.objects.create(
            name="ptr-record-rule",
            content_type=self.content_type_device,
            zone_template="2.0.192.in-addr.arpa",
            record_type="PTR",
            name_template="{{ obj.primary_ip4.address.ip.split('.')[-1] }}",
            value_template="{{ obj.name }}.example.com",
        )

        self.assertEqual(rule.record_type, "PTR")
        self.assertEqual(rule.value_template, "{{ obj.name }}.example.com")

    def test_dnsrule_defaults(self):
        """Test DNSRule default values."""
        rule = DNSRule.objects.create(
            name="defaults-test",
            content_type=self.content_type_device,
            zone_template="example.com",
            record_type="CNAME",
            name_template="{{ obj.name }}",
            value_template="test-value",
        )

        # Test default values
        self.assertEqual(rule.description, "")
        self.assertTrue(rule.enabled)

    def test_dnsrule_name_unique(self):
        """Test that DNSRule names must be unique."""
        DNSRule.objects.create(
            name="unique-test",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )

        # Attempt to create another rule with the same name
        with self.assertRaises(ValidationError):
            duplicate_rule = DNSRule(
                name="unique-test",
                content_type=self.content_type_device,
                zone_template="test.com",
                record_type="A",
                name_template="{{ obj.name }}",
                value_template="{{ obj.primary_ip4.id }}",
            )
            duplicate_rule.full_clean()

    def test_dnsrule_record_type_choices(self):
        """Test that DNSRule record_type validates against DNSRecordTypeChoices."""
        valid_types = [choice[0] for choice in DNSRecordTypeChoices.CHOICES]

        # Test valid record types
        for record_type in valid_types:
            rule_data = {
                "name": f"test-{record_type.lower()}",
                "content_type": self.content_type_device,
                "zone_template": "test.com",
                "record_type": record_type,
                "name_template": "{{ obj.name }}",
                "value_template": "test-value",
            }

            rule = DNSRule(**rule_data)
            rule.full_clean()  # Should not raise

        # Test invalid record type
        with self.assertRaises(ValidationError):
            invalid_rule = DNSRule(
                name="invalid-type",
                content_type=self.content_type_device,
                zone_template="test.com",
                record_type="INVALID",
                name_template="{{ obj.name }}",
                value_template="test-value",
            )
            invalid_rule.full_clean()

    def test_get_absolute_url(self):
        """Test DNSRule get_absolute_url method."""
        rule = DNSRule.objects.create(
            name="url-test-rule",
            content_type=self.content_type_device,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.address }}",
        )
        expected_url = f"/plugins/dns/dns-rules/{rule.pk}/"
        self.assertEqual(rule.get_absolute_url(), expected_url)

    def test_dnsrule_template_fields_blank(self):
        """Test that optional template fields can be blank."""
        rule = DNSRule.objects.create(
            name="blank-templates",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="CNAME",
            name_template="{{ obj.name }}",
            value_template="{{ obj.name }}.example.com",
        )

        self.assertEqual(rule.value_template, "{{ obj.name }}.example.com")

    def test_dnsrule_enabled_default_true(self):
        """Test that DNSRule enabled field defaults to True."""
        rule = DNSRule(
            name="default-enabled",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )
        # Before saving, enabled should default to True
        self.assertTrue(rule.enabled)

    def test_dnsrule_value_template_required(self):
        """Test that value_template is required and cannot be omitted."""
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="missing-value-template",
                content_type=self.content_type_device,
                zone_template="test.com",
                record_type="A",
                name_template="{{ obj.name }}",
                # value_template is intentionally omitted
            )
            rule.full_clean()

    def test_dnsrule_required_fields_validation(self):
        """Test that all required fields throw validation errors when missing."""
        # Test missing name
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                content_type=self.content_type_device,
                zone_template="test.com",
                record_type="A",
                name_template="{{ obj.name }}",
                value_template="{{ obj.primary_ip4.id }}",
            )
            rule.full_clean()

        # Test missing zone_template
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="missing-zone-template",
                content_type=self.content_type_device,
                record_type="A",
                name_template="{{ obj.name }}",
                value_template="{{ obj.primary_ip4.id }}",
            )
            rule.full_clean()

        # Test missing name_template
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="missing-name-template",
                content_type=self.content_type_device,
                zone_template="test.com",
                record_type="A",
                value_template="{{ obj.primary_ip4.id }}",
            )
            rule.full_clean()

        # Test missing record_type
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="missing-record-type",
                content_type=self.content_type_device,
                zone_template="test.com",
                name_template="{{ obj.name }}",
                value_template="{{ obj.primary_ip4.id }}",
            )
            rule.full_clean()

        # Test missing content_type
        with self.assertRaises(ValidationError):
            rule = DNSRule(
                name="missing-content-type",
                zone_template="test.com",
                record_type="A",
                name_template="{{ obj.name }}",
                value_template="{{ obj.primary_ip4.id }}",
            )
            rule.full_clean()

    def test_dnsrule_global_uniqueness_constraint(self):
        """Test that two enabled global rules with same content_type + record_type fails."""
        # Create first enabled global rule (location=None)
        DNSRule.objects.create(
            name="global-rule-1",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Global rule
            enabled=True,  # Enabled
        )

        # Attempt to create second enabled global rule with same content_type + record_type
        with self.assertRaises(ValidationError):  # Model validation error
            duplicate_rule = DNSRule(
                name="global-rule-2",
                content_type=self.content_type_device,
                zone_template="test.com",
                record_type="A",
                name_template="{{ obj.name }}",
                value_template="{{ obj.primary_ip4.id }}",
                location=None,  # Same: global rule
                enabled=True,  # Same: enabled
            )
            duplicate_rule.full_clean()  # Triggers validate_unique()

    @skip(
        "Skipping test_dnsrule_enabling_disabled_rule_with_enabled_duplicate_fails since we disabled that check. We maybe revert it, so leaving the test here."
    )
    def test_dnsrule_location_scoped_uniqueness_constraint(self):
        """Test that two enabled location-scoped rules with same content_type + record_type + location fails."""
        # Create first enabled location-scoped rule
        DNSRule.objects.create(
            name="location-rule-1",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Specific location
            enabled=True,  # Enabled
        )

        # Attempt to create second enabled rule with same content_type + record_type + location
        with self.assertRaises(IntegrityError):  # Database constraint violation
            DNSRule.objects.create(
                name="location-rule-2",
                content_type=self.content_type_device,
                zone_template="test.com",
                record_type="A",
                name_template="{{ obj.name }}",
                value_template="{{ obj.primary_ip4.id }}",
                location=self.location,  # Same location
                enabled=True,  # Same: enabled
            )

    def test_dnsrule_global_and_location_rules_allowed(self):
        """Test that global rule + location-scoped rule with same content_type + record_type succeeds."""
        # Create global rule
        global_rule = DNSRule.objects.create(
            name="global-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Global
        )

        # Create location-scoped rule (should succeed - different location value)
        location_rule = DNSRule.objects.create(
            name="location-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Specific location
        )

        # Both should exist
        self.assertTrue(DNSRule.objects.filter(id=global_rule.id).exists())
        self.assertTrue(DNSRule.objects.filter(id=location_rule.id).exists())

        # Verify they have different location values
        self.assertIsNone(global_rule.location)
        self.assertEqual(location_rule.location, self.location)

    def test_dnsrule_disabled_rules_allow_duplicates(self):
        """Test that disabled rules can have duplicate content_type + record_type combinations."""
        # Create first disabled global rule
        DNSRule.objects.create(
            name="disabled-global-rule-1",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Global rule
            enabled=False,  # Disabled
        )

        # Create second disabled global rule with same content_type + record_type (should succeed)
        DNSRule.objects.create(
            name="disabled-global-rule-2",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Same: global rule
            enabled=False,  # Same: disabled
        )

        # Create disabled location-scoped rules with same content_type + record_type + location (should succeed)
        DNSRule.objects.create(
            name="disabled-location-rule-1",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Specific location
            enabled=False,  # Disabled
        )

        DNSRule.objects.create(
            name="disabled-location-rule-2",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Same location
            enabled=False,  # Same: disabled
        )

        # Verify all rules were created successfully
        self.assertEqual(DNSRule.objects.filter(enabled=False).count(), 4)

    def test_dnsrule_enabled_rule_allowed_with_disabled_duplicate(self):
        """Test that an enabled rule can be created when a disabled rule with same content_type + record_type exists."""
        # Create disabled global rule first
        DNSRule.objects.create(
            name="disabled-global-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Global rule
            enabled=False,  # Disabled
        )

        # Create enabled global rule with same content_type + record_type (should succeed)
        enabled_global_rule = DNSRule.objects.create(
            name="enabled-global-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Same: global rule
            enabled=True,  # Different: enabled
        )

        # Create disabled location-scoped rule
        DNSRule.objects.create(
            name="disabled-location-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Specific location
            enabled=False,  # Disabled
        )

        # Create enabled location-scoped rule with same content_type + record_type + location (should succeed)
        enabled_location_rule = DNSRule.objects.create(
            name="enabled-location-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Same location
            enabled=True,  # Different: enabled
        )

        # Verify all rules were created successfully
        self.assertEqual(DNSRule.objects.filter(enabled=False).count(), 2)
        # Count includes the base test rule from setUpTestData (1) + our 2 new enabled rules = 3
        self.assertEqual(DNSRule.objects.filter(enabled=True).count(), 3)
        self.assertTrue(enabled_global_rule.enabled)
        self.assertTrue(enabled_location_rule.enabled)

    @skip(
        "Skipping test_dnsrule_enabling_disabled_rule_with_enabled_duplicate_fails since we disabled that check. We maybe revert it, so leaving the test here."
    )
    def test_dnsrule_enabling_disabled_rule_with_enabled_duplicate_fails(self):
        """Test that enabling a disabled rule fails when an enabled rule with same content_type + record_type exists."""
        # Create enabled global rule first
        DNSRule.objects.create(
            name="enabled-global-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Global rule
            enabled=True,  # Enabled
        )

        # Create disabled global rule with same content_type + record_type (should succeed initially)
        disabled_rule = DNSRule.objects.create(
            name="disabled-global-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=None,  # Same: global rule
            enabled=False,  # Different: disabled
        )

        # Attempt to enable the disabled rule (should fail due to uniqueness constraint)
        disabled_rule.enabled = True
        with self.assertRaises(ValidationError):
            disabled_rule.full_clean()

        # Test location-scoped scenario
        DNSRule.objects.create(
            name="enabled-location-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Specific location
            enabled=True,  # Enabled
        )

        disabled_location_rule = DNSRule.objects.create(
            name="disabled-location-rule",
            content_type=self.content_type_device,
            zone_template="test.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
            location=self.location,  # Same location
            enabled=False,  # Disabled
        )

        # Attempt to enable the disabled location rule (should fail)
        disabled_location_rule.enabled = True
        with self.assertRaises(ValidationError):
            disabled_location_rule.full_clean()

    def test_whitespace_disallowed_all_record_types(self):
        """Whitespace is disallowed in all templates for all supported record types."""

        record_types = [x[0] for x in DNSRecordTypeChoices.CHOICES]

        # Base valid (no-whitespace) templates
        base_kwargs = {
            "content_type": self.content_type_device,
            "zone_template": "example.com",
            "name_template": "{{ obj.name }}",
            "value_template": "{{ obj.primary_ip4.id }}",
            "enabled": False,
        }

        # Whitespace-injected variants per field
        whitespace_templates = {
            "zone_template": "example com",
            "name_template": "{{ 'device info' }}",
            "value_template": "primary ip",
        }

        for record_type in record_types:
            # Start from clean valid kwargs
            kwargs = dict(base_kwargs)
            kwargs["name"] = f"whitespace-disallow-{record_type}"
            kwargs["record_type"] = record_type

            # Fields to test for whitespace
            fields_to_test = ["zone_template", "name_template", "value_template"]

            for field in fields_to_test:
                with self.subTest(record_type=record_type, field=field):
                    # Instantiate with whitespace in the specific field
                    test_kwargs = dict(kwargs)
                    test_kwargs[field] = whitespace_templates[field]

                    rule = DNSRule(**test_kwargs)

                    with self.assertRaises(ValidationError) as ctx:
                        rule.full_clean()
                    self.assertIn(field, ctx.exception.message_dict)
                    self.assertIn(
                        "Whitespace in literals is not allowed; use '-' or '.'", ctx.exception.message_dict[field]
                    )


class DNSRuleRecordTestCase(TestCase):
    """Test the DNSRuleRecord model."""

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSRuleRecord model."""
        # Create required objects
        cls.status = Status.objects.get(name="Active")
        cls.namespace = Namespace.objects.get(name="Global")

        # Create test location structure
        cls.location_type = LocationType.objects.create(name="Building")
        cls.location = Location.objects.create(
            name="Test Building",
            location_type=cls.location_type,
            status=cls.status,
        )

        # Create device infrastructure
        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_type = DeviceType.objects.create(
            manufacturer=cls.manufacturer,
            model="Test Device",
        )

        # Create a role for devices
        device_content_type = ContentType.objects.get_for_model(Device)
        cls.device_role = Role.objects.create(name="Test Device Role")
        cls.device_role.content_types.add(device_content_type)

        # Create a status for interfaces
        interface_content_type = ContentType.objects.get_for_model(Interface)
        cls.interface_status = Status.objects.create(name="Test Interface Status")
        cls.interface_status.content_types.add(interface_content_type)

        cls.device = Device.objects.create(
            name="test-device-1",
            device_type=cls.device_type,
            location=cls.location,
            role=cls.device_role,
            status=cls.status,
        )
        cls.interface = Interface.objects.create(
            device=cls.device,
            name="eth0",
            type="1000base-t",
            status=cls.interface_status,
        )

        # Create IP addresses
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=cls.namespace, type="Pool", status=cls.status)
        cls.ip_address = IPAddress.objects.create(
            address="10.0.0.1/32",
            namespace=cls.namespace,
            status=cls.status,
        )

        # Create DNS zone and records
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.a_record = ARecord.objects.create(
            name="test-device-1",
            address=cls.ip_address,
            zone=cls.dns_zone,
        )

        # Create DNS rule
        cls.content_type_device = ContentType.objects.get_for_model(Device)
        cls.content_type_a_record = ContentType.objects.get_for_model(ARecord)
        cls.dns_rule = DNSRule.objects.create(
            name="test-device-rule",
            content_type=cls.content_type_device,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4.id }}",
        )

    def test_dnsrulerecord_create(self):
        """Test creating a DNSRuleRecord."""
        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        self.assertEqual(rule_record.rule, self.dns_rule)
        self.assertEqual(rule_record.content_type, self.content_type_device)
        self.assertEqual(rule_record.object_id, self.device.id)
        self.assertEqual(rule_record.source_object, self.device)
        self.assertEqual(rule_record.dns_record_content_type, self.content_type_a_record)
        self.assertEqual(rule_record.dns_record_object_id, self.a_record.id)
        self.assertEqual(rule_record.dns_record, self.a_record)

        # Test string representation
        expected_str = f"{self.dns_rule.name} -> {self.a_record}"
        self.assertEqual(str(rule_record), expected_str)

    def test_dnsrulerecord_generic_foreign_keys(self):
        """Test that GenericForeignKey relationships work correctly."""
        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        # Test source_object GenericForeignKey
        self.assertEqual(rule_record.source_object, self.device)
        self.assertEqual(rule_record.source_object.name, "test-device-1")

        # Test dns_record GenericForeignKey
        self.assertEqual(rule_record.dns_record, self.a_record)
        self.assertEqual(rule_record.dns_record.name, "test-device-1")

    def test_dnsrulerecord_uuid_fields(self):
        """Test that UUIDField correctly handles UUID values."""
        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,  # UUID object
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,  # UUID object
        )

        # Verify that UUIDs are handled correctly
        self.assertEqual(rule_record.object_id, self.device.id)
        self.assertEqual(rule_record.dns_record_object_id, self.a_record.id)

        # Verify that we can query by UUID
        found_record = DNSRuleRecord.objects.get(object_id=self.device.id)
        self.assertEqual(found_record, rule_record)

    def test_dnsrulerecord_unique_together(self):
        """Test the unique_together constraint on DNSRuleRecord."""
        # Create first rule record
        DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        # Attempt to create duplicate should fail at database level
        # (unique_together is enforced by database constraint, not model validation)
        with self.assertRaises(IntegrityError):
            DNSRuleRecord.objects.create(
                rule=self.dns_rule,
                content_type=self.content_type_device,
                object_id=self.device.id,
                dns_record_content_type=self.content_type_a_record,
                dns_record_object_id=self.a_record.id,
            )

    def test_dnsrulerecord_with_different_record_types(self):
        """Test DNSRuleRecord with different DNS record types."""
        # Create CNAME record
        cname_record = CNAMERecord.objects.create(
            name="www-test-device-1",
            alias="test-device-1.example.com",
            zone=self.dns_zone,
        )

        content_type_cname = ContentType.objects.get_for_model(CNAMERecord)

        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=content_type_cname,
            dns_record_object_id=cname_record.id,
        )

        self.assertEqual(rule_record.dns_record, cname_record)
        self.assertEqual(rule_record.dns_record.alias, "test-device-1.example.com")

    def test_dnsrulerecord_with_interface_source(self):
        """Test DNSRuleRecord with Interface as source object."""
        content_type_interface = ContentType.objects.get_for_model(Interface)

        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=content_type_interface,
            object_id=self.interface.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        self.assertEqual(rule_record.source_object, self.interface)
        self.assertEqual(rule_record.source_object.device, self.device)
        self.assertEqual(rule_record.source_object.name, "eth0")

    def test_dnsrulerecord_basemodel_inheritance(self):
        """Test that DNSRuleRecord inherits from BaseModel correctly."""
        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        # Should have UUID primary key
        self.assertIsNotNone(rule_record.id)

        # Should be a proper UUID, not an integer
        self.assertEqual(len(str(rule_record.id)), 36)  # UUID string length

        # Should inherit from BaseModel (basic check)

        self.assertIsInstance(rule_record, BaseModel)

    def test_dnsrulerecord_with_aaaa_record(self):
        """Test DNSRuleRecord with AAAA record."""
        # Create IPv6 address and AAAA record
        Prefix.objects.create(prefix="2001:db8::/64", namespace=self.namespace, type="Pool", status=self.status)
        ipv6_address = IPAddress.objects.create(
            address="2001:db8::1/128",
            namespace=self.namespace,
            status=self.status,
        )

        aaaa_record = AAAARecord.objects.create(
            name="test-device-ipv6",
            address=ipv6_address,
            zone=self.dns_zone,
        )

        content_type_aaaa = ContentType.objects.get_for_model(AAAARecord)

        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=content_type_aaaa,
            dns_record_object_id=aaaa_record.id,
        )

        self.assertEqual(rule_record.dns_record, aaaa_record)
        self.assertEqual(rule_record.dns_record.address, ipv6_address)

    def test_dnsrulerecord_cascade_delete_on_rule_deletion(self):
        """Test that DNSRuleRecord is deleted when associated DNSRule is deleted."""
        rule_record = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        rule_record_id = rule_record.id

        # Delete the DNS rule
        self.dns_rule.delete()

        # DNSRuleRecord should be cascade deleted
        with self.assertRaises(DNSRuleRecord.DoesNotExist):
            DNSRuleRecord.objects.get(id=rule_record_id)

    def test_dnsrulerecord_multiple_rules_same_source(self):
        """Test multiple DNSRuleRecord entries for the same source object with different rules."""
        # Create second DNS rule
        second_rule = DNSRule.objects.create(
            name="second-device-rule",
            content_type=self.content_type_device,
            zone_template="internal.com",
            record_type="AAAA",
            name_template="{{ obj.name }}-info",
            value_template="{{ obj.primary_ip6.id }}",
        )

        # Create rule records for same device with different rules
        rule_record_1 = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        # Create a second A record for the second rule
        second_a_record = ARecord.objects.create(
            name="test-device-1-info",
            address=self.ip_address,
            zone=self.dns_zone,
        )

        rule_record_2 = DNSRuleRecord.objects.create(
            rule=second_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=second_a_record.id,
        )

        # Both should exist and be distinct
        self.assertNotEqual(rule_record_1, rule_record_2)
        self.assertEqual(rule_record_1.source_object, rule_record_2.source_object)
        self.assertNotEqual(rule_record_1.rule, rule_record_2.rule)

        # Query should return both records for the same device
        device_records = DNSRuleRecord.objects.filter(content_type=self.content_type_device, object_id=self.device.id)
        self.assertEqual(device_records.count(), 2)

    def test_single_source_object_per_dns_record_constraint(self):
        """Test that the same source object cannot be linked to the same DNS record twice."""
        # Create a test DNS rule
        test_rule = DNSRule.objects.create(
            name="test-rule-2",
            content_type=self.content_type_device,
            zone_template="example.com",
            record_type="A",
            name_template="{{ obj.name }}-alt",
            value_template="{{ obj.primary_ip4 }}",
            enabled=True,
        )

        # Create the first DNSRuleRecord (should succeed)
        rule_record1 = DNSRuleRecord.objects.create(
            rule=self.dns_rule,
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )

        # Verify only one record exists before attempting duplicate
        matching_records_before = DNSRuleRecord.objects.filter(
            content_type=self.content_type_device,
            object_id=self.device.id,
            dns_record_content_type=self.content_type_a_record,
            dns_record_object_id=self.a_record.id,
        )
        self.assertEqual(matching_records_before.count(), 1)
        self.assertEqual(rule_record1.rule, self.dns_rule)

        # Attempting to link the same source object to the same DNS record should fail
        with self.assertRaises(IntegrityError):
            DNSRuleRecord.objects.create(
                rule=test_rule,  # Different rule
                content_type=self.content_type_device,
                object_id=self.device.id,  # Same source object - should cause failure
                dns_record_content_type=self.content_type_a_record,
                dns_record_object_id=self.a_record.id,  # Same DNS record - should cause failure
            )
