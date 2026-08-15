"""Test DNSZone."""
# pylint: disable=too-many-lines

from constance.test import override_config
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from nautobot.apps.change_logging import web_request_context
from nautobot.apps.testing import ModelTestCases, TestCase
from nautobot.extras.models import ObjectChange, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix
from netutils.ip import ipaddress_address

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.models import (
    APEX_RECORD_NAME,
    CATALOG_APEX_NS_SERVER,
    UINT32_MAX,
    AAAARecord,
    ARecord,
    CatalogZoneMembership,
    CNAMERecord,
    DNSRegistrar,
    DNSRegistration,
    DNSView,
    DNSViewPrefixAssignment,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
    catalog_member_label,
    dns_record_models,
    dns_wire_label_length,
)
from nautobot_dns_models.system_writes import system_write


def create_zone(name, **kwargs):
    """Create a zone, supplying the fields the model requires but this module does not care about."""
    return DNSZone.objects.create(
        name=name,
        filename=f"{name}.zone",
        soa_mname=f"ns1.{name}.",
        soa_rname=f"admin@{name}",
        **kwargs,
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


class TestDNSRegistrar(ModelTestCases.BaseModelTestCase):
    """Test DNSRegistrar model."""

    model = DNSRegistrar

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSRegistrar Model."""
        super().setUpTestData()
        DNSRegistrar.objects.create(name="Registrar 1", url="https://registrar1.example", account_number="ACC-001")
        DNSRegistrar.objects.create(name="Registrar 2", url="https://registrar2.example", account_number="ACC-002")
        DNSRegistrar.objects.create(name="Registrar 3", url="https://registrar3.example", account_number="ACC-003")

    def test_create_dnsregistrar_only_required(self):
        """Create with only required fields."""
        registrar = DNSRegistrar.objects.create(name="Test Registrar")
        self.assertEqual(registrar.name, "Test Registrar")
        self.assertEqual(registrar.url, "")
        self.assertEqual(registrar.account_number, "")
        self.assertEqual(str(registrar), "Test Registrar")

    def test_create_dnsregistrar_all_fields_success(self):
        """Create DNSRegistrar with all fields."""
        registrar = DNSRegistrar.objects.create(
            name="Another Registrar",
            url="https://another-registrar.example",
            account_number="ACCT-1234",
        )
        self.assertEqual(registrar.name, "Another Registrar")
        self.assertEqual(registrar.url, "https://another-registrar.example")
        self.assertEqual(registrar.account_number, "ACCT-1234")

    def test_get_absolute_url(self):
        registrar = DNSRegistrar.objects.get(name="Registrar 1")
        self.assertEqual(registrar.get_absolute_url(), f"/plugins/dns/dns-registrars/{registrar.id}/")


class TestDNSRegistration(ModelTestCases.BaseModelTestCase):
    """Test DNSRegistration model."""

    model = DNSRegistration

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSRegistration Model."""
        super().setUpTestData()
        for i in range(3):
            DNSZone.objects.create(name=f"Test Zone {i}", zone_type=DNSZoneTypeChoices.TYPE_PRIMARY)

        cls.registrar = DNSRegistrar.objects.create(name="Test Registrar")
        status = Status.objects.get(name="Active")
        status.content_types.add(ContentType.objects.get_for_model(DNSRegistration))
        cls.status = status

        DNSRegistration.objects.create(
            dns_registrar=cls.registrar,
            status=cls.status,
            dns_zone=DNSZone.objects.get(name="Test Zone 0"),
        )

    def test_registration_accepts_primary_zone(self):
        """Test that registration accepts a primary zone."""
        primary_zone = DNSZone.objects.create(name="Test Primary", zone_type=DNSZoneTypeChoices.TYPE_PRIMARY)
        registration = DNSRegistration(
            dns_registrar=self.registrar,
            status=self.status,
            dns_zone=primary_zone,
        )
        registration.validated_save()

        self.assertEqual(registration.dns_zone, primary_zone)

    def test_registration_rejects_catalog_zone(self):
        """Test that registration rejects a catalog zone."""
        catalog_zone = DNSZone.objects.create(name="Test Catalog", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with self.assertRaises(ValidationError) as context:
            DNSRegistration(
                dns_registrar=self.registrar,
                status=self.status,
                dns_zone=catalog_zone,
            ).validated_save()

        self.assertEqual(context.exception.message_dict["dns_zone"], ["Catalog zones cannot be registered."])


class TestDnsZone(ModelTestCases.BaseModelTestCase):
    """Test DnsZone model."""

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
        self.assertTrue(dnszone.enabled)
        self.assertEqual(str(dnszone), "Development (Default)")

    def test_create_dnszone_all_fields_success(self):
        """Create DnsZoneModel with all fields."""
        dnszone = DNSZone.objects.create(
            name="Development",
            description="Development Test",
            filename="development.zone",
            soa_mname="ns1.development.example",
            soa_rname="admin@development.example",
        )
        self.assertEqual(dnszone.name, "Development")
        self.assertEqual(dnszone.description, "Development Test")
        self.assertEqual(dnszone.filename, "development.zone")

    def test_get_absolute_url(self):
        dns_zone_model = DNSZone.objects.create(name="example.com")
        self.assertEqual(dns_zone_model.get_absolute_url(), f"/plugins/dns/dns-zones/{dns_zone_model.id}/")


class NSRecordTestCase(TestCase):
    """Test the NSRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_nsrecord(self):
        ns_record = NSRecord.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)

        self.assertEqual(ns_record.name, "primary")
        self.assertEqual(ns_record.server, "example-server.com.")
        self.assertEqual(str(ns_record), ns_record.name)

    def test_get_absolute_url(self):
        ns_record = NSRecord.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)
        self.assertEqual(ns_record.get_absolute_url(), f"/plugins/dns/ns-records/{ns_record.id}/")


class ARecordTestCase(TestCase):
    """Test the ARecord model."""

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

    def test_create_arecord(self):
        a_record = ARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)

        self.assertEqual(a_record.name, "site.example.com")
        self.assertEqual(a_record.ip_address, self.ip_address)
        self.assertEqual(a_record.ttl, 3600)
        self.assertEqual(str(a_record), a_record.name)

    def test_create_ipv6_arecord_fails(self):
        # Test that creating an IPv6 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = ARecord(name="invalid.example.com", ip_address=self.ipv6_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_create_ipv6_arecord_fails_on_save(self):
        """Creating via ORM should also fail due to save() calling clean()."""
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="invalid-save.example.com", ip_address=self.ipv6_address, zone=self.dns_zone)

    def test_get_absolute_url(self):
        a_record = ARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)
        self.assertEqual(a_record.get_absolute_url(), f"/plugins/dns/a-records/{a_record.id}/")


class AAAARecordTestCase(TestCase):
    """Test the AAAARecord model."""

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

    def test_create_aaaarecord(self):
        aaaa_record = AAAARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)

        self.assertEqual(aaaa_record.name, "site.example.com")
        self.assertEqual(aaaa_record.ip_address, self.ip_address)
        self.assertEqual(aaaa_record.ttl, 3600)
        self.assertEqual(str(aaaa_record), aaaa_record.name)

    def test_create_ipv4_aaaarecord_fails(self):
        # Test that creating an IPv4 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = AAAARecord(name="invalid.example.com", ip_address=self.ipv4_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_create_ipv4_aaaarecord_fails_on_save(self):
        """Creating via ORM should also fail due to save() calling clean()."""
        with self.assertRaises(ValidationError):
            AAAARecord.objects.create(
                name="invalid-save.example.com",
                ip_address=self.ipv4_address,
                zone=self.dns_zone,
            )

    def test_get_absolute_url(self):
        aaaa_record = AAAARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)
        self.assertEqual(aaaa_record.get_absolute_url(), f"/plugins/dns/aaaa-records/{aaaa_record.id}/")


class CNAMERecordTestCase(TestCase):
    """Test the CNAMERecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_cnamerecord(self):
        cname_record = CNAMERecord.objects.create(name="www.example.com", alias="site.example.com", zone=self.dns_zone)

        self.assertEqual(cname_record.name, "www.example.com")
        self.assertEqual(cname_record.alias, "site.example.com")
        self.assertEqual(str(cname_record), cname_record.name)

    def test_get_absolute_url(self):
        cname_record = CNAMERecord.objects.create(name="www.example.com", alias="site.example.com", zone=self.dns_zone)
        self.assertEqual(cname_record.get_absolute_url(), f"/plugins/dns/cname-records/{cname_record.id}/")


class MXRecordTestCase(TestCase):
    """Test the MXRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_mxrecord(self):
        mx_record = MXRecord.objects.create(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)

        self.assertEqual(mx_record.name, "mail-record")
        self.assertEqual(mx_record.preference, 10)
        self.assertEqual(mx_record.mail_server, "mail.example.com")
        self.assertEqual(str(mx_record), mx_record.name)

    def test_get_absolute_url(self):
        mx_record = MXRecord.objects.create(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)
        self.assertEqual(mx_record.get_absolute_url(), f"/plugins/dns/mx-records/{mx_record.id}/")


class TXTRecordTestCase(TestCase):
    """Test the TXTRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_txtrecord(self):
        txt_record = TXTRecord.objects.create(name="txt-record", text="spf-record", zone=self.dns_zone)

        self.assertEqual(txt_record.name, "txt-record")
        self.assertEqual(txt_record.text, "spf-record")
        self.assertEqual(str(txt_record), txt_record.name)

    def test_get_absolute_url(self):
        txt_record = TXTRecord.objects.create(name="txt-record", text="spf-record", zone=self.dns_zone)
        self.assertEqual(txt_record.get_absolute_url(), f"/plugins/dns/txt-records/{txt_record.id}/")


class PTRRecordTestCase(TestCase):
    """Test the PTRRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_ptrrecord(self):
        ptr_record = PTRRecord.objects.create(name="ptr-record", ptrdname="ptr-record", zone=self.dns_zone)

        self.assertEqual(ptr_record.ptrdname, "ptr-record")
        self.assertEqual(str(ptr_record), ptr_record.ptrdname)

    def test_get_absolute_url(self):
        ptr_record = PTRRecord.objects.create(ptrdname="ptr-record", zone=self.dns_zone)
        self.assertEqual(ptr_record.get_absolute_url(), f"/plugins/dns/ptr-records/{ptr_record.id}/")


class SRVRecordTestCase(TestCase):
    """Test the SRVRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com", ttl=7200)

    def test_create_srvrecord(self):
        srv_record = SRVRecord.objects.create(
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

    def test_create_srvrecord_wo_ttl(self):
        srv_record = SRVRecord.objects.create(
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
        self.assertEqual(srv_record.ttl, 7200)  # Inherits from DNSZone
        self.assertEqual(srv_record.description, "SIP server")
        self.assertEqual(srv_record.comment, "Primary SIP server")
        self.assertEqual(str(srv_record), srv_record.name)

    def test_get_absolute_url(self):
        srv_record = SRVRecord.objects.create(
            name="_sip._tcp.example.com", priority=10, weight=5, port=5060, target="sip.example.com", zone=self.dns_zone
        )
        self.assertEqual(srv_record.get_absolute_url(), f"/plugins/dns/srv-records/{srv_record.id}/")


@override_config(nautobot_dns_models__CNAME_RESTRICTION_ENABLED=True)
class CNAMEExclusivityModelTestCase(TestCase):
    """Model-level tests for exact-match CNAME exclusivity."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(name="example.com")
        # IP setup for ARecord use
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.9.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ipv4_1 = IPAddress.objects.create(address="10.9.0.1/32", namespace=namespace, status=status)
        cls.ipv4_2 = IPAddress.objects.create(address="10.9.0.2/32", namespace=namespace, status=status)

    def test_cname_blocked_when_arecord_exists(self):
        ARecord.objects.create(name="app", ip_address=self.ipv4_1, zone=self.zone)
        with self.assertRaises(ValidationError):
            cname_record = CNAMERecord(name="app", alias="target.example.com", zone=self.zone)
            cname_record.validated_save()

    def test_non_cname_blocked_when_cname_exists(self):
        CNAMERecord.objects.create(name="web", alias="web.example.com", zone=self.zone)
        # TODO: remove `save` overwrite from ARecord model and revisit this test
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="web", ip_address=self.ipv4_2, zone=self.zone)

    def test_zone_qualified_name_allowed(self):
        """A(name='host') does NOT block CNAME(name='host.zone') since names must match exactly."""
        ARecord.objects.create(name="testrecord", ip_address=self.ipv4_1, zone=self.zone)
        # Allowed because name differs (zone-qualified vs relative)
        CNAMERecord.objects.create(name=f"testrecord.{self.zone.name}", alias="x.example.com", zone=self.zone)

    def test_trailing_dot_zone_qualified_allowed(self):
        """A(name='host') does NOT block CNAME(name='host.zone.') (trailing dot normalized)."""
        ARecord.objects.create(name="td", ip_address=self.ipv4_1, zone=self.zone)
        # Trailing dot is removed to "td.zone", still zone-qualified and thus different from "td"
        CNAMERecord.objects.create(name=f"td.{self.zone.name}.", alias="x.example.com", zone=self.zone)

    @override_config(nautobot_dns_models__CNAME_RESTRICTION_ENABLED=False)
    def test_opt_out_allows_coexistence(self):
        ARecord.objects.create(name="opt", ip_address=self.ipv4_1, zone=self.zone)
        # Should succeed when enforcement disabled
        CNAMERecord.objects.create(name="opt", alias="opt.example.com", zone=self.zone)


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
    def test_rejects_empty_label(self):
        record = TXTRecord(name="www..subdomain", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

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


class DNSZoneSOARNameTest(TestCase):
    """Test SOA RNAME normalization and validation."""

    def test_save_normalizes_soa_rname(self):
        test_cases = {
            "john.example.com": "john@example.com",
            "john.example.com.": "john@example.com",
            r"john\.smith.example.com": "john.smith@example.com",
            r"john\.smith.example.com.": "john.smith@example.com",
            r"john_smith.example.com": "john_smith@example.com",
            r"john_smith.example.com.": "john_smith@example.com",
            "invalid": "invalid",
            "invalid.": "invalid",
        }
        for index, (value, expected) in enumerate(test_cases.items()):
            with self.subTest(value=value):
                zone = DNSZone.objects.create(
                    name=f"rname-{index}.example",
                    filename=f"rname-{index}.example.zone",
                    soa_mname=f"ns1.rname-{index}.example.",
                    soa_rname=value,
                )
                self.assertEqual(zone.soa_rname, expected)

    def test_save_rejects_invalid_soa_rname(self):
        invalid_values = (
            "",
            "john@example",
            "john.example",
            "john@",
            "@example.com",
            "john@@example.com",
            ".example.com",
            "john..example.com",
            r"john\\.smith.example.com",
            r"john\\.smith.example.com.",
            r"john\\\.smith.example.com",
            r"john\\\.smith.example.com.",
            r"john\046example.com.",
            r"john.example\.com.",
            "a" * 64,
        )
        for index, value in enumerate(invalid_values):
            with self.subTest(value=value):
                zone = DNSZone(
                    name=f"invalid-rname-{index}.example",
                    filename=f"invalid-rname-{index}.example.zone",
                    soa_mname=f"ns1.invalid-rname-{index}.example.",
                    soa_rname=value,
                )

                with self.assertRaises(ValidationError) as context:
                    zone.validated_save()

                self.assertIn("soa_rname", context.exception.message_dict)


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


class AutoCreatePTRRecordTestCase(TestCase):
    """Test the per-zone auto_create_ptr flag for ARecord/AAAARecord."""

    @classmethod
    def setUpTestData(cls):
        cls.status = Status.objects.get(name="Active")
        cls.namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=cls.namespace, type="Pool", status=cls.status)
        cls.ipv4 = IPAddress.objects.create(address="10.0.0.1/32", namespace=cls.namespace, status=cls.status)
        cls.ipv4_other = IPAddress.objects.create(address="10.0.0.2/32", namespace=cls.namespace, status=cls.status)
        Prefix.objects.create(prefix="192.168.1.0/24", namespace=cls.namespace, type="Pool", status=cls.status)
        cls.ipv4_unmatched = IPAddress.objects.create(
            address="192.168.1.1/32", namespace=cls.namespace, status=cls.status
        )
        Prefix.objects.create(prefix="2001:db8::/32", namespace=cls.namespace, type="Pool", status=cls.status)
        cls.ipv6 = IPAddress.objects.create(address="2001:db8::1/128", namespace=cls.namespace, status=cls.status)

        cls.view = DNSView.objects.create(name="View Default")
        cls.other_view = DNSView.objects.create(name="View Other")
        cls.fwd_off = DNSZone.objects.create(name="example.com", dns_view=cls.view, auto_create_ptr=False)
        cls.fwd_on = DNSZone.objects.create(name="auto.example.com", dns_view=cls.view, auto_create_ptr=True)
        cls.reverse_zone = DNSZone.objects.create(name="0.0.10.in-addr.arpa", dns_view=cls.view)

    def test_no_auto_ptr_when_flag_disabled(self):
        """auto_create_ptr=False: no PTR is created even if a matching reverse zone exists."""
        ARecord.objects.create(name="host1", ip_address=self.ipv4, zone=self.fwd_off)
        self.assertFalse(PTRRecord.objects.exists())

    def test_auto_ptr_creates_record_when_enabled(self):
        """auto_create_ptr=True with matching reverse zone in same view creates a PTR."""
        ARecord.objects.create(name="host1", ip_address=self.ipv4, zone=self.fwd_on)
        ptr = PTRRecord.objects.get(zone=self.reverse_zone, name="1")
        self.assertEqual(ptr.ptrdname, "host1.auto.example.com")

    def test_auto_ptr_raises_when_no_reverse_zone(self):
        """No matching reverse zone in same view raises ValidationError pre-insert; A record is not persisted."""
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="host2", ip_address=self.ipv4_unmatched, zone=self.fwd_on)
        self.assertFalse(ARecord.objects.filter(name="host2").exists())
        self.assertFalse(PTRRecord.objects.exists())

    def test_auto_ptr_does_not_use_reverse_zone_in_different_view(self):
        """A reverse zone in a different DNS view is NOT used; raises ValidationError."""
        DNSZone.objects.create(name="1.168.192.in-addr.arpa", dns_view=self.other_view)
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="host3", ip_address=self.ipv4_unmatched, zone=self.fwd_on)
        self.assertFalse(ARecord.objects.filter(name="host3").exists())
        self.assertFalse(PTRRecord.objects.exists())

    def test_auto_ptr_does_not_use_catalog_reverse_zone(self):
        """A reverse-named catalog zone is not eligible to receive an automatically created PTR."""
        catalog_zone = DNSZone.objects.create(
            name="1.168.192.in-addr.arpa",
            dns_view=self.view,
            zone_type=DNSZoneTypeChoices.TYPE_CATALOG,
        )
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="host4", ip_address=self.ipv4_unmatched, zone=self.fwd_on)
        self.assertFalse(ARecord.objects.filter(name="host4").exists())
        self.assertFalse(PTRRecord.objects.filter(zone=catalog_zone).exists())

    def test_auto_ptr_idempotent_when_ptr_already_exists(self):
        """If a PTR with the same owner name already exists in the reverse zone, no duplicate is created."""
        existing = PTRRecord.objects.create(name="1", ptrdname="host1.auto.example.com", zone=self.reverse_zone)
        ARecord.objects.create(name="host1", ip_address=self.ipv4, zone=self.fwd_on)
        ptrs = PTRRecord.objects.filter(name="1", zone=self.reverse_zone)
        self.assertEqual(ptrs.count(), 1)
        self.assertEqual(ptrs.first().pk, existing.pk)

    def test_auto_ptr_for_aaaa_record(self):
        """AAAARecord triggers PTR creation similarly when flag is on."""
        full_reverse = ipaddress_address("2001:db8::1", "reverse_pointer")
        parent_zone_name = ".".join(full_reverse.split(".")[1:])
        reverse_v6 = DNSZone.objects.create(name=parent_zone_name, dns_view=self.view)
        AAAARecord.objects.create(name="v6host", ip_address=self.ipv6, zone=self.fwd_on)
        ptr = PTRRecord.objects.get(zone=reverse_v6, name="1")
        self.assertEqual(ptr.ptrdname, "v6host.auto.example.com")


class TestDNSZoneFindForPtrdname(TestCase):
    """Test DNSZone.find_for_ptrdname classmethod."""

    @classmethod
    def setUpTestData(cls):
        cls.view_a = DNSView.objects.create(name="View A")
        cls.view_b = DNSView.objects.create(name="View B")

    def test_finds_most_specific_match(self):
        specific = DNSZone.objects.create(name="0.0.10.in-addr.arpa", dns_view=self.view_a)
        DNSZone.objects.create(name="10.in-addr.arpa", dns_view=self.view_a)
        self.assertEqual(DNSZone.find_reverse_zone_for_ptrdname("1.0.0.10.in-addr.arpa"), specific)

    def test_falls_back_to_less_specific_match(self):
        broad = DNSZone.objects.create(name="10.in-addr.arpa", dns_view=self.view_a)
        self.assertEqual(DNSZone.find_reverse_zone_for_ptrdname("1.0.0.10.in-addr.arpa"), broad)

    def test_falls_back_past_catalog_zone(self):
        DNSZone.objects.create(
            name="0.0.10.in-addr.arpa",
            dns_view=self.view_a,
            zone_type=DNSZoneTypeChoices.TYPE_CATALOG,
        )
        broad = DNSZone.objects.create(name="10.in-addr.arpa", dns_view=self.view_a)
        self.assertEqual(DNSZone.find_reverse_zone_for_ptrdname("1.0.0.10.in-addr.arpa"), broad)

    def test_returns_none_when_nothing_matches(self):
        self.assertIsNone(DNSZone.find_reverse_zone_for_ptrdname("1.2.3.4.in-addr.arpa"))

    def test_returns_none_when_only_catalog_matches(self):
        DNSZone.objects.create(
            name="0.0.10.in-addr.arpa",
            dns_view=self.view_a,
            zone_type=DNSZoneTypeChoices.TYPE_CATALOG,
        )
        self.assertIsNone(DNSZone.find_reverse_zone_for_ptrdname("1.0.0.10.in-addr.arpa"))

    def test_dns_view_scoping(self):
        """When dns_view is provided, only zones in that view are considered."""
        specific = DNSZone.objects.create(name="0.0.10.in-addr.arpa", dns_view=self.view_a)
        self.assertIsNone(DNSZone.find_reverse_zone_for_ptrdname("1.0.0.10.in-addr.arpa", dns_view=self.view_b))
        self.assertEqual(
            DNSZone.find_reverse_zone_for_ptrdname("1.0.0.10.in-addr.arpa", dns_view=self.view_a),
            specific,
        )


class DNSZoneIntegerFieldBoundaryTest(TestCase):
    """Boundary tests for integer fields on DNSZone.

    TTL (RFC 8767 §4): unsigned 32-bit, 0..4294967295.
    SOA fields (RFC 1035 §3.3.13): 32-bit values, explicitly unsigned for SERIAL and MINIMUM.
    RFC 1982 §7 governs SERIAL's uint32 range and arithmetic.
    """

    _INTEGER_FIELDS = ("ttl", "soa_refresh", "soa_retry", "soa_expire", "soa_serial", "soa_minimum")

    def _make_zone(self, **kwargs):
        defaults = {
            "name": "boundary-test.example",
            "filename": "boundary-test.zone",
            "soa_mname": "ns1.boundary-test.example.",
            "soa_rname": "admin@boundary-test.example",
            "ttl": 3600,
            "soa_refresh": 86400,
            "soa_retry": 7200,
            "soa_expire": 3600000,
            "soa_serial": 0,
            "soa_minimum": 3600,
        }
        defaults.update(kwargs)
        return DNSZone(**defaults)

    def test_all_fields_accept_zero(self):
        """All DNS integer zone fields accept 0 as a valid value."""
        for field in self._INTEGER_FIELDS:
            with self.subTest(field=field):
                zone = self._make_zone(name=f"{field}-zero.example", **{field: 0})
                zone.full_clean()

    def test_all_fields_accept_uint32_max(self):
        """All DNS integer zone fields accept the uint32 maximum."""
        for field in self._INTEGER_FIELDS:
            with self.subTest(field=field):
                zone = self._make_zone(name=f"{field}-max.example", **{field: UINT32_MAX})
                zone.full_clean()

    def test_all_fields_reject_above_uint32_max(self):
        """All DNS integer zone fields reject values above the uint32 maximum."""
        for field in self._INTEGER_FIELDS:
            with self.subTest(field=field):
                zone = self._make_zone(name=f"{field}-overflow.example", **{field: UINT32_MAX + 1})
                with self.assertRaises(ValidationError):
                    zone.full_clean()


class DNSRecordTTLBoundaryTest(TestCase):
    """Boundary tests for the record-level TTL field (RFC 8767 §4: unsigned 32-bit, 0..4294967295)."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(name="ttl-boundary.example", ttl=3600)

    def test_record_ttl_accepts_zero(self):
        """Record TTL of 0 is valid."""
        record = NSRecord(name="ns1", server="ns1.example.com.", zone=self.zone, _ttl=0)
        record.full_clean()

    def test_record_ttl_zero_not_replaced_by_zone_ttl(self):
        """TTL of 0 must not be treated as unset and silently replaced by the zone TTL (guards against falsy-check regression)."""
        record = NSRecord.objects.create(name="ns-zero", server="ns1.example.com.", zone=self.zone, _ttl=0)
        record.refresh_from_db()
        self.assertEqual(record.ttl, 0)

    def test_record_ttl_accepts_uint32_max(self):
        """Record TTL at the uint32 maximum is accepted."""
        record = NSRecord(name="ns1", server="ns1.example.com.", zone=self.zone, _ttl=UINT32_MAX)
        record.full_clean()

    def test_record_ttl_rejects_above_uint32_max(self):
        """Record TTL above the uint32 maximum is rejected."""
        record = NSRecord(name="ns1", server="ns1.example.com.", zone=self.zone, _ttl=UINT32_MAX + 1)
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_record_inherits_zone_ttl_when_no_record_ttl_set(self):
        """When no record-level TTL is set, the zone TTL is returned by the ttl property."""
        record = NSRecord.objects.create(name="ns1", server="ns1.example.com.", zone=self.zone)
        self.assertEqual(record.ttl, self.zone.ttl)


class DNSModelEnabledFieldTest(TestCase):
    """Tests for the `enabled` field that DNSZone and every record type inherit from DNSModel."""

    @classmethod
    def setUpTestData(cls):
        # Populate the required zone fields so the zone can be re-saved with validated_save().
        cls.zone = DNSZone.objects.create(
            name="enabled.example",
            filename="enabled.example.zone",
            soa_mname="ns1.enabled.example",
            soa_rname="admin@enabled.example",
        )
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.10.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="10.10.0.1/32", namespace=namespace, status=status)
        Prefix.objects.create(prefix="2001:db8:abcd:77::/64", namespace=namespace, type="Pool", status=status)
        cls.ipv6_address = IPAddress.objects.create(
            address="2001:db8:abcd:77::1/128", namespace=namespace, status=status
        )

    def _records(self, suffix, **kwargs):
        """Return one unsaved record of every type, all named after `suffix`."""
        return [
            NSRecord(name=f"ns-{suffix}", server="ns1.example.com.", zone=self.zone, **kwargs),
            ARecord(name=f"a-{suffix}", ip_address=self.ip_address, zone=self.zone, **kwargs),
            AAAARecord(name=f"aaaa-{suffix}", ip_address=self.ipv6_address, zone=self.zone, **kwargs),
            CNAMERecord(name=f"cname-{suffix}", alias="www.example.com", zone=self.zone, **kwargs),
            MXRecord(name=f"mx-{suffix}", mail_server="mail.example.com", zone=self.zone, **kwargs),
            TXTRecord(name=f"txt-{suffix}", text="v=spf1 -all", zone=self.zone, **kwargs),
            PTRRecord(name=f"ptr-{suffix}", ptrdname="www.example.com", zone=self.zone, **kwargs),
            SRVRecord(
                name=f"srv-{suffix}",
                priority=10,
                weight=5,
                port=5060,
                target="sip.example.com",
                zone=self.zone,
                **kwargs,
            ),
        ]

    def test_zone_is_enabled_by_default(self):
        """A zone is eligible for publication unless explicitly disabled."""
        self.assertTrue(DNSZone.objects.create(name="default.example").enabled)

    def test_zone_can_be_disabled(self):
        """A zone's enabled flag can be set to False."""
        zone = DNSZone.objects.create(name="disabled.example", enabled=False)
        zone.refresh_from_db()
        self.assertFalse(zone.enabled)

    def test_records_are_enabled_by_default(self):
        """Every record type inherits enabled=True from DNSModel."""
        for record in self._records("default"):
            with self.subTest(model=type(record).__name__):
                record.validated_save()
                record.refresh_from_db()
                self.assertTrue(record.enabled)

    def test_records_can_be_disabled(self):
        """Every record type can be created with enabled=False."""
        for record in self._records("disabled", enabled=False):
            with self.subTest(model=type(record).__name__):
                record.validated_save()
                record.refresh_from_db()
                self.assertFalse(record.enabled)

    def test_disabling_zone_does_not_disable_its_records(self):
        """The zone and record flags are independent; this app does not cascade them."""
        record = NSRecord.objects.create(name="ns-cascade", server="ns1.example.com.", zone=self.zone)

        self.zone.enabled = False
        self.zone.validated_save()

        record.refresh_from_db()
        self.assertTrue(record.enabled)


class DNSZoneTypeTest(TestCase):
    """Tests for the DNSZone.zone_type field and the invariants it carries."""

    def test_default_zone_type_is_primary(self):
        """A zone created without an explicit type is a primary zone."""
        zone = DNSZone.objects.create(name="default-type.example")
        self.assertEqual(zone.zone_type, DNSZoneTypeChoices.TYPE_PRIMARY)

    def test_catalog_zone_can_be_created(self):
        """A catalog zone can be created and validated."""
        zone = self._make_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        zone.validated_save()
        zone.refresh_from_db()
        self.assertEqual(zone.zone_type, DNSZoneTypeChoices.TYPE_CATALOG)

    def test_rejects_zone_type_change(self):
        """Changing zone_type on an existing zone is rejected."""
        zone = self._make_zone("immutable.example")
        zone.validated_save()
        zone.zone_type = DNSZoneTypeChoices.TYPE_CATALOG
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("cannot be changed after creation", str(context.exception.message_dict["zone_type"]))

    def test_primary_zone_allows_auto_create_ptr(self):
        """auto_create_ptr remains available on primary zones."""
        zone = self._make_zone("ptr-ok.example", auto_create_ptr=True)
        zone.validated_save()
        self.assertTrue(zone.auto_create_ptr)

    def test_catalog_zone_rejects_auto_create_ptr(self):
        """Validation rejects auto_create_ptr on a catalog zone rather than silently ignoring it."""
        zone = self._make_zone("catalog-ptr.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG, auto_create_ptr=True)
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("cannot enable automatic PTR creation", str(context.exception.message_dict["auto_create_ptr"]))

    def test_catalog_zone_auto_create_ptr_blocked_at_database(self):
        """The check constraint blocks auto_create_ptr on catalog zones even when validation is skipped."""
        zone = DNSZone.objects.create(name="catalog-db.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with self.assertRaises(IntegrityError):
            DNSZone.objects.filter(pk=zone.pk).update(auto_create_ptr=True)

    @staticmethod
    def _make_zone(name, **kwargs):
        """Build an unsaved DNSZone populated with every field full_clean() requires."""
        defaults = {
            "name": name,
            "filename": f"{name}.zone",
            "soa_mname": f"ns1.{name}.",
            "soa_rname": f"admin@{name}",
        }
        defaults.update(kwargs)
        return DNSZone(**defaults)


class CatalogZoneRecordGatingTest(TestCase):
    """Tests for which zone types accept user-managed records and for system-managed immutability."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.primary_zone = create_zone("primary.example")

    def test_primary_zone_type_allows_records(self):
        """A primary zone is the ordinary case: users manage its records directly."""
        self.assertTrue(DNSZone.zone_type_allows_records(self.primary_zone.zone_type))
        self.assertFalse(self.primary_zone.is_catalog_zone)

    def test_catalog_zone_type_allows_no_records(self):
        """A catalog maintains its own records and is identified as a catalog zone."""
        self.assertFalse(DNSZone.zone_type_allows_records(self.catalog_zone.zone_type))
        self.assertTrue(self.catalog_zone.is_catalog_zone)

    def test_record_fixtures_cover_every_record_model(self):
        """The hand-built fixtures below must keep pace with the record models discovered at runtime."""
        self.assertEqual(
            {type(record) for record in self._unsaved_records(self.catalog_zone)},
            set(dns_record_models()),
        )

    def test_unknown_zone_type_allows_no_records(self):
        """A zone type missing from the registry denies everything rather than defaulting to open."""
        zone = DNSZone(name="future.example", zone_type="future")
        self.assertFalse(DNSZone.zone_type_allows_records(zone.zone_type))
        self.assertFalse(zone.is_catalog_zone)

    def test_rejects_user_created_record_in_catalog_zone(self):
        """Validation refuses every record type a user could try to add to a catalog zone."""
        for record in self._unsaved_records(self.catalog_zone):
            with self.subTest(record_model=type(record).__name__):
                with self.assertRaises(ValidationError) as context:
                    record.full_clean()
                self.assertIn("system-managed", str(context.exception.message_dict["zone"]))

    def test_system_write_allows_record_in_catalog_zone(self):
        """The app's own sync code can write the records a user is forbidden to create."""
        with system_write():
            record = TXTRecord(name="group.nj2xg5b.zones", text="operators", zone=self.catalog_zone, _ttl=0)
            record.validated_save()
        self.assertTrue(TXTRecord.objects.filter(pk=record.pk).exists())

    def test_rejects_edit_of_catalog_record(self):
        """An existing catalog record cannot be edited through ordinary record validation."""
        record = self._version_record()
        record.text = "1"
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("system-managed", str(context.exception.message_dict["zone"]))

    def test_rejects_delete_of_catalog_record(self):
        """Deleting a catalog record one at a time is refused."""
        record = self._version_record()
        with self.assertRaises(ProtectedError):
            record.delete()
        self.assertTrue(TXTRecord.objects.filter(pk=record.pk).exists())

    def test_rejects_bulk_delete_of_catalog_record(self):
        """Bulk delete routes through QuerySet.delete(), which never reaches Model.delete()."""
        record = self._version_record()
        with self.assertRaises(ProtectedError):
            TXTRecord.objects.filter(pk=record.pk).delete()
        self.assertTrue(TXTRecord.objects.filter(pk=record.pk).exists())

    def test_system_write_allows_delete_of_catalog_record(self):
        """The app's own sync code can remove the records a user is forbidden to delete."""
        record = self._version_record()
        with system_write():
            record.delete()
        self.assertFalse(TXTRecord.objects.filter(pk=record.pk).exists())

    def test_deleting_catalog_zone_removes_its_records(self):
        """A catalog zone stays deletable despite holding records that refuse user deletes."""
        record = self._version_record()
        self.catalog_zone.delete()
        self.assertFalse(DNSZone.objects.filter(pk=self.catalog_zone.pk).exists())
        self.assertFalse(TXTRecord.objects.filter(pk=record.pk).exists())

    def test_bulk_deleting_catalog_zone_removes_its_records(self):
        """The same cleanup runs for the QuerySet.delete() path Nautobot's bulk delete job uses."""
        record = self._version_record()
        DNSZone.objects.filter(pk=self.catalog_zone.pk).delete()
        self.assertFalse(DNSZone.objects.filter(pk=self.catalog_zone.pk).exists())
        self.assertFalse(TXTRecord.objects.filter(pk=record.pk).exists())

    def test_primary_zone_with_records_remains_protected(self):
        """The cleanup is scoped to catalog zones; a primary zone still refuses to drop its records."""
        record = NSRecord.objects.create(name="ns1", server="ns1.primary.example.", zone=self.primary_zone)
        with self.assertRaises(ProtectedError):
            self.primary_zone.delete()
        self.assertTrue(NSRecord.objects.filter(pk=record.pk).exists())

    def _version_record(self):
        """Return the version TXT the zone created for itself, the one record a user may not touch."""
        return TXTRecord.objects.get(name="version", zone=self.catalog_zone)

    @staticmethod
    def _unsaved_records(zone):
        """Return one unsaved instance of every record type, all owned by `zone`."""
        return [
            AAAARecord(name="v6", zone=zone),
            ARecord(name="v4", zone=zone),
            CNAMERecord(name="alias", alias="target.example.", zone=zone),
            MXRecord(name="mail", mail_server="mx1.example.", zone=zone),
            NSRecord(name="sub", server="ns1.example.", zone=zone),
            PTRRecord(name="ptr", ptrdname="host.example.", zone=zone),
            SRVRecord(name="_sip._tcp", target="sip.example.", port=5060, zone=zone),
            TXTRecord(name="txt", text="value", zone=zone),
        ]


class CatalogZoneApexNSRecordTest(TestCase):
    """Tests for the apex NS RRset RFC 9432 §4 requires in every catalog zone."""

    def test_creating_catalog_zone_writes_the_apex_ns_record(self):
        """A new catalog zone carries `$CATZ 0 IN NS invalid.`, the RRset that makes it a valid zone."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        record = NSRecord.objects.get(zone=zone)
        self.assertEqual(record.name, APEX_RECORD_NAME)
        self.assertEqual(record.server, CATALOG_APEX_NS_SERVER)
        self.assertEqual(record.ttl, 0)

    def test_resaving_catalog_zone_does_not_duplicate_the_apex_ns_record(self):
        """The RRset holds the single RR the RFC recommends, so editing a zone adds none."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        zone.description = "Edited"
        zone.save()
        self.assertEqual(NSRecord.objects.filter(zone=zone).count(), 1)

    def test_saving_catalog_zone_restores_a_missing_apex_ns_record(self):
        """Saving repairs a catalog zone left without an NS RRset, which a server would refuse to load."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with system_write():
            NSRecord.objects.filter(zone=zone).delete()

        zone.save()

        self.assertEqual(NSRecord.objects.get(zone=zone).server, CATALOG_APEX_NS_SERVER)

    def test_saving_catalog_zone_drops_a_foreign_ns_record(self):
        """An NS naming anything else is removed, since the app owns this RRset outright."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with system_write():
            NSRecord(name="sub", server="ns1.example.", zone=zone, _ttl=0).validated_save()

        zone.save()

        self.assertEqual(
            [(record.name, record.server) for record in NSRecord.objects.filter(zone=zone)],
            [(APEX_RECORD_NAME, CATALOG_APEX_NS_SERVER)],
        )


class CatalogZoneVersionRecordTest(TestCase):
    """Tests for the version TXT record RFC 9432 §4.2.1 requires in every catalog zone."""

    def test_creating_catalog_zone_writes_the_version_record(self):
        """A new catalog zone carries `version.$CATZ 0 IN TXT "2"` without the user adding it."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        record = TXTRecord.objects.get(zone=zone)
        self.assertEqual(record.name, "version")
        self.assertEqual(record.text, "2")
        self.assertEqual(record.ttl, 0)

    def test_creating_primary_zone_writes_no_records(self):
        """The version record belongs to catalog zones alone."""
        zone = create_zone("primary.example")
        for record_model in dns_record_models():
            with self.subTest(record_model=record_model.__name__):
                self.assertFalse(record_model.objects.filter(zone=zone).exists())

    def test_resaving_catalog_zone_does_not_duplicate_the_version_record(self):
        """RFC 9432 §4.2.1 allows exactly one RR in the version RRset, so editing a zone adds none."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        zone.description = "Edited"
        zone.save()
        self.assertEqual(TXTRecord.objects.filter(name="version", zone=zone).count(), 1)

    def test_saving_catalog_zone_restores_a_missing_version_record(self):
        """Saving repairs a catalog zone whose version record was lost, since a consumer would reject it."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with system_write():
            TXTRecord.objects.filter(zone=zone).delete()

        zone.save()

        self.assertEqual(TXTRecord.objects.get(name="version", zone=zone).text, "2")

    def test_saving_catalog_zone_drops_a_foreign_schema_version_record(self):
        """A version RR from another schema version is removed, leaving the single RR the RFC allows."""
        zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with system_write():
            TXTRecord(name="version", text="1", zone=zone, _ttl=0).validated_save()

        zone.save()

        self.assertEqual([record.text for record in TXTRecord.objects.filter(name="version", zone=zone)], ["2"])


class CatalogMemberLabelTest(TestCase):
    """Tests for the opaque catalog member label generator."""

    def test_is_a_single_dns_safe_label(self):
        """Unpadded lowercase base32 of a UUID is 26 characters from [a-z2-7], inside RFC 1035 §3.1."""
        label = catalog_member_label()
        self.assertEqual(len(label), 26)
        self.assertRegex(label, r"^[a-z2-7]+$")
        self.assertNotIn("=", label)
        self.assertNotIn(".", label)

    def test_each_call_mints_a_new_identity(self):
        """Re-enrolling with a blank label must not silently resume prior consumer state."""
        self.assertNotEqual(catalog_member_label(), catalog_member_label())


class CatalogMembershipChangeLogTest(TestCase):
    """Tests that a membership is recorded against the zones it relates, not only the row itself."""

    def test_enrolling_records_a_change_against_both_zones(self):
        """Declaring the membership as an M2M through earns core's side-object change records."""
        catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        member_zone = create_zone("member.example")

        with web_request_context(self.user):
            CatalogZoneMembership(catalog_zone=catalog_zone, member_zone=member_zone).validated_save()

        self.assertTrue(ObjectChange.objects.filter(changed_object_id=member_zone.pk).exists())
        self.assertTrue(ObjectChange.objects.filter(changed_object_id=catalog_zone.pk).exists())

    def test_renaming_a_member_records_a_withdrawal_and_an_addition(self):
        """A rename is published as the removal of one catalog entry and the addition of another.

        The membership row is replaced, but it is not change-logged in its own right, so the
        member PTR records are where the history of a rename is legible: one deleted at the old
        label, one created at the new. A reader auditing the catalog sees what a consumer saw.
        """
        catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        member_zone = create_zone("member.example")
        membership = CatalogZoneMembership(catalog_zone=catalog_zone, member_zone=member_zone)
        membership.validated_save()
        old_pk = membership.pk
        old_label = membership.member_label

        with web_request_context(self.user):
            member_zone.name = "renamed.example"
            member_zone.validated_save()

        membership = CatalogZoneMembership.objects.get(member_zone=member_zone)
        self.assertNotEqual(membership.pk, old_pk)
        self.assertNotEqual(membership.member_label, old_label)
        self.assertFalse(CatalogZoneMembership.objects.filter(pk=old_pk).exists())
        ptr_changes = ObjectChange.objects.filter(
            changed_object_type=ContentType.objects.get_for_model(PTRRecord)
        ).values_list("action", "object_repr")
        self.assertEqual(
            set(ptr_changes),
            {("delete", "member.example"), ("create", "renamed.example")},
        )


class CatalogMembershipManagerTest(TestCase):
    """Tests the M2M manager shortcut, which reaches the through table without saving through it."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")

    def test_adding_enrolls_the_zone_and_publishes_it(self):
        """A manager add is a real membership, so it earns a label and a member record."""
        self.member_zone.catalogs.add(self.catalog_zone)

        membership = self.member_zone.catalog_memberships.get()
        self.assertEqual(len(membership.member_label), 26)
        self.assertTrue(
            PTRRecord.objects.filter(zone=self.catalog_zone, name=f"{membership.member_label}.zones").exists()
        )
        self.assertTrue(self.catalog_zone.has_members)

    def test_adding_from_the_catalog_end_enrolls_the_zone_too(self):
        """The reverse accessor writes the same row, so it is held to the same rules."""
        self.catalog_zone.members.add(self.member_zone)

        self.assertEqual(self.member_zone.catalog_memberships.get().catalog_zone, self.catalog_zone)

    def test_adding_several_zones_gives_each_its_own_label(self):
        """Bulk-created rows never reach save(), so the label has to come from the field default."""
        second_zone = create_zone("second.example")

        self.catalog_zone.members.add(self.member_zone, second_zone)

        labels = set(CatalogZoneMembership.objects.values_list("member_label", flat=True))
        self.assertEqual(len(labels), 2)

    def test_adding_refuses_to_nest_a_catalog_zone(self):
        """The manager cannot be used to write a membership the model would have rejected.

        Nothing is queried after the refusal: the rules are checked from `pre_add`, which Django
        runs inside an atomic block it opened without a savepoint, so raising there leaves any
        enclosing transaction unusable.
        """
        nested_catalog = create_zone("nested.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)

        with self.assertRaises(ValidationError) as context:
            self.catalog_zone.members.add(nested_catalog)

        self.assertIn("cannot be a member of another catalog zone", str(context.exception))

    def test_adding_refuses_a_zone_from_another_view(self):
        """View scoping holds on the manager path as it does on the membership."""
        other_zone = create_zone("other.example", dns_view=DNSView.objects.create(name="Other"))

        with self.assertRaises(ValidationError) as context:
            self.catalog_zone.members.add(other_zone)

        self.assertIn("same view", str(context.exception))

    def test_removing_withdraws_the_member_record(self):
        """Removal deletes the through row, which the post_delete receiver already answers for."""
        self.catalog_zone.members.add(self.member_zone)

        self.catalog_zone.members.remove(self.member_zone)

        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())
        self.assertFalse(self.catalog_zone.has_members)


class CatalogZoneMembershipTest(TestCase):
    """Tests for the membership model that enrolls a zone in a catalog zone."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")

    def test_label_is_generated_when_left_blank(self):
        """Leaving the label blank mints an opaque identity rather than demanding operator input."""
        membership = self._membership()
        self.assertEqual(len(membership.member_label), 26)
        self.assertRegex(membership.member_label, r"^[a-z2-7]+$")

    def test_label_is_generated_without_validation(self):
        """An ORM caller that skips full_clean() still gets a label, since save() cannot store a blank one."""
        membership = CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone)
        self.assertEqual(len(membership.member_label), 26)
        self.assertRegex(membership.member_label, r"^[a-z2-7]+$")

    def test_supplied_label_is_kept(self):
        """RFC 9432 §4.1 lets a producer pick any unique label, so an operator's choice stands."""
        membership = self._membership(member_label="chosen")
        self.assertEqual(membership.member_label, "chosen")

    def test_label_cannot_be_changed(self):
        """A consumer treats a relabelled member as a removal and re-addition, discarding its state."""
        membership = self._membership()
        membership.member_label = "renamed"
        with self.assertRaises(ValidationError) as context:
            membership.full_clean()
        self.assertIn("cannot be changed", str(context.exception.message_dict["member_label"]))

    def test_rejects_label_spanning_more_than_one_node(self):
        """The label names a single node under zones.$CATZ, so a dot would silently nest it deeper."""
        with self.assertRaises(ValidationError) as context:
            self._membership(member_label="two.labels")
        self.assertIn("single DNS label", str(context.exception.message_dict["member_label"]))

    def test_rejects_membership_in_a_non_catalog_zone(self):
        """Only a catalog zone publishes members."""
        primary_zone = create_zone("second.example")
        with self.assertRaises(ValidationError) as context:
            self._membership(catalog_zone=primary_zone)
        self.assertIn("only be added to a catalog zone", str(context.exception.message_dict["catalog_zone"]))

    def test_rejects_a_catalog_zone_as_a_member(self):
        """A consumer configures a member as an ordinary zone, so a nested catalog would go unread."""
        other_catalog = create_zone("other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with self.assertRaises(ValidationError) as context:
            self._membership(member_zone=other_catalog)
        self.assertIn("cannot be a member of another catalog zone", str(context.exception.message_dict["member_zone"]))

    def test_rejects_self_membership(self):
        """Reported on its own rather than as the less obvious complaint that a catalog cannot be a member."""
        with self.assertRaises(ValidationError) as context:
            self._membership(member_zone=self.catalog_zone)
        self.assertIn("cannot be a member of itself", str(context.exception.message_dict["member_zone"]))

    def test_rejects_a_member_zone_from_another_view(self):
        """A catalog and its members have to resolve in the same view to describe one nameserver's zones."""
        other_view = DNSView.objects.create(name="Other")
        member_elsewhere = create_zone("elsewhere.example", dns_view=other_view)
        with self.assertRaises(ValidationError) as context:
            self._membership(member_zone=member_elsewhere)
        self.assertIn("same view", str(context.exception.message_dict["member_zone"]))

    def test_rejects_a_second_membership_for_one_zone(self):
        """A zone belongs to at most one catalog, so two catalogs cannot both claim to provision it."""
        self._membership()
        other_catalog = create_zone("other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        with self.assertRaises(ValidationError) as context:
            self._membership(catalog_zone=other_catalog)
        self.assertIn("already belongs to a catalog zone", str(context.exception))

    def test_rejects_a_label_reused_within_one_catalog(self):
        """Two PTRs sharing a label make a catalog BIND 9.18.3 and later refuse to load."""
        self._membership(member_label="shared")
        other_member = create_zone("second.example")
        with self.assertRaises(ValidationError) as context:
            self._membership(member_zone=other_member, member_label="shared")
        self.assertIn("already used by another member", str(context.exception))

    def test_allows_the_same_label_in_a_different_catalog(self):
        """Labels are scoped to their catalog, so uniqueness beyond it would be a restriction the RFC does not make."""
        self._membership(member_label="shared")
        other_catalog = create_zone("other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        other_member = create_zone("second.example")
        membership = self._membership(catalog_zone=other_catalog, member_zone=other_member, member_label="shared")
        self.assertEqual(membership.member_label, "shared")

    def test_deleting_the_member_zone_removes_the_membership(self):
        """Membership is a property of the member zone, so it should not outlive it."""
        membership = self._membership()
        self.member_zone.delete()
        self.assertFalse(CatalogZoneMembership.objects.filter(pk=membership.pk).exists())

    def test_catalog_zone_cannot_be_deleted_while_it_has_members(self):
        """Losing a catalog silently unprovisions every member zone, so the members come out first."""
        self._membership()
        with self.assertRaises(ProtectedError):
            self.catalog_zone.delete()
        self.assertTrue(DNSZone.objects.filter(pk=self.catalog_zone.pk).exists())

    def _membership(self, **overrides):
        """Create and return a validated membership, defaulting to the fixture zones."""
        fields = {"catalog_zone": self.catalog_zone, "member_zone": self.member_zone}
        fields.update(overrides)
        membership = CatalogZoneMembership(**fields)
        membership.validated_save()
        return membership


class CatalogMembershipViewChangeTest(TestCase):
    """Tests that a zone taking part in a membership stays in the view that membership was made in.

    `CatalogZoneMembership` refuses a catalog and a member in different views, but nothing re-validates a
    stored membership when either of its zones moves, so the same rule has to hold from the zone side.
    """

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")
        cls.other_view = DNSView.objects.create(name="Other")

    def test_enrolled_member_cannot_change_view(self):
        """Moving an enrolled zone would leave its catalog publishing a member from another view."""
        membership = self._membership()

        self.member_zone.dns_view = self.other_view
        with self.assertRaises(ValidationError) as context:
            self.member_zone.validated_save()

        self.assertIn("cannot be moved to another view", str(context.exception.message_dict["dns_view"]))
        self.member_zone.refresh_from_db()
        self.assertEqual(self.member_zone.dns_view_id, self.catalog_zone.dns_view_id)
        self.assertTrue(CatalogZoneMembership.objects.filter(pk=membership.pk).exists())

    def test_catalog_with_members_cannot_change_view(self):
        """Moving a catalog would strand every zone it publishes in the view it left."""
        self._membership()

        self.catalog_zone.dns_view = self.other_view
        with self.assertRaises(ValidationError) as context:
            self.catalog_zone.validated_save()

        self.assertIn("cannot be moved to another view", str(context.exception.message_dict["dns_view"]))
        self.catalog_zone.refresh_from_db()
        self.assertEqual(self.catalog_zone.dns_view_id, self.member_zone.dns_view_id)

    def test_unenrolled_zone_can_change_view(self):
        """A zone in no membership has nothing holding it in place."""
        self.member_zone.dns_view = self.other_view
        self.member_zone.validated_save()

        self.member_zone.refresh_from_db()
        self.assertEqual(self.member_zone.dns_view_id, self.other_view.pk)

    def test_empty_catalog_can_change_view(self):
        """A catalog with no members publishes nothing that a move could strand."""
        self.catalog_zone.dns_view = self.other_view
        self.catalog_zone.validated_save()

        self.catalog_zone.refresh_from_db()
        self.assertEqual(self.catalog_zone.dns_view_id, self.other_view.pk)

    def test_enrolled_member_can_still_be_edited(self):
        """Only the view is pinned, so membership does not freeze the rest of the zone."""
        self._membership()

        self.member_zone.description = "still enrolled"
        self.member_zone.validated_save()

        self.member_zone.refresh_from_db()
        self.assertEqual(self.member_zone.description, "still enrolled")

    def _membership(self):
        """Enroll the fixture member in the fixture catalog."""
        membership = CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone)
        membership.validated_save()
        return membership


class CatalogMemberRecordSyncTest(TestCase):
    """Tests for the member PTR records a catalog zone publishes on behalf of its memberships."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")

    def test_membership_publishes_a_member_ptr(self):
        """RFC 9432 §4.1 publishes a member at `<label>.zones.$CATZ` pointing to the member zone."""
        membership = self._membership()
        record = PTRRecord.objects.get(zone=self.catalog_zone)
        self.assertEqual(record.name, f"{membership.member_label}.zones")
        self.assertEqual(record.ptrdname, "member.example")
        self.assertEqual(record.ttl, 0)

    def test_member_ptr_is_system_managed(self):
        """The PTR belongs to the membership, so ordinary record CRUD may not touch it."""
        self._membership()
        record = PTRRecord.objects.get(zone=self.catalog_zone)
        with self.assertRaises(ProtectedError):
            record.delete()

    def test_resaving_a_membership_publishes_no_duplicate(self):
        """That RRset must hold exactly one RR, so an edit cannot add a second."""
        membership = self._membership()
        membership.save()
        self.assertEqual(PTRRecord.objects.filter(zone=self.catalog_zone).count(), 1)

    def test_retargeting_a_membership_mints_a_new_label(self):
        """A label names the state a consumer holds for one zone, so another zone cannot inherit it.

        The same reset a rename calls for, reached by pointing the membership at a different zone
        rather than by renaming the one it already had.
        """
        membership = self._membership()
        original_label = membership.member_label
        membership.member_zone = create_zone("second.example")
        membership.validated_save()

        self.assertNotEqual(membership.member_label, original_label)
        self.assertEqual(
            {(record.name, record.ptrdname) for record in PTRRecord.objects.filter(zone=self.catalog_zone)},
            {(f"{membership.member_label}.zones", "second.example")},
        )

    def test_renaming_the_member_zone_republishes_it_under_the_new_label(self):
        """A PTR left at the old label would keep the old zone name in the catalog after the rename."""
        membership = self._membership()
        self.member_zone.name = "renamed.example"
        self.member_zone.validated_save()

        membership = CatalogZoneMembership.objects.get(member_zone=self.member_zone)
        self.assertEqual(
            {(record.name, record.ptrdname) for record in PTRRecord.objects.filter(zone=self.catalog_zone)},
            {(f"{membership.member_label}.zones", "renamed.example")},
        )

    def test_renaming_one_member_leaves_the_other_members_alone(self):
        """A rename reconciles the whole catalog, so the members it did not touch keep their labels."""
        first = self._membership()
        second = self._membership(member_zone=create_zone("second.example"))
        second_pk = second.pk
        second_label = second.member_label
        self.member_zone.name = "renamed.example"
        self.member_zone.validated_save()

        first = CatalogZoneMembership.objects.get(member_zone=self.member_zone)
        second.refresh_from_db()
        self.assertEqual(second.pk, second_pk)
        self.assertEqual(second.member_label, second_label)
        self.assertEqual(
            {(record.name, record.ptrdname) for record in PTRRecord.objects.filter(zone=self.catalog_zone)},
            {
                (f"{first.member_label}.zones", "renamed.example"),
                (f"{second_label}.zones", "second.example"),
            },
        )

    def test_moving_a_membership_between_catalogs_moves_the_ptr(self):
        """The catalog it left must stop advertising a member it no longer has."""
        membership = self._membership()
        other_catalog = create_zone("other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        membership.catalog_zone = other_catalog
        membership.validated_save()

        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())
        self.assertEqual(PTRRecord.objects.get(zone=other_catalog).ptrdname, "member.example")

    def test_deleting_a_membership_withdraws_the_ptr(self):
        """Withdrawing a zone has to stop a consumer from provisioning it."""
        membership = self._membership()
        membership.delete()
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())

    def test_bulk_deleting_memberships_withdraws_the_ptr(self):
        """Bulk delete routes through QuerySet.delete(), which sends post_delete per instance."""
        self._membership()
        CatalogZoneMembership.objects.all().delete()
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())

    def test_deleting_the_member_zone_withdraws_the_ptr(self):
        """The cascade destroys the membership without calling Model.delete(), which is why a receiver runs."""
        self._membership()
        self.member_zone.delete()
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())

    def test_two_members_each_get_their_own_ptr(self):
        """Reconciling the whole set must not disturb the members that did not change."""
        first = self._membership()
        second = self._membership(member_zone=create_zone("second.example"))
        self.assertEqual(
            {(record.name, record.ptrdname) for record in PTRRecord.objects.filter(zone=self.catalog_zone)},
            {
                (f"{first.member_label}.zones", "member.example"),
                (f"{second.member_label}.zones", "second.example"),
            },
        )

    def test_saving_the_catalog_zone_restores_a_missing_member_ptr(self):
        """The reconciler is the repair path for member records as much as for the version record."""
        membership = self._membership()
        with system_write():
            PTRRecord.objects.filter(zone=self.catalog_zone).delete()

        self.catalog_zone.save()

        self.assertEqual(PTRRecord.objects.get(zone=self.catalog_zone).name, f"{membership.member_label}.zones")

    def test_saving_the_catalog_zone_drops_a_second_rr_for_one_member(self):
        """A repeated owner name makes BIND 9.18.3 and later refuse the catalog, so the extra RR goes."""
        membership = self._membership()
        with system_write():
            PTRRecord(
                name=f"{membership.member_label}.zones", ptrdname="impostor.example", zone=self.catalog_zone, _ttl=0
            ).validated_save()

        self.catalog_zone.save()

        self.assertEqual(
            [record.ptrdname for record in PTRRecord.objects.filter(zone=self.catalog_zone)], ["member.example"]
        )

    def _membership(self, **overrides):
        """Create and return a validated membership, defaulting to the fixture zones."""
        fields = {"catalog_zone": self.catalog_zone, "member_zone": self.member_zone}
        fields.update(overrides)
        membership = CatalogZoneMembership(**fields)
        membership.validated_save()
        return membership
