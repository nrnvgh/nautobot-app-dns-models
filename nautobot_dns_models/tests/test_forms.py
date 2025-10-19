"""Tests for nautobot_dns_models Form Classes."""

from unittest import skip

from constance.test import override_config
from django.test import TestCase
from nautobot.extras.models.statuses import Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_dns_models import forms
from nautobot_dns_models.models import DNSView, DNSZone


class DNSViewFormTestCase(TestCase):
    """Test DNSView forms."""

    form_class = forms.DNSViewForm

    @classmethod
    def setUpTestData(cls):
        active_status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        cls.prefix = Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, status=active_status)

    def test_specifying_all_fields_success(self):
        form = self.form_class(
            data={"name": "Test View", "description": "Test Description", "prefixes": [self.prefix.pk]}
        )
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_only_required_success(self):
        form = self.form_class(data={"name": "Test View"})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_validate_name_dnsview_is_required(self):
        form = self.form_class(data={"description": "Test Description"})
        self.assertFalse(form.is_valid())
        self.assertIn("This field is required.", form.errors["name"])


class RecordNameFormNormalizationMixin:
    """Mixin for shared form normalization tests.

    Subclasses must define:
    - form_class: the ModelForm class under test.
    - build_valid_data(name: str) -> dict: returns a form data dict with all required fields for the record type,
      using the provided name.
    """

    @staticmethod
    def _strip_expected(data: dict) -> tuple[str, dict]:
        test_metadata = data.get("test_metadata")
        field_to_check = test_metadata.get("field_to_check")
        expected_value = test_metadata.get("expected_value")
        payload = {k: v for k, v in data.items() if k != "test_metadata"}
        return expected_value, payload, field_to_check

    @override_config(nautobot_dns_models__NORMALIZE_DNS_RECORDS=True)
    def test_record_fields_normalized_with_constance_config_normalize_true(self):
        """Record fields should be normalized when the constance config is set to True."""
        for normalization_data in self.normalization_data:
            expected_value, payload, field_to_check = self._strip_expected(normalization_data)
            with self.subTest(
                expected_value=expected_value,
                payload=payload,
                field_to_check=field_to_check
            ):
                print(f"expected_value: {expected_value}, payload: {payload}, field_to_check: {field_to_check}")
                form = self.form_class(payload)
                self.assertTrue(form.is_valid(), form.errors)
                instance = form.save()
                self.assertEqual(getattr(instance, field_to_check), expected_value)

    @override_config(nautobot_dns_models__NORMALIZE_DNS_RECORDS=False)
    def test_record_fields_fails_when_not_normalized_with_constance_config_normalize_false(self):
        """Record fields should not be normalized when the constance config is set to False."""
        for normalization_data in self.normalization_data:
            expected_value, payload, field_to_check = self._strip_expected(normalization_data)
            with self.subTest(
                expected_value=expected_value,
                payload=payload,
                field_to_check=field_to_check
            ):
                print(f"Subtest: {expected_value=}, {payload=}, {field_to_check=}")
                form = self.form_class(payload)
                self.assertFalse(form.is_valid())
                print(f"form.errors: [{form.errors.as_data()}]\n")
                self.assertIn(
                    "Field is not normalized.", 
                    str(form.errors.as_data().get(field_to_check))
                )


class DNSZoneTest(TestCase):
    """Test DNSZone forms."""

    def test_specifying_all_fields_success(self):
        form = forms.DNSZoneForm(
            data={
                "name": "development",
                "dns_view": DNSView.objects.get(name="Default").id,
                "description": "Development Testing",
                "ttl": 1010101,
                "filename": "development.zone",
                "soa_mname": "ns1.example.com",
                "soa_rname": "admin@example.com",
                "soa_refresh": 10800,
                "soa_retry": 3600,
                "soa_expire": 604800,
                "soa_serial": 202,
                "soa_minimum": 3600,
            }
        )
        form.is_valid()
        print(form.errors)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_only_required_success(self):
        form = forms.DNSZoneForm(
            data={
                "name": "development",
                "dns_view": DNSView.objects.get(name="Default").id,
                "ttl": 1010101,
                "filename": "development.zone",
                "soa_mname": "ns1.example.com",
                "soa_rname": "admin@example.com",
                "soa_refresh": 10800,
                "soa_retry": 3600,
                "soa_expire": 604800,
                "soa_serial": 202,
                "soa_minimum": 3600,
            }
        )
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_validate_name_dnszone_is_required(self):
        form = forms.DNSZoneForm(data={"ttl": "1010101"})
        self.assertFalse(form.is_valid())
        self.assertIn("This field is required.", form.errors["name"])


