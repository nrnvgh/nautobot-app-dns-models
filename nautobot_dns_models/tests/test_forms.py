"""Tests for nautobot_dns_models Form Classes."""

import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from nautobot.extras.context_managers import web_request_context
from nautobot.extras.models import ObjectChange
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


class DNSZoneFormPayloadMixin:
    """The base form payload the DNSZone form suites post, which each of them varies."""

    def _zone_data(self, **overrides):
        """Return a valid DNSZoneForm payload, with any supplied overrides applied."""
        data = {
            "name": "Development",
            "type": DNSZoneTypeChoices.TYPE_PRIMARY,
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


class DNSZoneFormTestCase(DNSZoneFormPayloadMixin, TestCase):
    """Test DNSZone forms."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_view = DNSView.objects.get(name="Default")

    def test_specifying_all_fields_success(self):
        registrar = DNSRegistrar.objects.create(
            name="Registrar One",
            portal_url="https://registrar.example",
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
        form = forms.DNSZoneForm(data=self._zone_data(type=DNSZoneTypeChoices.TYPE_CATALOG))
        self.assertTrue(form.is_valid(), form.errors)
        zone = form.save()
        self.assertEqual(zone.type, DNSZoneTypeChoices.TYPE_CATALOG)

    def test_rejects_auto_create_ptr_on_catalog_zone(self):
        form = forms.DNSZoneForm(data=self._zone_data(type=DNSZoneTypeChoices.TYPE_CATALOG, auto_create_ptr=True))
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["auto_create_ptr"][0],
            "Catalog zones cannot enable automatic PTR creation.",
        )

    def test_zone_type_is_disabled_when_editing(self):
        zone = DNSZone.objects.create(name="existing.example")
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["type"].disabled)

    def test_zone_type_is_enabled_when_creating(self):
        form = forms.DNSZoneForm()
        self.assertFalse(form.fields["type"].disabled)

    def test_submitted_zone_type_is_ignored_when_editing(self):
        """A disabled field falls back to the instance value, so an attempted change is a no-op rather than an error."""
        zone = DNSZone.objects.create(name="existing.example")
        form = forms.DNSZoneForm(
            instance=zone,
            data=self._zone_data(name=zone.name, type=DNSZoneTypeChoices.TYPE_CATALOG),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().type, DNSZoneTypeChoices.TYPE_PRIMARY)

    def test_auto_create_ptr_is_disabled_when_editing_catalog_zone(self):
        zone = DNSZone.objects.create(name="catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["auto_create_ptr"].disabled)

    def test_auto_create_ptr_is_enabled_when_editing_primary_zone(self):
        zone = DNSZone.objects.create(name="primary.example")
        form = forms.DNSZoneForm(instance=zone)
        self.assertFalse(form.fields["auto_create_ptr"].disabled)


class DNSZoneFormCatalogFieldTestCase(DNSZoneFormPayloadMixin, TestCase):
    """Test the DNSZoneForm catalog field, which enrolls the zone as it is saved."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_view = DNSView.objects.get(name="Default")

    def test_can_enroll_a_new_zone_in_a_catalog(self):
        """Enrolling at creation saves the operator a second trip through Catalog Zone Memberships."""
        catalog_zone = self._catalog_zone()
        form = forms.DNSZoneForm(data=self._zone_data(catalog=catalog_zone.pk))
        self.assertTrue(form.is_valid(), form.errors)

        zone = form.save()

        self.assertEqual(zone.catalog, catalog_zone)
        self.assertTrue(models.PTRRecord.objects.filter(zone=catalog_zone).exists())

    def test_enrolling_an_existing_zone_logs_its_catalog(self):
        """The change log names the catalog joined, though the edit view's zone has its memberships prefetched."""
        catalog_zone = self._catalog_zone()
        DNSZone.objects.create(name="member.example")
        zone = DNSZone.objects.prefetch_related("catalog_memberships__catalog_zone").get(name="member.example")
        form = forms.DNSZoneForm(instance=zone, data=self._zone_data(name=zone.name, catalog=catalog_zone.pk))
        self.assertTrue(form.is_valid(), form.errors)

        with web_request_context(get_user_model().objects.create(username="editor")):
            form.save()

        change = ObjectChange.objects.get(changed_object_id=zone.pk)
        self.assertEqual(change.object_data_v2["catalog"]["id"], str(catalog_zone.pk))

    def test_creating_a_zone_without_a_catalog_enrolls_it_nowhere(self):
        form = forms.DNSZoneForm(data=self._zone_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().catalog)

    def test_rejects_a_catalog_for_a_catalog_zone(self):
        """Nesting is refused here as it is on the membership model."""
        form = forms.DNSZoneForm(
            data=self._zone_data(type=DNSZoneTypeChoices.TYPE_CATALOG, catalog=self._catalog_zone().pk)
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["catalog"][0],
            "A catalog zone cannot be a member of another catalog zone.",
        )

    def test_rejects_a_catalog_that_is_not_a_catalog_zone(self):
        """The picker filters by zone type, so only a hand-built payload reaches this."""
        form = forms.DNSZoneForm(data=self._zone_data(catalog=DNSZone.objects.create(name="primary.example").pk))
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["catalog"][0], "The selected zone is not a catalog zone.")

    def test_rejects_a_catalog_in_another_view(self):
        other_view = DNSView.objects.create(name="Other")
        catalog_zone = DNSZone.objects.create(
            name="catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG, dns_view=other_view
        )
        form = forms.DNSZoneForm(data=self._zone_data(catalog=catalog_zone.pk))
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["catalog"][0],
            "The catalog zone must be in the same view as this zone.",
        )

    def test_editing_shows_the_current_catalog(self):
        zone, catalog_zone = self._enrolled_zone()
        self.assertEqual(forms.DNSZoneForm(instance=zone).initial["catalog"], catalog_zone)

    def test_editing_ignores_a_submitted_catalog_change(self):
        """A submitted replacement catalog leaves the enrolled zone's catalog and member label unchanged."""
        zone, catalog_zone = self._enrolled_zone()
        member_label = zone.catalog_memberships.get().member_label
        other_catalog = DNSZone.objects.create(name="other-catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)

        form = forms.DNSZoneForm(instance=zone, data=self._zone_data(name=zone.name, catalog=other_catalog.pk))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        membership = zone.catalog_memberships.get()
        self.assertEqual(membership.catalog_zone, catalog_zone)
        self.assertEqual(membership.member_label, member_label)

    def test_editing_ignores_a_submitted_catalog_clear(self):
        """Clearing the disabled catalog field leaves the membership and its published PTR in place."""
        zone, catalog_zone = self._enrolled_zone()

        form = forms.DNSZoneForm(instance=zone, data=self._zone_data(name=zone.name, catalog=""))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertTrue(zone.catalog_memberships.exists())
        self.assertTrue(models.PTRRecord.objects.filter(zone=catalog_zone).exists())

    def test_editing_ignores_a_submitted_view_for_a_catalog_with_members(self):
        """A catalog zone's own form is the one UI path that could otherwise strand the members it publishes.

        The disabled field keeps the stored view, so a hand-built payload cannot move the zone.
        """
        member_zone, catalog_zone = self._enrolled_zone()
        other_view = DNSView.objects.create(name="Other")

        form = forms.DNSZoneForm(
            instance=catalog_zone,
            data=self._zone_data(
                name=catalog_zone.name,
                type=DNSZoneTypeChoices.TYPE_CATALOG,
                dns_view=other_view.pk,
            ),
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        catalog_zone.refresh_from_db()
        self.assertEqual(catalog_zone.dns_view_id, member_zone.dns_view_id)

    def test_editing_ignores_a_submitted_view_for_an_enrolled_zone(self):
        zone, catalog_zone = self._enrolled_zone()
        other_view = DNSView.objects.create(name="Other")

        form = forms.DNSZoneForm(
            instance=zone,
            data=self._zone_data(name=zone.name, catalog=catalog_zone.pk, dns_view=other_view.pk),
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        zone.refresh_from_db()
        self.assertEqual(zone.dns_view_id, catalog_zone.dns_view_id)

    def test_catalog_is_disabled_when_editing_catalog_zone(self):
        zone = DNSZone.objects.create(name="catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["catalog"].disabled)

    def test_catalog_is_disabled_when_editing_enrolled_primary_zone(self):
        """The catalog field is disabled when editing an enrolled primary zone."""
        zone, _ = self._enrolled_zone()
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["catalog"].disabled)

    def test_catalog_is_enabled_when_editing_primary_zone(self):
        zone = DNSZone.objects.create(name="primary.example")
        form = forms.DNSZoneForm(instance=zone)
        self.assertFalse(form.fields["catalog"].disabled)

    def test_view_is_disabled_when_editing_a_catalog_zone_with_members(self):
        _, catalog_zone = self._enrolled_zone()
        form = forms.DNSZoneForm(instance=catalog_zone)
        self.assertTrue(form.fields["dns_view"].disabled)
        self.assertEqual(
            form.fields["dns_view"].help_text,
            "A catalog zone with members cannot be moved to another view.",
        )

    def test_view_is_disabled_when_editing_an_enrolled_zone(self):
        zone, _ = self._enrolled_zone()
        form = forms.DNSZoneForm(instance=zone)
        self.assertTrue(form.fields["dns_view"].disabled)
        self.assertEqual(
            form.fields["dns_view"].help_text,
            "A zone that is a member of a catalog zone cannot be moved to another view.",
        )

    def test_view_is_enabled_when_editing_a_catalog_zone_without_members(self):
        form = forms.DNSZoneForm(instance=self._catalog_zone())
        self.assertFalse(form.fields["dns_view"].disabled)

    def test_view_is_enabled_when_editing_an_unenrolled_zone(self):
        form = forms.DNSZoneForm(instance=DNSZone.objects.create(name="primary.example"))
        self.assertFalse(form.fields["dns_view"].disabled)

    def _catalog_zone(self, **overrides):
        """Create and return a catalog zone in the view the form payload uses."""
        fields = {"name": "catalog.example", "type": DNSZoneTypeChoices.TYPE_CATALOG}
        fields.update(overrides)
        return DNSZone.objects.create(**fields)

    def _enrolled_zone(self):
        """Create a zone already enrolled in a catalog, returning both."""
        catalog_zone = self._catalog_zone()
        zone = DNSZone.objects.create(name="member.example")
        models.CatalogZoneMembership(catalog_zone=catalog_zone, member_zone=zone).validated_save()
        return zone, catalog_zone


class DNSZoneBulkEditFormTest(TestCase):
    """Test DNSZone bulk edit form SOA RNAME handling."""

    form_class = forms.DNSZoneBulkEditForm

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(
            name="bulk-rname.example",
            filename="bulk-rname.example.zone",
            soa_mname="ns1.bulk-rname.example.",
            soa_rname="admin@example.com",
        )

    def test_soa_rname_accepts_dns_style_mailbox(self):
        form = self.form_class(
            DNSZone,
            data={"pk": [self.zone.pk], "soa_rname": "admin.example.com"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.zone.soa_rname = form.cleaned_data["soa_rname"]
        self.zone.validated_save()
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.soa_rname, "admin@example.com")

    def test_soa_rname_accepts_single_label_placeholder(self):
        form = self.form_class(
            DNSZone,
            data={"pk": [self.zone.pk], "soa_rname": "invalid."},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.zone.soa_rname = form.cleaned_data["soa_rname"]
        self.zone.validated_save()
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.soa_rname, "invalid")

    def test_soa_rname_rejects_invalid_value(self):
        form = self.form_class(
            DNSZone,
            data={"pk": [self.zone.pk], "soa_rname": "john.example"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.zone.soa_rname = form.cleaned_data["soa_rname"]
        with self.assertRaises(ValidationError) as context:
            self.zone.validated_save()
        self.assertIn("soa_rname", context.exception.message_dict)
        self.assertIn(
            "SOA RNAME must be a valid email address, a basic DNS-style mailbox with a fully qualified domain, "
            "or a single-label placeholder.",
            context.exception.message_dict["soa_rname"],
        )


class CatalogZoneMembershipFormTestCase(TestCase):
    """Test the membership add form."""

    def test_member_zone_picker_hides_enrolled_zones(self):
        """The picker asks the zone API for zones that are not already in a catalog."""
        form = forms.CatalogZoneMembershipForm()

        self.assertEqual(
            json.loads(form.fields["member_zone"].widget.attrs["data-query-param-is_catalog_member"]),
            ["false"],
        )


class DNSZoneBulkEditTestCase(TestCase):
    """Test the DNSZone bulk edit form, whose view field a membership holds its zones away from."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = DNSZone.objects.create(name="catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = DNSZone.objects.create(name="member.example")
        cls.unenrolled_zone = DNSZone.objects.create(name="primary.example")
        cls.other_view = DNSView.objects.create(name="Other")

    def test_refuses_to_move_an_enrolled_zone(self):
        """The enrolled zone is named, so a selection can be corrected in one pass."""
        models.CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone).validated_save()

        form = self._form([self.member_zone, self.unenrolled_zone], self.other_view)

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["dns_view"][0],
            "Cannot be moved to another view while in a catalog membership: <strong>member.example</strong>.",
        )

    def test_refuses_to_move_a_catalog_with_members(self):
        models.CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone).validated_save()

        form = self._form([self.catalog_zone], self.other_view)

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["dns_view"][0],
            "Cannot be moved to another view while in a catalog membership: <strong>catalog.example</strong>.",
        )

    def test_a_long_list_of_pinned_zones_is_capped_and_the_rest_counted(self):
        """The report lists five names and counts the rest, which it never fetched."""
        pinned = [DNSZone.objects.create(name=f"pinned-{index}.example") for index in range(7)]
        for zone in pinned:
            models.CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=zone).validated_save()

        form = self._form([self.catalog_zone, *pinned], self.other_view)

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["dns_view"][0],
            "Cannot be moved to another view while in a catalog membership: "
            "<strong>catalog.example</strong>, <strong>pinned-0.example</strong>, "
            "<strong>pinned-1.example</strong>, <strong>pinned-2.example</strong>, "
            "<strong>pinned-3.example</strong>, and 3 more.",
        )

    def test_allows_the_view_an_enrolled_zone_is_already_in(self):
        """Only a move is refused, so normalizing a mixed selection onto that view still goes through."""
        models.CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone).validated_save()
        elsewhere = DNSZone.objects.create(name="elsewhere.example", dns_view=self.other_view)

        form = self._form([self.member_zone, elsewhere], self.member_zone.dns_view)

        self.assertTrue(form.is_valid(), form.errors)

    def test_allows_moving_zones_in_no_membership(self):
        form = self._form([self.unenrolled_zone, self.catalog_zone], self.other_view)
        self.assertTrue(form.is_valid(), form.errors)

    def test_allows_a_bulk_edit_that_sets_no_view(self):
        models.CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone).validated_save()
        form = self._form([self.member_zone], None, description="Bulk edit zones")
        self.assertTrue(form.is_valid(), form.errors)

    def test_refuses_an_enrolled_zone_the_selection_reaches_but_no_page_posted(self):
        """A selection given by the view is judged whole, so an offender off the page is still named."""
        models.CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone).validated_save()

        form = self._form([self.unenrolled_zone], self.other_view, selection=DNSZone.objects.all())

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["dns_view"][0],
            "Cannot be moved to another view while in a catalog membership: "
            "<strong>catalog.example</strong>, <strong>member.example</strong>.",
        )

    def test_a_selection_reaching_nothing_is_taken_at_its_word(self):
        """An edit that reaches no zones checks none, rather than falling back on the posted ones."""
        models.CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone).validated_save()

        form = self._form([self.member_zone], self.other_view, selection=DNSZone.objects.none())

        self.assertTrue(form.is_valid(), form.errors)

    @staticmethod
    def _form(zones, dns_view, selection=None, **overrides):
        """Build a bulk edit form posting `zones` and `dns_view`, over `selection` when the view gave one."""
        data = {"pk": [zone.pk for zone in zones]}
        if dns_view is not None:
            data["dns_view"] = dns_view.pk
        data.update(overrides)
        return forms.DNSZoneBulkEditForm(DNSZone, data=data, selection=selection)


class DNSRegistrarFormTestCase(TestCase):
    """Test DNSRegistrar forms."""

    form_class = forms.DNSRegistrarForm

    def test_specifying_all_fields_success(self):
        form = self.form_class(
            data={
                "name": "Registrar Test",
                "portal_url": "https://registrar.test",
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
        form = self.form_class(data={"portal_url": "https://registrar.test"})
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

    def test_ip_address_label(self):
        form = self.form_class()
        self.assertEqual(form.fields["ip_address"].label, "IP Address")


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

    def test_ip_address_label(self):
        form = self.form_class()
        self.assertEqual(form.fields["ip_address"].label, "IP Address")


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

    def test_accepts_dkim_key_longer_than_256_characters(self):
        data = {
            "name": "dkim",
            "text": "v=DKIM1; k=rsa; p=" + "A" * 582,
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save())

    def test_rejects_quoted_character_string_over_255_octets(self):
        data = {
            "name": "txt-record",
            "text": '"' + "a" * 300 + '"',
            "ttl": 3600,
            "zone": self.dns_zone,
        }
        form = self.form_class(data)
        self.assertFalse(form.is_valid())
        self.assertIn("text", form.errors)


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
