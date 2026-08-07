"""Tests for nautobot_dns_models Form Classes."""

from django.test import TestCase
from nautobot.extras.models.statuses import Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_dns_models import forms, models
from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.models import DNSRegistrar, DNSView, DNSZone


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


class DNSZoneFormTestCase(TestCase):
    """Test DNSZone forms."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_view = DNSView.objects.get(name="Default")

    def test_specifying_all_fields_success(self):
        registrar = DNSRegistrar.objects.create(
            name="Registrar One",
            url="https://registrar.example",
            account_number="ACC-100",
        )
        form = forms.DNSZoneForm(
            data=self._zone_data(
                dns_registrar=registrar.id,
                description="Development Testing",
                expiration_date="2026-12-31",
                auto_renewal=True,
                registry_locked=True,
                transfer_locked=True,
                privacy_enabled=True,
                website_forwarding_enabled=True,
                renewal_term_months=24,
                dnssec_enabled=True,
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save())

    def test_specifying_only_required_success(self):
        form = forms.DNSZoneForm(data=self._zone_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save())

    def test_soa_rname_accepts_value_without_at_sign(self):
        form = forms.DNSZoneForm(
            data=self._zone_data(
                name="Catalog",
                filename="catalog.zone",
                soa_mname="invalid.",
                soa_rname="invalid.",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        # Single-label placeholder is stored without a trailing dot
        self.assertEqual(form.save().soa_rname, "invalid")

    def test_validate_name_dnszone_is_required(self):
        form = forms.DNSZoneForm(data={"ttl": "1010101"})
        self.assertFalse(form.is_valid())
        self.assertIn("This field is required.", form.errors["name"])

    def test_expiration_date_accepts_date_picker_value(self):
        form = forms.DNSZoneForm(data=self._zone_data(expiration_date="2026-12-31"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_can_create_catalog_zone(self):
        form = forms.DNSZoneForm(data=self._zone_data(zone_type=DNSZoneTypeChoices.TYPE_CATALOG))
        self.assertTrue(form.is_valid(), form.errors)
        zone = form.save()
        self.assertEqual(zone.zone_type, DNSZoneTypeChoices.TYPE_CATALOG)

    def test_rejects_auto_create_ptr_on_catalog_zone(self):
        form = forms.DNSZoneForm(data=self._zone_data(zone_type=DNSZoneTypeChoices.TYPE_CATALOG, auto_create_ptr=True))
        self.assertFalse(form.is_valid())
        self.assertIn("cannot enable automatic PTR creation", str(form.errors["auto_create_ptr"]))

    def test_zone_type_is_disabled_when_editing(self):
        zone = DNSZone.objects.create(name="existing.example")
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["zone_type"].disabled)

    def test_zone_type_is_enabled_when_creating(self):
        form = forms.DNSZoneForm()
        self.assertFalse(form.fields["zone_type"].disabled)

    def test_submitted_zone_type_is_ignored_when_editing(self):
        """A disabled field falls back to the instance value, so an attempted change is a no-op rather than an error."""
        zone = DNSZone.objects.create(name="existing.example")
        form = forms.DNSZoneForm(
            instance=zone,
            data=self._zone_data(name=zone.name, zone_type=DNSZoneTypeChoices.TYPE_CATALOG),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().zone_type, DNSZoneTypeChoices.TYPE_PRIMARY)

    def test_auto_create_ptr_is_disabled_when_editing_catalog_zone(self):
        zone = DNSZone.objects.create(name="catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["auto_create_ptr"].disabled)

    def test_auto_create_ptr_is_enabled_when_editing_primary_zone(self):
        zone = DNSZone.objects.create(name="primary.example")
        form = forms.DNSZoneForm(instance=zone)
        self.assertFalse(form.fields["auto_create_ptr"].disabled)

    def test_can_enroll_a_new_zone_in_a_catalog(self):
        """Enrolling at creation saves the operator a second trip through Catalog Zone Members."""
        catalog_zone = self._catalog_zone()
        form = forms.DNSZoneForm(data=self._zone_data(catalog=catalog_zone.pk))
        self.assertTrue(form.is_valid(), form.errors)

        zone = form.save()

        self.assertEqual(zone.catalog, catalog_zone)
        self.assertTrue(models.PTRRecord.objects.filter(zone=catalog_zone).exists())

    def test_creating_a_zone_without_a_catalog_enrolls_it_nowhere(self):
        form = forms.DNSZoneForm(data=self._zone_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().catalog)

    def test_rejects_a_catalog_for_a_catalog_zone(self):
        """Nesting is refused here as it is on the membership model."""
        form = forms.DNSZoneForm(
            data=self._zone_data(zone_type=DNSZoneTypeChoices.TYPE_CATALOG, catalog=self._catalog_zone().pk)
        )
        self.assertFalse(form.is_valid())
        self.assertIn("cannot be a member of another catalog zone", str(form.errors["catalog"]))

    def test_rejects_a_catalog_that_is_not_a_catalog_zone(self):
        """The picker filters by zone type, so only a hand-built payload reaches this."""
        form = forms.DNSZoneForm(data=self._zone_data(catalog=DNSZone.objects.create(name="primary.example").pk))
        self.assertFalse(form.is_valid())
        self.assertIn("not a catalog zone", str(form.errors["catalog"]))

    def test_rejects_a_catalog_in_another_view(self):
        other_view = DNSView.objects.create(name="Other")
        catalog_zone = DNSZone.objects.create(
            name="catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG, dns_view=other_view
        )
        form = forms.DNSZoneForm(data=self._zone_data(catalog=catalog_zone.pk))
        self.assertFalse(form.is_valid())
        self.assertIn("same view", str(form.errors["catalog"]))

    def test_editing_shows_the_current_catalog(self):
        zone, catalog_zone = self._enrolled_zone()
        self.assertEqual(forms.DNSZoneForm(instance=zone).initial["catalog"], catalog_zone)

    def test_editing_moves_the_zone_to_another_catalog(self):
        """The membership is reused, so the member label a consumer keys on survives the move."""
        zone, _ = self._enrolled_zone()
        member_label = zone.catalog_membership.get().member_label
        other_catalog = DNSZone.objects.create(name="other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)

        form = forms.DNSZoneForm(instance=zone, data=self._zone_data(name=zone.name, catalog=other_catalog.pk))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        membership = zone.catalog_membership.get()
        self.assertEqual(membership.catalog_zone, other_catalog)
        self.assertEqual(membership.member_label, member_label)

    def test_editing_withdraws_the_zone_from_its_catalog(self):
        zone, catalog_zone = self._enrolled_zone()

        form = forms.DNSZoneForm(instance=zone, data=self._zone_data(name=zone.name, catalog=""))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertFalse(zone.catalog_membership.exists())
        self.assertFalse(models.PTRRecord.objects.filter(zone=catalog_zone).exists())

    def test_catalog_is_disabled_when_editing_catalog_zone(self):
        zone = DNSZone.objects.create(name="catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["catalog"].disabled)

    def test_catalog_is_enabled_when_editing_primary_zone(self):
        zone = DNSZone.objects.create(name="primary.example")
        form = forms.DNSZoneForm(instance=zone)
        self.assertFalse(form.fields["catalog"].disabled)

    def _catalog_zone(self, **overrides):
        """Create and return a catalog zone in the view the form payload uses."""
        fields = {"name": "catalog.example", "zone_type": DNSZoneTypeChoices.TYPE_CATALOG}
        fields.update(overrides)
        return DNSZone.objects.create(**fields)

    def _enrolled_zone(self):
        """Create a zone already enrolled in a catalog, returning both."""
        catalog_zone = self._catalog_zone()
        zone = DNSZone.objects.create(name="member.example")
        models.CatalogZoneMember(catalog_zone=catalog_zone, member_zone=zone).validated_save()
        return zone, catalog_zone

    def _zone_data(self, **overrides):
        """Return a valid DNSZoneForm payload, with any supplied overrides applied."""
        data = {
            "name": "Development",
            "zone_type": DNSZoneTypeChoices.TYPE_PRIMARY,
            "dns_view": self.dns_view.id,
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
        data.update(overrides)
        return data


class CatalogZoneMemberFormTestCase(TestCase):
    """Test CatalogZoneMember forms."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = DNSZone.objects.create(name="catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = DNSZone.objects.create(name="member.example")

    def test_specifying_only_required_success(self):
        """The model mints the opaque member label; the form never asks for one."""
        form = forms.CatalogZoneMemberForm(
            data={"catalog_zone": self.catalog_zone.pk, "member_zone": self.member_zone.pk}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(len(form.save().member_label), 26)

    def test_member_label_is_not_on_the_form(self):
        """Create and edit both omit the label; a chosen value is an API concern."""
        self.assertNotIn("member_label", forms.CatalogZoneMemberForm().fields)
        self.assertNotIn("member_label", forms.CatalogZoneMemberForm(instance=self._membership()).fields)

    def test_submitted_member_label_is_ignored(self):
        """Extra POST data cannot smuggle a label past the form's declared fields."""
        form = forms.CatalogZoneMemberForm(
            data={
                "catalog_zone": self.catalog_zone.pk,
                "member_zone": self.member_zone.pk,
                "member_label": "chosen",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotEqual(form.save().member_label, "chosen")

    def test_rejects_a_non_catalog_zone_as_the_catalog(self):
        """The picker only offers catalog zones, and the model enforces that against a hand-built POST."""
        form = forms.CatalogZoneMemberForm(
            data={"catalog_zone": self.member_zone.pk, "member_zone": self.catalog_zone.pk}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Members can only be added to a catalog zone.", str(form.errors["catalog_zone"]))

    def test_editing_preserves_the_stored_member_label(self):
        """Moving a membership between catalogs must not remint the consumer-facing identity."""
        membership = self._membership()
        other_catalog = models.DNSZone.objects.create(
            name="other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG
        )
        form = forms.CatalogZoneMemberForm(
            instance=membership,
            data={
                "catalog_zone": other_catalog.pk,
                "member_zone": self.member_zone.pk,
                "member_label": "rewritten",
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().member_label, membership.member_label)

    def test_creating_offers_only_unenrolled_member_zones(self):
        """Without `coo`, a zone belongs to one catalog, so an enrolled zone could only fail validation."""
        self.assertEqual(self._member_zone_availability(forms.CatalogZoneMemberForm()), '["true"]')

    def test_editing_keeps_the_current_member_zone_selectable(self):
        """Every enrolled zone is filtered out of the picker, and this membership's own is one of them."""
        membership = self._membership()
        form = forms.CatalogZoneMemberForm(instance=membership)
        self.assertEqual(self._member_zone_availability(form), f'["{membership.pk}"]')

    def _member_zone_availability(self, form):
        """Return the availability query parameter the member zone picker sends."""
        return form.fields["member_zone"].widget.attrs["data-query-param-available_for_catalog_membership"]

    def _membership(self):
        """Create and return a membership joining the fixture zones."""
        return models.CatalogZoneMember.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone)


class DNSRegistrarFormTestCase(TestCase):
    """Test DNSRegistrar forms."""

    form_class = forms.DNSRegistrarForm

    def test_specifying_all_fields_success(self):
        form = self.form_class(
            data={
                "name": "Registrar Test",
                "url": "https://registrar.test",
                "account_number": "REG-100",
            }
        )
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_only_required_success(self):
        form = self.form_class(data={"name": "Registrar Required"})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_validate_name_is_required(self):
        form = self.form_class(data={"url": "https://registrar.test"})
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

    # Testing the record `enabled` field here. If it works for NSRecord, it works for all other record types.
    def test_enabled_is_checked_by_default(self):
        """A new record form offers `enabled` pre-checked, matching the model default."""
        self.assertTrue(self.form_class().fields["enabled"].initial)

    def test_enabled_can_be_unchecked(self):
        """Submitting the form without `enabled` saves a disabled record."""
        data = {
            "name": "ns-record",
            "server": "ns-record-server",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.save().enabled)

    def test_enabled_can_be_checked(self):
        """Submitting the form with `enabled` saves an enabled record."""
        data = {
            "name": "ns-record",
            "server": "ns-record-server",
            "ttl": 3600,
            "zone": self.dns_zone,
            "enabled": True,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save().enabled)


class ARecordFormTestCase(TestCase):
    """Test ARecord forms."""

    form_class = forms.ARecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=status)

    def test_specifying_only_required_success(self):
        data = {
            "name": "a-record",
            "ip_address": self.ip_address,
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "a-record",
            "ip_address": self.ip_address,
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
            "ip_address": "10.10.10.0/32",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors)
        self.assertIn("not a valid UUID.", form.errors["ip_address"][0])


class AAAARecordFormTestCase(TestCase):
    """Test AAAARecord forms."""

    form_class = forms.AAAARecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="2001:db8:abcd:12::/64", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="2001:db8:abcd:12::1/128", namespace=namespace, status=status)

    def test_specifying_only_required_success(self):
        data = {
            "name": "aaaa-record",
            "ip_address": self.ip_address,
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save())

    def test_specifying_all_fields_success(self):
        data = {
            "name": "aaaa-record",
            "ip_address": self.ip_address,
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
            "ip_address": "10.10.10.0/32",
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors)


class CNAMERecordFormTestCase(TestCase):
    """Test CNAMERecord forms."""

    form_class = forms.CNAMERecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

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


class MXRecordFormTestCase(TestCase):
    """Test MXRecord forms."""

    form_class = forms.MXRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

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


class TXTRecordFormTestCase(TestCase):
    """Test TXTRecord forms."""

    form_class = forms.TXTRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

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


class PTRRecordFormTestCase(TestCase):
    """Test PTRRecord forms."""

    form_class = forms.PTRRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

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


class SRVRecordFormTestCase(TestCase):
    """Test SRVRecord forms."""

    form_class = forms.SRVRecordForm

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

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