class NSRecordFormTestCase(TestCase):
    """Test NSRecord forms."""

    form_class = forms.NSRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_specifying_all_fields_success(self):
        data = {
            "name": "ns-record",
            "server": "ns-record-server",
            "description": "Development Testing",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_only_required_success(self):
        data = {
            "name": "ns-record",
            "server": "ns-record-server",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_zone_is_required(self):
        data = {
            "name": "ns-record",
            "server": "ns-record-server",
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors)
        self.assertIn("This field is required.", form.errors["zone"])

    @skip("Skipping because we need to update how normalization rules are applied to the form.")
    def test_name_normalized_on_form_save(self):
        """NSRecord.name should be normalized on save (base model)."""
        data = {
            "name": "NS/ Record _01",
            "server": "server.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.name, "ns-record-01")

    @skip("Skipping because we need to update how normalization rules are applied to the form.")
    def test_name_label_normalization_with_dots_on_form_save(self):
        """Per-label normalization preserves dots for NSRecord.name."""
        data = {
            "name": "Ns/_Rec_Ord.One___.Two",
            "server": "ns.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.name, "ns-rec-ord.one.two")

    @skip("Skipping this test for now as it is not implemented.")
    def test_server_normalized_on_form_save(self):
        """NSRecord.server should be normalized (domain-like field)."""
        data = {
            "name": "ns-record",
            "server": "Server/ Name _01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.server, "server-name-01.example.com")


class ARecordFormTestCase(RecordNameFormNormalizationMixin, TestCase):
    """Test ARecord forms."""

    form_class = forms.ARecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=status)

        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01",
                },
            },
            {
                "name": "Web/ App _01.Name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01.name",
                },
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "foo-bar-baz.quux.name",
                },
            },
        ]

    def test_specifying_only_required_success(self):
        data = {
            "name": "a-record",
            "address": self.ip_address,
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "a-record",
            "address": self.ip_address,
            "ttl": 3600,
            "zone": self.dns_zone,
            "comment": "example-comment",
            "description": "this is Gerasimo's description",
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())





    def test_ip_address_obj_is_required(self):
        data = {
            "name": "a-record",
            "address": "10.10.10.0/32",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors)
        self.assertIn("not a valid UUID.", form.errors["address"][0])


class AAAARecordFormTestCase(RecordNameFormNormalizationMixin, TestCase):
    """Test AAAARecord forms."""

    form_class = forms.AAAARecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="2001:db8:abcd:12::/64", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="2001:db8:abcd:12::1/128", namespace=namespace, status=status)
        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01",
                },
            },
            {
                "name": "Web/ App _01.Name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01.name",
                },
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "address": cls.ip_address,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "foo-bar-baz.quux.name",
                },
            },
        ]

    def test_specifying_only_required_success(self):
        data = {
            "name": "aaaa-record",
            "address": self.ip_address,
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "aaaa-record",
            "address": self.ip_address,
            "ttl": 3600,
            "zone": self.dns_zone,
            "comment": "example-comment",
            "description": "this is Gerasimo's description",
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_ip_address_obj_is_required(self):
        data = {
            "name": "aaaa-record",
            "address": "10.10.10.0/32",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors)




class CNAMERecordFormTestCase(RecordNameFormNormalizationMixin, TestCase):
    """Test CNAMERecord forms."""

    form_class = forms.CNAMERecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "alias": "alias.example.com",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01",
                },
            },
            {
                "name": "Web/ App _01.Name",
                "alias": "alias.example.com",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01.name",
                },
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "alias": "alias.example.com",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "foo-bar-baz.quux.name",
                },
            },
            {
                "name": "cname-record",
                "alias": "Alias/ Name _01.Example.COM",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "alias",
                    "expected_value": "alias-name-01.example.com",
                },
            },
        ]

    def test_specifying_only_required_success(self):
        data = {
            "name": "cname-record",
            "alias": "cname-alias",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "cname-record",
            "alias": "cname-alias",
            "ttl": 3600,
            "zone": self.dns_zone,
            "description": "this is a cname description",
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())



    @skip("Skipping this test for now as it is not implemented.")
    def test_alias_normalized_on_form_save(self):
        """CNAMERecord.alias should be normalized (domain-like field)."""
        data = {
            "name": "cname-record",
            "alias": "Alias/ Name _01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.alias, "alias-name-01.example.com")

    @skip("Skipping this test for now as it is not implemented.")
    def test_alias_label_normalization_with_dots_on_form_save(self):
        """Per-label normalization preserves dots for CNAMERecord.alias."""
        data = {
            "name": "cname-record",
            "alias": "Alias/_Name 01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.alias, "alias-name-01.example.com")


class MXRecordFormTestCase(RecordNameFormNormalizationMixin, TestCase):
    """Test MXRecord forms."""

    form_class = forms.MXRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "mail_server": "mail.example.com",
                "preference": 10,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01",
                },
            },
            {
                "name": "Web/ App _01.Name",
                "mail_server": "mail.example.com",
                "preference": 10,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01.name",
                },
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "mail_server": "mail.example.com",
                "preference": 10,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "foo-bar-baz.quux.name",
                },
            },
        ]
 
    def test_specifying_only_required_success(self):
        data = {
            "name": "mx-record",
            "preference": 10,
            "mail_server": "mail-server.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "mx-record",
            "preference": 10,
            "mail_server": "mail-server.com",
            "ttl": 3600,
            "zone": self.dns_zone,
            "description": "this is a boring description",
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

 

    @skip("Skipping this test for now as it is not implemented.")
    def test_mail_server_normalized_on_form_save(self):
        """MXRecord.mail_server should be normalized (domain-like field)."""
        data = {
            "name": "mx-record",
            "preference": 10,
            "mail_server": "Mail/ Server _01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.mail_server, "mail-server-01.example.com")

    @skip("Skipping this test for now as it is not implemented.")
    def test_mail_server_label_normalization_with_dots_on_form_save(self):
        """Per-label normalization preserves dots for MXRecord.mail_server."""
        data = {
            "name": "mx-record",
            "preference": 10,
            "mail_server": "Mail/_Server 01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.mail_server, "mail-server-01.example.com")


class TXTRecordFormTestCase(RecordNameFormNormalizationMixin, TestCase):
    """Test TXTRecord forms."""

    form_class = forms.TXTRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "text": "spf-record",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01",
                },
            },
            {
                "name": "Web/ App _01.Name",
                "text": "spf-record",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01.name",
                },
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "text": "spf-record",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "foo-bar-baz.quux.name",
                },
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "text": "spf-record with spaces",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "foo-bar-baz.quux.name",
                },
            },
        ]

    def test_specifying_only_required_success(self):
        data = {
            "name": "txt-record",
            "text": "spf record",
            "ttl": 3600,
            "zone": self.dns_zone,

        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "txt-record",
            "text": "spf record",
            "ttl": 3600,
            "zone": self.dns_zone,
            "description": "this is a boring description",
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())




class PTRRecordFormTestCase(RecordNameFormNormalizationMixin, TestCase):
    """Test PTRRecord forms."""

    form_class = forms.PTRRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

        cls.normalization_data = [
            {
                "name": "Web/ App _01",
                "ptrdname": "ptr-record",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01",
                },
            },
            {
                "name": "Web/ App _01.Name",
                "ptrdname": "ptr-record",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "web-app-01.name",
                },
            },
            {
                "name": "Foo/_Bar  Baz.Quux___.Name",
                "ptrdname": "ptr-record",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "foo-bar-baz.quux.name",
                },
            },
        ]

    def test_specifying_only_required_success(self):
        data = {
            "name": "ptr-record",
            "ptrdname": "ptr-record",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "ptr-record",
            "ptrdname": "ptr-record",
            "ttl": 3600,
            "comment": "example-comment",
            "zone": self.dns_zone,
            "description": "this is a boring description",
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    @skip("Skipping this test for now as it is not implemented.")
    def test_ptrdname_normalized_on_form_save(self):
        """PTRRecord.ptrdname should be normalized (domain-like field)."""
        data = {
            "name": "ptr-record",
            "ptrdname": "PTR/ Name _01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.ptrdname, "ptr-name-01.example.com")


    @skip("Skipping this test for now as it is not implemented.")
    def test_ptrdname_label_normalization_with_dots_on_form_save(self):
        """Per-label normalization preserves dots for PTRRecord.ptrdname."""
        data = {
            "name": "ptr-record",
            "ptrdname": "Ptr/_Name 01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.ptrdname, "ptr-name-01.example.com")


class SRVRecordFormTestCase(RecordNameFormNormalizationMixin, TestCase):
    """Test SRVRecord forms."""

    form_class = forms.SRVRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        cls.normalization_data = [
            {
                "name": "_Kerberos._TCP.DC._msdcs_",
                "priority": 10,
                "weight": 5,
                "port": 88,
                "target": "server.example.com",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "_kerberos._tcp.dc._msdcs",
                }
            },
            {
                "name": "_Http._TcP.Service/ Name 01",
                "priority": 10,
                "weight": 5,
                "port": 8080,
                "target": "server.example.com",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "_http._tcp.service-name-01",
                }
            },
            {
                "name": "_Http._TCP.Service/ Name 01.Name",
                "priority": 10,
                "weight": 5,
                "port": 8080,
                "target": "server.example.com",
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "name",
                    "expected_value": "_http._tcp.service-name-01.name",
                }
            },
            {
                "name": "_http._tcp.service",
                "priority": 10,
                "weight": 5,
                "port": 8080,
                "target": "Target/ Host _01.Example.COM",
                "ttl": 3600,
                "zone": cls.dns_zone,
                "test_metadata": {
                    "field_to_check": "target",
                    "expected_value": "target-host-01.example.com",
                },
            },
        ]

    def test_specifying_only_required_success(self):
        data = {
            "name": "srv-record",
            "priority": 10,
            "weight": 5,
            "port": 8080,
            "target": "server.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "srv-record",
            "priority": 10,
            "weight": 5,
            "port": 8080,
            "target": "server.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
            "description": "this is an srv description",
            "comment": "example-comment",
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_validate_priority_range(self):
        data = {
            "name": "srv-record",
            "priority": 65536,  # Invalid priority (max is 65535)
            "weight": 5,
            "port": 8080,
            "target": "server.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertIn("Ensure this value is less than or equal to 65535.", form.errors["priority"])

    def test_validate_weight_range(self):
        data = {
            "name": "srv-record",
            "priority": 10,
            "weight": 65536,  # Invalid weight (max is 65535)
            "port": 8080,
            "target": "server.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertIn("Ensure this value is less than or equal to 65535.", form.errors["weight"])

    def test_validate_port_range(self):
        data = {
            "name": "srv-record",
            "priority": 10,
            "weight": 5,
            "port": 65536,  # Invalid port (max is 65535)
            "target": "server.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertIn("Ensure this value is less than or equal to 65535.", form.errors["port"])

    def test_zone_is_required(self):
        data = {
            "name": "srv-record",
            "priority": 10,
            "weight": 5,
            "port": 8080,
            "target": "server.example.com",
            "ttl": 3600,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertIn("This field is required.", form.errors["zone"])

    def test_validate_negative_values(self):
        data = {
            "name": "srv-record",
            "priority": -1,  # Invalid priority (min is 0)
            "weight": -1,  # Invalid weight (min is 0)
            "port": -1,  # Invalid port (min is 0)
            "target": "server.example.com",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertIn("Ensure this value is greater than or equal to 0.", form.errors["priority"])
        self.assertIn("Ensure this value is greater than or equal to 0.", form.errors["weight"])
        self.assertIn("Ensure this value is greater than or equal to 0.", form.errors["port"])

    #
    # TODO: figure out how to roll arbritrary field normalizatoin tests into the mixin.
    @skip("Skipping this test for now as it is not implemented.")
    def test_target_normalized_on_form_save(self):
        """SRVRecord.target should be normalized (domain-like field)."""
        data = {
            "name": "_http._tcp.service",
            "priority": 10,
            "weight": 5,
            "port": 8080,
            "target": "Target/ Host _01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.target, "target-host-01.example.com")

    @skip("Skipping this test for now as it is not implemented.")
    def test_target_label_normalization_with_dots_on_form_save(self):
        """Per-label normalization preserves dots for SRVRecord.target."""
        data = {
            "name": "_http._tcp.service",
            "priority": 10,
            "weight": 5,
            "port": 8080,
            "target": "Target/_Host 01.Example.COM",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        instance = form.save()
        self.assertEqual(instance.target, "target-host-01.example.com")

        instance = form.save()
        self.assertEqual(instance.target, "target-host-01.example.com")
