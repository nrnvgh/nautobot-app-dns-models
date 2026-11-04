"""Unit tests for views."""
# pylint: disable=too-many-lines

import re
import uuid
from unittest.mock import patch

from constance import config as constance_config
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import reverse
from nautobot.apps.testing import AssertNoRepeatedQueries, TestCase, ViewTestCases, disable_warnings, post_data
from nautobot.core.testing.utils import extract_page_body
from nautobot.extras.models import ObjectChange, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix
from nautobot.users.models import ObjectPermission
from netutils.ip import ipaddress_address

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.forms import DNSZoneBulkAddMembershipForm, DNSZoneBulkEditForm, DNSZoneForm
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CatalogZoneMembership,
    CNAMERecord,
    DNSRecord,
    DNSRegistrar,
    DNSView,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
)
from nautobot_dns_models.tests.test_models import create_zone
from nautobot_dns_models.views import DNSZoneUIViewSet

User = get_user_model()


class SidePanelTestsMixin:
    """Provide test methods for template_content side panels."""

    def detail_view_test_side_panels(
        self, detail_object, render_panel, panel_model, panel_objects=None, panel_title=None
    ):  # pylint: disable=too-many-arguments
        """Test whether a side panel renders properly.

        Args:
            detail_object (obj): The object with the under-test detailed view.
            render_panel (bool): Should the under-test side panel render or not.
            panel_model (obj): The class of the objects in the side panel.
            panel_objects (list, optional): List of expected panel objects.
            panel_title (str, optional): The title of the side panel, defaults to panel_model._meta.verbose_name_plural.
        """
        panel_objects = panel_objects or []
        panel_title = panel_title or panel_model._meta.verbose_name_plural

        detail_reverse = f"{detail_object._meta.app_label}:{detail_object._meta.model_name}"
        url = reverse(detail_reverse, args=(detail_object.pk,))
        response = self.client.get(url)
        self.assertHttpStatus(response, 200)
        content = extract_page_body(response.content.decode(response.charset))

        self.assertInHTML(f"<strong>{panel_title}</strong>", content, int(render_panel))
        if render_panel:
            if not panel_objects:
                component = f"— No {panel_model._meta.verbose_name_plural} found —"
                self.assertInHTML(component, content, 1)
            for panel_object in panel_objects:
                panel_reverse = f"plugins:{panel_object._meta.app_label}:{panel_object._meta.model_name}"
                panel_object_url = reverse(panel_reverse, args=(panel_object.pk,))
                component = f'<a href="{panel_object_url}">{panel_object.name}</a>'
                self.assertInHTML(component, content, 1)


class DNSViewViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the DNSView views."""

    model = DNSView

    @classmethod
    def setUpTestData(cls):
        DNSView.objects.create(
            name="View 1",
            description="Test Description",
        )
        DNSView.objects.create(
            name="View 2",
            description="Test Description",
        )
        DNSView.objects.create(
            name="View 3",
            description="Test Description",
        )

        cls.form_data = {
            "name": "Test 1",
            "description": "Initial model",
        }

        cls.csv_data = (
            "name,description",
            "Test 3,Description 3",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views"}


class DNSRegistrarViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the DNSRegistrar views."""

    model = DNSRegistrar

    @classmethod
    def setUpTestData(cls):
        DNSRegistrar.objects.create(
            name="Registrar 1", portal_url="https://registrar1.example", account_number="ACC-001"
        )
        DNSRegistrar.objects.create(
            name="Registrar 2", portal_url="https://registrar2.example", account_number="ACC-002"
        )
        DNSRegistrar.objects.create(
            name="Registrar 3", portal_url="https://registrar3.example", account_number="ACC-003"
        )

        cls.form_data = {
            "name": "Registrar Test",
            "portal_url": "https://registrar-test.example",
            "account_number": "ACC-TEST",
        }

        cls.csv_data = (
            "name,portal_url,account_number",
            "Registrar CSV,https://registrar-csv.example,ACC-CSV",
        )

        cls.bulk_edit_data = {"account_number": "UPDATED-ACCOUNT"}


class DnsZoneViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the DNSZone views."""

    model = DNSZone

    @classmethod
    def setUpTestData(cls):
        DNSZone.objects.create(
            name="example-one.com",
            filename="test one",
            soa_mname="auth-server",
            soa_rname="admin@example-one.com",
            soa_refresh=86400,
            soa_retry=7200,
            soa_expire=3600000,
            soa_serial=0,
            soa_minimum=172800,
        )
        DNSZone.objects.create(
            name="example-two.com",
            filename="test two",
            soa_mname="auth-server",
            soa_rname="admin@example-two.com",
            soa_refresh=86400,
            soa_retry=7200,
            soa_expire=3600000,
            soa_serial=0,
            soa_minimum=172800,
        )
        DNSZone.objects.create(
            name="example-three.com",
            filename="test three",
            soa_mname="auth-server",
            soa_rname="admin@example-three.com",
            soa_refresh=86400,
            soa_retry=7200,
            soa_expire=3600000,
            soa_serial=0,
            soa_minimum=172800,
        )

        dns_view = DNSView.objects.get(name="Default")
        cls.form_data = {
            "name": "Test 1",
            "type": DNSZoneTypeChoices.TYPE_PRIMARY,
            "dns_view": dns_view.id,
            "ttl": 3600,
            "description": "Initial model",
            "filename": "test three",
            "soa_mname": "auth-server",
            "soa_rname": "admin@example-three.com",
            "soa_refresh": 86400,
            "soa_retry": 7200,
            "soa_expire": 3600000,
            "soa_serial": 0,
            "soa_minimum": 172800,
            "enabled": True,
        }

        cls.csv_data = (
            "name, dns_view, ttl, description, filename, soa_mname, soa_rname, soa_refresh, soa_retry, soa_expire, soa_serial, soa_minimum",
            f"Test 3, {dns_view.id}, 3600, Description 3, filename 3, auth-server, admin@example_three.com, 86400, 7200, 3600000, 0, 172800",
        )

        cls.bulk_edit_data = {
            "description": "Bulk edit views",
            "enabled": False,
            # DNSZone.soa_rname accepts a DNS-style mailbox, not only an email address
            "soa_rname": "admin.example.com",
        }

    def test_list_names_each_zone_catalog_without_per_zone_queries(self):
        """The catalog column reads the membership from the view's prefetch, not once per row."""
        catalog = DNSZone.objects.create(name="catalog-list.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        for index in range(12):
            CatalogZoneMembership.objects.create(
                catalog_zone=catalog,
                member_zone=DNSZone.objects.create(name=f"member-list-{index}.example"),
            )

        self.add_permissions("nautobot_dns_models.view_dnszone")
        # The rows arrive on the HTMX follow-up request; the first response is an empty table shell.
        with AssertNoRepeatedQueries(self):
            response = self.client.get(self._get_url("list"), headers={"HX-Request": "true"})

        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))
        # The catalog's own row names it once; every member row names it again in the catalog column.
        self.assertEqual(body.count(catalog.name), 13)
        # The column names the catalog alone, leaving the view to the column that already carries it.
        self.assertNotIn(str(catalog), body)


@override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
class ZoneDetailViewByZoneTypeTest(TestCase):
    """Tests for the panels and buttons a zone's detail page offers, which vary by zone type."""

    RECORD_PANELS = frozenset(
        model._meta.verbose_name_plural.upper() for model in apps.get_models() if issubclass(model, DNSRecord)
    )

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")
        cls.membership = CatalogZoneMembership(catalog_zone=cls.catalog_zone, member_zone=cls.member_zone)
        cls.membership.validated_save()
        cls.member_zone_record = TXTRecord(name="txt", text="a user record", zone=cls.member_zone)
        cls.member_zone_record.validated_save()

    def test_primary_zone_offers_every_record_panel(self):
        """An ordinary zone's detail page lists a panel for every record type."""
        self.assertLessEqual(self.RECORD_PANELS, self._panel_headings(self.member_zone))

    def test_catalog_zone_keeps_only_the_record_panels_it_has_records_for(self):
        """A catalog zone lists only the NS and TXT panels, the record types it holds."""
        self.assertEqual(self.RECORD_PANELS & self._panel_headings(self.catalog_zone), {"NS RECORDS", "TXT RECORDS"})

    def test_catalog_zone_shows_the_version_record(self):
        """A catalog zone links the schema version TXT it auto-creates (RFC 9432 §4.2.1)."""
        record = TXTRecord.objects.get(zone=self.catalog_zone)
        self.assertIn(record.get_absolute_url(), self._detail(self.catalog_zone))

    def test_catalog_zone_shows_the_apex_ns_record(self):
        """A catalog zone links the apex NS record it auto-creates (RFC 9432 §4)."""
        record = NSRecord.objects.get(zone=self.catalog_zone)
        self.assertIn(record.get_absolute_url(), self._detail(self.catalog_zone))

    def test_catalog_zone_offers_no_write_controls_for_the_version_record(self):
        """With `change_txtrecord`, the version TXT still renders no edit link."""
        self.add_permissions("nautobot_dns_models.change_txtrecord")
        record = TXTRecord.objects.get(zone=self.catalog_zone)
        url = reverse("plugins:nautobot_dns_models:txtrecord_edit", args=(record.pk,))
        self.assertNotIn(url, self._detail(self.catalog_zone))

    def test_catalog_zone_offers_no_write_controls_for_the_apex_ns_record(self):
        """With `change_nsrecord`, the apex NS still renders no edit link."""
        self.add_permissions("nautobot_dns_models.change_nsrecord")
        record = NSRecord.objects.get(zone=self.catalog_zone)
        url = reverse("plugins:nautobot_dns_models:nsrecord_edit", args=(record.pk,))
        self.assertNotIn(url, self._detail(self.catalog_zone))

    def test_primary_zone_keeps_write_controls_for_its_records(self):
        """With `change_txtrecord`, an ordinary zone's TXT record still renders its edit link."""
        self.add_permissions("nautobot_dns_models.change_txtrecord")
        url = reverse("plugins:nautobot_dns_models:txtrecord_edit", args=(self.member_zone_record.pk,))
        self.assertIn(url, self._detail(self.member_zone))

    def test_catalog_zone_offers_no_add_button_for_records(self):
        """With `add_txtrecord`, a catalog zone's TXT panel renders no Add button."""
        self.add_permissions("nautobot_dns_models.add_txtrecord")
        url = reverse("plugins:nautobot_dns_models:txtrecord_add")
        self.assertNotIn(url, self._detail(self.catalog_zone))

    def test_primary_zone_keeps_the_add_button_on_its_record_panels(self):
        """With `add_txtrecord`, an ordinary zone's TXT panel still renders its Add button."""
        self.add_permissions("nautobot_dns_models.add_txtrecord")
        url = reverse("plugins:nautobot_dns_models:txtrecord_add")
        self.assertIn(url, self._detail(self.member_zone))

    def test_catalog_zone_hides_the_add_records_menu(self):
        """With `add_arecord`, a catalog zone renders no Add Records dropdown."""
        self.add_permissions("nautobot_dns_models.change_dnszone", "nautobot_dns_models.add_arecord")
        self.assertNotIn("Add Records", self._detail(self.catalog_zone))

    def test_primary_zone_keeps_the_add_records_menu(self):
        """With `add_arecord`, an ordinary zone still renders the Add Records dropdown."""
        self.add_permissions("nautobot_dns_models.change_dnszone", "nautobot_dns_models.add_arecord")
        self.assertIn("Add Records", self._detail(self.member_zone))

    def test_catalog_zone_lists_its_members(self):
        """A catalog zone renders a Member Zones panel carrying each member's PTR record name."""
        self.assertIn("MEMBER ZONES", self._panel_headings(self.catalog_zone))
        self.assertIn(f"{self.membership.member_label}.zones", self._detail(self.catalog_zone))

    def test_primary_zone_has_no_member_zones_panel(self):
        """An ordinary zone renders no Member Zones panel, having no members to publish."""
        self.assertNotIn("MEMBER ZONES", self._panel_headings(self.member_zone))

    def test_catalog_zone_has_no_record_statistics(self):
        """A catalog zone renders no Records Statistics panel, holding no user records to count."""
        self.assertNotIn("RECORDS STATISTICS", self._panel_headings(self.catalog_zone))

    def test_catalog_zone_has_no_registration_panel(self):
        """A catalog zone renders no Registration panel, not being a registered name."""
        self.assertNotIn("REGISTRATION", self._panel_headings(self.catalog_zone))

    def test_primary_zone_keeps_the_registration_panel(self):
        """An ordinary zone still renders the Registration panel."""
        self.assertIn("REGISTRATION", self._panel_headings(self.member_zone))

    def test_primary_zone_keeps_record_statistics(self):
        """An ordinary zone still renders the Records Statistics panel."""
        self.assertIn("RECORDS STATISTICS", self._panel_headings(self.member_zone))

    def test_member_zone_names_the_catalog_it_belongs_to(self):
        """A member zone carries a Catalog Zone row naming the catalog holding it."""
        content = self._detail(self.member_zone)
        self.assertInHTML("<td>Catalog Zone</td>", content, 1)
        self.assertIn(self.catalog_zone.name, content)

    def test_catalog_zone_omits_the_catalog_field(self):
        """A catalog zone carries no Catalog Zone row."""
        self.assertInHTML("<td>Catalog Zone</td>", self._detail(self.catalog_zone), 0)

    def _detail(self, zone):
        """Return the rendered body of `zone`'s detail page."""
        response = self.client.get(zone.get_absolute_url())
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))

    def _panel_headings(self, zone):
        """Return the panel headings on `zone`'s detail page, upper-cased since Nautobot's own casing varies.

        Headings rather than raw page text: a hidden panel's title survives elsewhere in the markup, in
        the table configuration drawer and the navigation menu, so a substring search sees it either way.
        """
        return {label.upper() for label in re.findall(r"<strong>([^<]*)</strong>", self._detail(zone))}


@override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
class ZoneFormMembershipPermissionTest(TestCase):
    """Tests that the zone form's catalog field is governed by the membership's own permissions.

    The field writes `CatalogZoneMembership` rows, so `change_dnszone` alone must not carry a user
    through a membership they could not have made from the membership's own pages.
    """

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("other-catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.unenrolled_zone = create_zone("unenrolled.example")
        cls.enrolled_zone = create_zone("enrolled.example")
        CatalogZoneMembership(catalog_zone=cls.catalog_zone, member_zone=cls.enrolled_zone).validated_save()

    def setUp(self):
        """Grant the zone permissions every one of these edits needs before its membership is judged."""
        super().setUp()
        self.add_permissions(
            "nautobot_dns_models.view_dnsview",
            "nautobot_dns_models.view_dnszone",
            "nautobot_dns_models.add_dnszone",
            "nautobot_dns_models.change_dnszone",
        )

    ADD_REFUSED = "You do not have permission to add a zone to a catalog."

    def test_enrolling_requires_add_permission(self):
        """Without `add_catalogzonemembership`, choosing a catalog is refused and no membership is written."""
        self._assert_refused(self._edit(self.unenrolled_zone, self.catalog_zone), self.ADD_REFUSED)
        self.assertIsNone(self._catalog_of(self.unenrolled_zone))

    def test_enrolling_is_allowed_with_add_permission(self):
        """With `add_catalogzonemembership`, choosing a catalog enrolls the zone."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        self.assertHttpStatus(self._edit(self.unenrolled_zone, self.catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.unenrolled_zone), self.catalog_zone)

    def test_submitting_replacement_catalog_does_not_move_existing_membership(self):
        """A submitted replacement catalog leaves the enrolled zone's current catalog unchanged."""
        self.assertHttpStatus(self._edit(self.enrolled_zone, self.other_catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_submitting_blank_catalog_value_does_not_remove_existing_membership(self):
        """Submitting a blank catalog value on an enrolled zone edit does not clear its membership."""
        self.assertHttpStatus(self._edit(self.enrolled_zone), 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_editing_an_enrolled_zone_leaves_its_membership_alone(self):
        """Resubmitting the same catalog needs no membership permission and leaves the row alone."""
        self.assertHttpStatus(self._edit(self.enrolled_zone, self.catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_a_removal_during_the_edit_is_not_undone(self):
        """An edit must not enroll the zone again when another writer removed it during the request.

        The view loads the zone with its memberships prefetched, so the form disables its catalog
        field, which it reads from initial: the old catalog. That value only displays the zone's
        catalog. Acting on it would enroll the zone again, here for a user without
        `add_catalogzonemembership`.
        """
        original_clean = DNSZoneForm.clean

        def remove_then_clean(form):
            CatalogZoneMembership.objects.filter(member_zone=self.enrolled_zone).delete()
            return original_clean(form)

        with patch.object(DNSZoneForm, "clean", autospec=True, side_effect=remove_then_clean):
            response = self._edit(self.enrolled_zone, self.catalog_zone)

        self.assertHttpStatus(response, 302)
        self.assertIsNone(self._catalog_of(self.enrolled_zone))
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())

    def test_renaming_an_enrolled_zone_needs_no_membership_permission(self):
        """A rename needs no membership permission, though it replaces the membership row.

        The zone stays in the catalog it was already in. The membership row is replaced because a
        renamed zone is a different zone to a consumer, and that replacement is derived state this
        app maintains, like the catalog's PTR records. Demanding `add_catalogzonemembership` or
        `delete_catalogzonemembership` would block a rename the user is entitled to make on a model
        they need not know exists.
        """
        data = self._zone_data(zone=self.enrolled_zone, catalog=self.catalog_zone)
        data["name"] = "renamed.example"

        response = self.client.post(
            reverse("plugins:nautobot_dns_models:dnszone_edit", args=(self.enrolled_zone.pk,)), data
        )

        self.assertHttpStatus(response, 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_renaming_with_replacement_catalog_keeps_zone_in_current_catalog(self):
        """Renaming an enrolled zone succeeds without changing its catalog despite the submitted replacement."""
        data = self._zone_data(zone=self.enrolled_zone, catalog=self.other_catalog_zone)
        data["name"] = "renamed-with-ignored-catalog.example"

        response = self.client.post(
            reverse("plugins:nautobot_dns_models:dnszone_edit", args=(self.enrolled_zone.pk,)), data
        )

        self.assertHttpStatus(response, 302)
        self.assertEqual(
            DNSZone.objects.get(pk=self.enrolled_zone.pk).name,
            "renamed-with-ignored-catalog.example",
        )
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_creating_an_enrolled_zone_requires_add_permission(self):
        """Without `add_catalogzonemembership`, creating a zone with a catalog is refused and no zone is left behind."""
        response = self.client.post(
            reverse("plugins:nautobot_dns_models:dnszone_add"),
            self._zone_data(create_zone_name="new.example", catalog=self.catalog_zone),
        )
        self._assert_refused(response, self.ADD_REFUSED)
        self.assertFalse(DNSZone.objects.filter(name="new.example").exists())

    def test_constraints_are_evaluated_against_the_membership(self):
        """A permission narrowed to one catalog must not enroll zones in any other."""
        object_permission = ObjectPermission(
            name="Enroll in one catalog only",
            actions=["add"],
            constraints={"catalog_zone__name": self.catalog_zone.name},
        )
        object_permission.save()
        object_permission.users.add(self.user)
        object_permission.object_types.add(ContentType.objects.get_for_model(CatalogZoneMembership))

        self._assert_refused(self._edit(self.unenrolled_zone, self.other_catalog_zone), self.ADD_REFUSED)
        self.assertIsNone(self._catalog_of(self.unenrolled_zone))

        self.assertHttpStatus(self._edit(self.unenrolled_zone, self.catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.unenrolled_zone), self.catalog_zone)

    def _assert_refused(self, response, message):
        """Assert the save was refused for the stated reason, on the field the user chose the catalog in.

        Any form error redisplays the page, so the status alone would let an unrelated failure pass.
        """
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))
        self.assertIn(message, body)
        self.assertIn("id_catalog_error", body)

    def _catalog_of(self, zone):
        """Return the catalog `zone` is enrolled in, read back from the database."""
        return DNSZone.objects.get(pk=zone.pk).catalog

    def _edit(self, zone, catalog=None):
        """Post `zone`'s edit form, offering `catalog` in the field that governs its membership."""
        return self.client.post(
            reverse("plugins:nautobot_dns_models:dnszone_edit", args=(zone.pk,)),
            self._zone_data(zone=zone, catalog=catalog),
        )

    def _zone_data(self, zone=None, create_zone_name=None, catalog=None):
        """Return a complete zone form submission, since an incomplete one never reaches the save."""
        zone = zone or DNSZone(name=create_zone_name, filename=f"{create_zone_name}.zone")
        data = {
            "name": zone.name,
            "type": DNSZoneTypeChoices.TYPE_PRIMARY,
            "dns_view": DNSView.objects.get(name="Default").pk,
            "filename": zone.filename,
            "soa_mname": "ns1.example.",
            "soa_rname": "admin@example.com",
            "soa_refresh": 86400,
            "soa_retry": 7200,
            "soa_expire": 3600000,
            "soa_serial": 0,
            "soa_minimum": 172800,
            "ttl": 3600,
            "enabled": True,
        }
        if catalog is not None:
            data["catalog"] = catalog.pk

        return data


@override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
class ZoneFormRemovalButtonTest(TestCase):
    """The zone edit form offers removal via the membership delete page, not the catalog field."""

    HELP_TEXT = "Remove this zone from its current catalog before selecting another."

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.unenrolled_zone = create_zone("unenrolled.example")
        cls.enrolled_zone = create_zone("enrolled.example")
        cls.membership = CatalogZoneMembership(catalog_zone=cls.catalog_zone, member_zone=cls.enrolled_zone)
        cls.membership.validated_save()

    def setUp(self):
        super().setUp()
        self.add_permissions(
            "nautobot_dns_models.view_dnsview",
            "nautobot_dns_models.view_dnszone",
            "nautobot_dns_models.change_dnszone",
        )

    def test_enrolled_zone_offers_removal_when_permitted(self):
        """With `delete_catalogzonemembership`, the edit form links to that membership's delete page."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        body = self._edit_body(self.enrolled_zone)

        self.assertIn(self.HELP_TEXT, body)
        self.assertIn(self._removal_href(self.enrolled_zone, self.membership), body)

    def test_enrolled_zone_hides_removal_without_delete_permission(self):
        """Without `delete_catalogzonemembership`, the help text remains and the button does not."""
        body = self._edit_body(self.enrolled_zone)

        self.assertIn(self.HELP_TEXT, body)
        self.assertNotIn(self._removal_href(self.enrolled_zone, self.membership), body)
        self.assertNotIn("Remove from Catalog", body)

    def test_unenrolled_zone_offers_no_removal(self):
        """An unenrolled zone's edit form has no catalog-removal help or button."""
        body = self._edit_body(self.unenrolled_zone)

        self.assertNotIn(self.HELP_TEXT, body)
        self.assertNotIn("Remove from Catalog", body)

    def test_catalog_zone_offers_no_removal(self):
        """A catalog zone is not a member, so its edit form has no catalog-removal help or button."""
        body = self._edit_body(self.catalog_zone)

        self.assertNotIn(self.HELP_TEXT, body)
        self.assertNotIn("Remove from Catalog", body)

    def test_removing_follows_the_return_url_and_withdraws_the_ptr(self):
        """Confirming delete with the form's return_url lands on the zone detail and withdraws the PTR."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        member_label = self.membership.member_label
        return_url = reverse("plugins:nautobot_dns_models:dnszone", args=(self.enrolled_zone.pk,))
        self.assertTrue(PTRRecord.objects.filter(name=f"{member_label}.zones", zone=self.catalog_zone).exists())

        response = self.client.post(
            self._removal_href(self.enrolled_zone, self.membership),
            post_data({"confirm": True}),
        )

        self.assertHttpStatus(response, 302)
        self.assertEqual(response.url, return_url)
        self.assertFalse(CatalogZoneMembership.objects.filter(pk=self.membership.pk).exists())
        self.assertFalse(PTRRecord.objects.filter(name=f"{member_label}.zones", zone=self.catalog_zone).exists())

    def _edit_body(self, zone):
        """Return the HTML of `zone`'s edit form."""
        response = self.client.get(reverse("plugins:nautobot_dns_models:dnszone_edit", args=(zone.pk,)))
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))

    def _removal_href(self, zone, membership):
        """Return the delete URL the edit form should offer for `membership`, returning to `zone`."""
        delete_url = reverse("plugins:nautobot_dns_models:catalogzonemembership_delete", args=(membership.pk,))
        return_url = reverse("plugins:nautobot_dns_models:dnszone", args=(zone.pk,))
        return f"{delete_url}?return_url={return_url}"


class CatalogZoneMembershipViewTest(
    ViewTestCases.CreateObjectViewTestCase,
    ViewTestCases.DeleteObjectViewTestCase,
):
    """Test the membership add and delete pages."""

    model = CatalogZoneMembership

    @classmethod
    def setUpTestData(cls):
        catalogs = [
            create_zone("view-catalog-0.example", type=DNSZoneTypeChoices.TYPE_CATALOG),
            create_zone("view-catalog-1.example", type=DNSZoneTypeChoices.TYPE_CATALOG),
        ]
        members = [create_zone(f"view-member-{index}.example") for index in range(4)]
        for index, member in enumerate(members[:3]):
            CatalogZoneMembership.objects.create(
                catalog_zone=catalogs[0],
                member_zone=member,
                member_label=f"label{index}",
            )

        cls.catalog_zone = catalogs[0]
        cls.enrolled_zone = members[0]
        cls.unenrolled_zone = members[3]
        cls.membership = CatalogZoneMembership.objects.get(member_zone=members[0])
        cls.form_data = {
            "catalog_zone": catalogs[0].pk,
            "member_zone": members[3].pk,
        }

    # These first two tests are overrides of the two `CreateObjectViewTestCase` tests, changed only to look
    # up the new row by `member_zone`. Core uses `queryset.last()`, which follows `ordering`, since
    # CatalogZoneMembership has no `last_updated`.
    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_create_object_with_constrained_permission(self):
        initial_count = self._get_queryset().count()
        obj_perm = ObjectPermission(
            name="Test permission",
            constraints={"pk": str(uuid.uuid4())},
            actions=["add"],
        )
        obj_perm.save()
        obj_perm.users.add(self.user)
        obj_perm.object_types.add(ContentType.objects.get_for_model(self.model))

        self.assertHttpStatus(self.client.get(self._get_url("add")), 200)

        request = {"path": self._get_url("add"), "data": post_data(self.form_data)}
        self.assertHttpStatus(self.client.post(**request), 200)
        self.assertEqual(initial_count, self._get_queryset().count())

        obj_perm.constraints = {"pk__isnull": False}
        obj_perm.save()

        request = {"path": self._get_url("add"), "data": post_data(self.form_data)}
        self.assertHttpStatus(self.client.post(**request), 302)
        self.assertEqual(initial_count + 1, self._get_queryset().count())
        self.assertInstanceEqual(
            self._get_queryset().get(member_zone=self.form_data["member_zone"]),
            self.form_data,
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_create_object_with_permission(self):
        initial_count = self._get_queryset().count()
        self.add_permissions(f"{self.model._meta.app_label}.add_{self.model._meta.model_name}")

        self.assertHttpStatus(self.client.get(self._get_url("add")), 200)

        request = {"path": self._get_url("add"), "data": post_data(self.form_data)}
        self.assertHttpStatus(self.client.post(**request), 302)
        self.assertEqual(initial_count + 1, self._get_queryset().count())
        self.assertInstanceEqual(
            self._get_queryset().get(member_zone=self.form_data["member_zone"]),
            self.form_data,
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_add_page_seeds_the_catalog_zone_from_the_query(self):
        """`?catalog_zone=<pk>` pre-selects the catalog on the add form."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        response = self.client.get(self._get_url("add"), {"catalog_zone": self.catalog_zone.pk})
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertIn('name="catalog_zone"', body)
        self.assertIn(str(self.catalog_zone.pk), body)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_add_page_seeds_the_member_zone_from_the_query(self):
        """`?member_zone=<pk>` pre-selects the member zone on the add form."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        response = self.client.get(self._get_url("add"), {"member_zone": self.unenrolled_zone.pk})
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertIn('name="member_zone"', body)
        self.assertIn(str(self.unenrolled_zone.pk), body)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_adding_follows_the_return_url(self):
        """`return_url` in the submission is where the add redirects."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        return_url = self.catalog_zone.get_absolute_url()

        response = self.client.post(
            self._get_url("add"),
            {
                "catalog_zone": self.catalog_zone.pk,
                "member_zone": self.unenrolled_zone.pk,
                "return_url": return_url,
            },
        )

        self.assertHttpStatus(response, 302)
        self.assertEqual(response.url, return_url)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_edit_page_is_not_available(self):
        """GET and POST to the edit URL return 404; memberships are add and delete only."""
        self.add_permissions(
            "nautobot_dns_models.add_catalogzonemembership",
            "nautobot_dns_models.change_catalogzonemembership",
        )
        url = self._get_url("edit", self.membership)
        catalog_zone = self.membership.catalog_zone
        member_zone = self.membership.member_zone
        member_label = self.membership.member_label

        with disable_warnings("django.request"):
            self.assertHttpStatus(self.client.get(url), 404)
            self.assertHttpStatus(
                self.client.post(
                    url,
                    post_data(
                        {
                            "catalog_zone": self.catalog_zone.pk,
                            "member_zone": self.unenrolled_zone.pk,
                        }
                    ),
                ),
                404,
            )

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.catalog_zone, catalog_zone)
        self.assertEqual(self.membership.member_zone, member_zone)
        self.assertEqual(self.membership.member_label, member_label)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_catalog_detail_links_to_add_and_delete(self):
        """A catalog zone's Member Zones panel links add, delete, and the filtered zone list."""
        self.add_permissions(
            "nautobot_dns_models.add_catalogzonemembership",
            "nautobot_dns_models.delete_catalogzonemembership",
        )
        add_url = self._get_url("add")
        list_url = reverse("plugins:nautobot_dns_models:dnszone_list")

        response = self.client.get(self.catalog_zone.get_absolute_url())
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertRegex(body, rf'href="{re.escape(add_url)}\?[^"]*&(amp;)?catalog_zone={self.catalog_zone.pk}"')
        self.assertIn(self._get_url("delete", self.membership), body)
        self.assertIn(f"{list_url}?catalog={self.catalog_zone.pk}", body)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_zone_list_links_an_unenrolled_zone_to_add(self):
        """An unenrolled row offers only the member-seeded add, not edit or the catalog-seeded add."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        add_url = self._get_url("add")
        # The rows arrive on the HTMX follow-up request; the first response is an empty table shell.
        response = self.client.get(
            reverse("plugins:nautobot_dns_models:dnszone_list"),
            headers={"HX-Request": "true"},
        )
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertIn(f"{add_url}?member_zone={self.unenrolled_zone.pk}", body)
        self.assertNotIn(self._get_url("edit", self.membership), body)
        self.assertNotIn(f"{add_url}?catalog_zone={self.catalog_zone.pk}", body)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_zone_list_links_an_enrolled_zone_to_delete(self):
        """An enrolled row offers only the delete action."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        add_url = self._get_url("add")
        # The rows arrive on the HTMX follow-up request; the first response is an empty table shell.
        response = self.client.get(
            reverse("plugins:nautobot_dns_models:dnszone_list"),
            headers={"HX-Request": "true"},
        )
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertIn(self._get_url("delete", self.membership), body)
        self.assertNotIn(self._get_url("edit", self.membership), body)
        self.assertNotIn(f"{add_url}?member_zone={self.enrolled_zone.pk}", body)


class NSRecordViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the NSRecord views."""

    model = NSRecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example_one.com",
        )

        NSRecord.objects.create(
            name="primary",
            server="example-server.com.",
            zone=zone,
        )
        NSRecord.objects.create(
            name="secondary",
            server="example-server.com.",
            zone=zone,
        )
        NSRecord.objects.create(
            name="tertiary",
            server="example-server.com.",
            zone=zone,
        )

        cls.form_data = {
            "name": "test record",
            "server": "test server",
            "zone": zone.pk,
            "ttl": 3600,
            "enabled": True,
        }

        cls.csv_data = (
            "name,server,zone, ttl",
            f"Test 3,server 3,{zone.name}, 3600",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}


class ARecordViewTest(ViewTestCases.PrimaryObjectViewTestCase, SidePanelTestsMixin):
    # pylint: disable=too-many-ancestors
    """Test the ARecord views."""

    model = ARecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example_one.com",
        )
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_addresses = (
            IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=status),
            IPAddress.objects.create(address="10.0.0.2/32", namespace=namespace, status=status),
            IPAddress.objects.create(address="10.0.0.3/32", namespace=namespace, status=status),
        )
        cls.ip_addresses_wo_records = (
            IPAddress.objects.create(address="10.0.0.4/32", namespace=namespace, status=status),
        )

        ARecord.objects.create(
            name="primary",
            ip_address=cls.ip_addresses[0],
            zone=zone,
        )
        ARecord.objects.create(
            name="primary",
            ip_address=cls.ip_addresses[1],
            zone=zone,
        )
        ARecord.objects.create(
            name="primary",
            ip_address=cls.ip_addresses[2],
            zone=zone,
        )

        cls.form_data = {
            "name": "test record",
            "ip_address": cls.ip_addresses[0].pk,
            "ttl": 3600,
            "zone": zone.pk,
            "enabled": True,
        }

        cls.csv_data = (
            "name,ip_address,zone",
            f"Test 3,{cls.ip_addresses[0].pk},{zone.name}",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_always(self):
        """Test IP Address side panel for A Records when set to 'Always'."""
        constance_config.nautobot_dns_models__SHOW_FORWARD_PANEL = "always"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=ARecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        arecord = ARecord.objects.get(ip_address=address)
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=ARecord, panel_objects=[arecord]
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_present(self):
        """Test IP Address side panel for A Records when set to 'If present'."""
        constance_config.nautobot_dns_models__SHOW_FORWARD_PANEL = "if_present"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=ARecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        arecord = ARecord.objects.get(ip_address=address)
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=ARecord, panel_objects=[arecord]
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_never(self):
        """Test IP Address side panel for A Records when set to 'Never'."""
        constance_config.nautobot_dns_models__SHOW_FORWARD_PANEL = "never"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=ARecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        arecord = ARecord.objects.get(ip_address=address)
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=ARecord, panel_objects=[arecord]
        )


class AAAARecordViewTest(ViewTestCases.PrimaryObjectViewTestCase, SidePanelTestsMixin):
    # pylint: disable=too-many-ancestors
    """Test the AAAARecord views."""

    model = AAAARecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example_one.com",
        )
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="2001:db8:abcd:12::/64", namespace=namespace, type="Pool", status=status)
        cls.ip_addresses = (
            IPAddress.objects.create(address="2001:db8:abcd:12::1/128", namespace=namespace, status=status),
            IPAddress.objects.create(address="2001:db8:abcd:12::2/128", namespace=namespace, status=status),
            IPAddress.objects.create(address="2001:db8:abcd:12::3/128", namespace=namespace, status=status),
        )
        cls.ip_addresses_wo_records = (
            IPAddress.objects.create(address="2001:db8:abcd:12::4/128", namespace=namespace, status=status),
        )

        AAAARecord.objects.create(
            name="primary",
            ip_address=cls.ip_addresses[0],
            zone=zone,
        )
        AAAARecord.objects.create(
            name="primary",
            ip_address=cls.ip_addresses[1],
            zone=zone,
        )
        AAAARecord.objects.create(
            name="primary",
            ip_address=cls.ip_addresses[2],
            zone=zone,
        )

        cls.form_data = {
            "name": "test record",
            "ip_address": cls.ip_addresses[0].pk,
            "ttl": 3600,
            "zone": zone.pk,
            "enabled": True,
        }

        cls.csv_data = (
            "name,ip_address,zone",
            f"Test 3,{cls.ip_addresses[0].pk},{zone.name}",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_always(self):
        """Test IP Address side panel for AAAA Records when set to 'Always'."""
        constance_config.nautobot_dns_models__SHOW_FORWARD_PANEL = "always"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=AAAARecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        aaaarecord = AAAARecord.objects.get(ip_address=address)
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=AAAARecord, panel_objects=[aaaarecord]
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_present(self):
        """Test IP Address side panel for AAAA Records when set to 'If present'."""
        constance_config.nautobot_dns_models__SHOW_FORWARD_PANEL = "if_present"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=AAAARecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        aaaarecord = AAAARecord.objects.get(ip_address=address)
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=AAAARecord, panel_objects=[aaaarecord]
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_never(self):
        """Test IP Address side panel for AAAA Records when set to 'Never'."""
        constance_config.nautobot_dns_models__SHOW_FORWARD_PANEL = "never"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=AAAARecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        aaaarecord = AAAARecord.objects.get(ip_address=address)
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=AAAARecord, panel_objects=[aaaarecord]
        )


class CNAMERecordViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the CNAMERecord views."""

    model = CNAMERecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example.com",
        )

        CNAMERecord.objects.create(
            name="www.example.com",
            alias="www.example.com",
            zone=zone,
        )
        CNAMERecord.objects.create(
            name="mail.example.com",
            alias="mail.example.com",
            zone=zone,
        )
        CNAMERecord.objects.create(
            name="blog.example.com",
            alias="blog.example.com",
            zone=zone,
        )

        cls.form_data = {
            "name": "test record",
            "alias": "test.example.com",
            "ttl": 3600,
            "zone": zone.pk,
            "enabled": True,
        }

        cls.csv_data = (
            "name,alias,zone",
            f"Test 3,test2.example.com,{zone.name}",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}


class MXRecordViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the MXRecord views."""

    model = MXRecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example.com",
        )

        MXRecord.objects.create(
            name="mail-record-01",
            mail_server="mail01.example.com",
            zone=zone,
        )
        MXRecord.objects.create(
            name="mail-record-02",
            mail_server="mail02.example.com",
            zone=zone,
        )
        MXRecord.objects.create(
            name="mail-record-03",
            mail_server="mail03.example.com",
            zone=zone,
        )

        cls.form_data = {
            "name": "test record",
            "mail_server": "test_mail.example.com",
            "preference": 10,
            "ttl": 3600,
            "zone": zone.pk,
            "enabled": True,
        }

        cls.csv_data = (
            "name,mail_server,zone",
            f"Test 3,test_mail2.example.com,{zone.name}",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}


class TXTRecordViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the TXTRecord views."""

    model = TXTRecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example.com",
        )

        TXTRecord.objects.create(
            name="txt-record-01",
            text="txt-record-01",
            zone=zone,
        )

        TXTRecord.objects.create(
            name="txt-record-02",
            text="txt-record-02",
            zone=zone,
        )
        TXTRecord.objects.create(
            name="txt-record-03",
            text="txt-record-03",
            zone=zone,
        )

        cls.form_data = {
            "name": "test record",
            "text": "test-text",
            "ttl": 3600,
            "zone": zone.pk,
            "enabled": True,
        }

        cls.csv_data = (
            "name,text,zone",
            f"Test 3,test-text,{zone.name}",
            # A 2048-bit DKIM key: CSV import still resolves the natural key with `text` far past the
            # former 256-character limit.
            f"Test 4,v=DKIM1; k=rsa; p={'A' * 582},{zone.name}",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}


class PTRRecordViewTest(ViewTestCases.PrimaryObjectViewTestCase, SidePanelTestsMixin):
    # pylint: disable=too-many-ancestors
    """Test the PTRRecord views."""

    model = PTRRecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example.com",
        )
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_addresses = (IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=status),)
        cls.ip_addresses_wo_records = (
            IPAddress.objects.create(address="10.0.0.2/32", namespace=namespace, status=status),
        )

        PTRRecord.objects.create(
            name="ptr-record-01",
            ptrdname="ptr-record-01",
            zone=zone,
        )
        PTRRecord.objects.create(
            name="ptr-record-02",
            ptrdname="ptr-record-02",
            zone=zone,
        )
        PTRRecord.objects.create(
            name="ptr-record-03",
            ptrdname="ptr-record-03",
            zone=zone,
        )

        PTRRecord.objects.create(
            name="one.example.com",
            ptrdname=ipaddress_address(cls.ip_addresses[0].host, "reverse_pointer"),
            zone=zone,
        )

        cls.form_data = {
            "name": "test record",
            "ptrdname": "ptr-test-record",
            "ttl": 3600,
            "zone": zone.pk,
            "enabled": True,
        }

        cls.csv_data = (
            "name,ptrdname,zone",
            f"Test 3,ptr-test02-record,{zone.name}",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_always(self):
        """Test IP Address side panel for PTR Records when set to 'Always'."""
        constance_config.nautobot_dns_models__SHOW_REVERSE_PANEL = "always"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=PTRRecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        ptrrecord = PTRRecord.objects.get(ptrdname=ipaddress_address(address.host, "reverse_pointer"))
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=PTRRecord, panel_objects=[ptrrecord]
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_present(self):
        """Test IP Address side panel for PTR Records when set to 'If present'."""
        constance_config.nautobot_dns_models__SHOW_REVERSE_PANEL = "if_present"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=PTRRecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        ptrrecord = PTRRecord.objects.get(ptrdname=ipaddress_address(address.host, "reverse_pointer"))
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=True, panel_model=PTRRecord, panel_objects=[ptrrecord]
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_ipaddress_detail_view_side_panel_never(self):
        """Test IP Address side panel for PTR Records when set to 'Never'."""
        constance_config.nautobot_dns_models__SHOW_REVERSE_PANEL = "never"

        address = self.ip_addresses_wo_records[0]
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=PTRRecord, panel_objects=[]
        )

        address = self.ip_addresses[0]
        ptrrecord = PTRRecord.objects.get(ptrdname=ipaddress_address(address.host, "reverse_pointer"))
        self.detail_view_test_side_panels(
            detail_object=address, render_panel=False, panel_model=PTRRecord, panel_objects=[ptrrecord]
        )


class SRVRecordViewTest(ViewTestCases.PrimaryObjectViewTestCase):
    """Test the SRVRecord views."""

    model = SRVRecord

    @classmethod
    def setUpTestData(cls):
        zone = DNSZone.objects.create(
            name="example.com",
        )

        SRVRecord.objects.create(
            name="_sip._tcp",
            priority=10,
            weight=5,
            port=5060,
            target="sip.example.com",
            zone=zone,
        )
        SRVRecord.objects.create(
            name="_sip._tcp",
            priority=20,
            weight=10,
            port=5060,
            target="sip2.example.com",
            zone=zone,
        )
        SRVRecord.objects.create(
            name="_sip._tcp",
            priority=30,
            weight=15,
            port=5060,
            target="sip3.example.com",
            zone=zone,
        )

        cls.form_data = {
            "name": "_xmpp._tcp",
            "priority": 10,
            "weight": 5,
            "port": 5222,
            "target": "xmpp.example.com",
            "ttl": 3600,
            "zone": zone.pk,
            "enabled": True,
        }

        cls.csv_data = (
            "name,priority,weight,port,target,zone",
            f"_ldap._tcp,20,10,389,ldap.example.com,{zone.name}",
        )

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}


class ZoneBulkEditPTRControlTest(TestCase):
    """Tests that a bulk edit withdraws the PTR control once a catalog zone is among the selection.

    A catalog zone refuses `auto_create_ptr`, and the bulk edit job saves each object in turn outside
    a transaction, so offering the control would write the primary zones and then fail on the first
    catalog zone.
    """

    WITHDRAWN = "Catalog zones cannot enable this, and the selection includes one."

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("bulk-catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.primary_zones = [create_zone(f"bulk-primary-{index}.example") for index in range(2)]
        cls.bulk_edit_path = reverse("plugins:nautobot_dns_models:dnszone_bulk_edit")

    def setUp(self):
        """Grant the permissions a bulk edit needs before its selection is judged."""
        super().setUp()
        self.add_permissions("nautobot_dns_models.view_dnszone", "nautobot_dns_models.change_dnszone")

    def test_a_selection_of_primary_zones_offers_the_control(self):
        """A selection of primary zones renders the `auto_create_ptr` control."""
        content = self._bulk_edit_form(pk_list=[zone.pk for zone in self.primary_zones])
        self.assertIn('name="auto_create_ptr"', content)
        self.assertNotIn(self.WITHDRAWN, content)

    def test_a_selection_holding_a_catalog_zone_withdraws_the_control(self):
        """One catalog zone among primary zones withdraws the control for the whole selection."""
        content = self._bulk_edit_form(pk_list=[self.primary_zones[0].pk, self.catalog_zone.pk])
        self.assertIn(self.WITHDRAWN, content)

    def test_select_all_withdraws_the_control_when_it_includes_a_catalog_zone(self):
        """An unfiltered "select all" withdraws the control, resolving to every zone including the catalog zone."""
        self.assertIn(self.WITHDRAWN, self._bulk_edit_form(edit_all=True))

    def test_select_all_keeps_the_control_when_filtered_to_primary_zones(self):
        """With `?type=primary`, "select all" resolves to primary zones alone and keeps the control."""
        content = self._bulk_edit_form(edit_all=True, query=f"?type={DNSZoneTypeChoices.TYPE_PRIMARY}")
        self.assertIn('name="auto_create_ptr"', content)
        self.assertNotIn(self.WITHDRAWN, content)

    def test_a_withdrawn_control_discards_a_submitted_value(self):
        """A disabled `auto_create_ptr` cleans to None, so a submitted value never reaches the job."""
        form = DNSZoneBulkEditForm(
            DNSZone,
            {"pk": [str(zone.pk) for zone in self.primary_zones], "auto_create_ptr": "True"},
            selection=DNSZone.objects.filter(pk__in=[self.primary_zones[0].pk, self.catalog_zone.pk]),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["auto_create_ptr"])

    def _bulk_edit_form(self, pk_list=None, edit_all=False, query=""):
        """Return the bulk edit page rendered for a selection, named by pk or claimed wholesale."""
        data = {"pk": [str(pk) for pk in pk_list or []]}
        if edit_all:
            data["_all"] = "on"

        response = self.client.post(f"{self.bulk_edit_path}{query}", data)
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))


class ZoneBulkEditViewMoveTest(TestCase):
    """Tests that a bulk edit refuses to move zones a catalog membership holds in their current view.

    A membership records a zone in one view, so the form is handed the zones the queued job will
    edit. Under "select all" that is everything the filter matched, not the page that submitted.
    """

    REFUSAL = "Cannot be moved to another view while in a catalog membership:"

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("move-catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("move-member.example")
        cls.loose_zones = [create_zone(f"move-loose-{index}.example") for index in range(2)]
        CatalogZoneMembership(catalog_zone=cls.catalog_zone, member_zone=cls.member_zone).validated_save()
        cls.other_view = DNSView.objects.create(name="Move Target")
        cls.bulk_edit_path = reverse("plugins:nautobot_dns_models:dnszone_bulk_edit")

    def setUp(self):
        """Grant the permissions a bulk edit needs, including on the view it would move zones into."""
        super().setUp()
        self.add_permissions(
            "nautobot_dns_models.view_dnszone",
            "nautobot_dns_models.change_dnszone",
            "nautobot_dns_models.view_dnsview",
        )

    def test_a_selection_of_unenrolled_zones_is_handed_to_the_job(self):
        """Zones in no membership move, so the page redirects to the job it queued."""
        self.assertHttpStatus(self._apply(pk_list=[zone.pk for zone in self.loose_zones]), 302)

    def test_a_selection_naming_an_enrolled_zone_is_refused(self):
        """The pre-existing check: an enrolled zone among the posted ones is named."""
        body = self._apply_and_read(pk_list=[self.member_zone.pk, self.loose_zones[0].pk])
        self.assertIn(f"{self.REFUSAL} <strong>move-member.example</strong>.", body)

    def test_select_all_refuses_an_enrolled_zone_no_page_posted(self):
        """The whole selection is judged, so zones the page never offered are still caught."""
        body = self._apply_and_read(pk_list=[zone.pk for zone in self.loose_zones], edit_all=True)
        self.assertIn(
            f"{self.REFUSAL} <strong>move-catalog.example</strong>, <strong>move-member.example</strong>.",
            body,
        )

    def test_select_all_judges_only_the_filter_it_was_made_under(self):
        """`?type=primary` leaves the catalog zone out of the selection, so its member is named alone."""
        body = self._apply_and_read(
            pk_list=[zone.pk for zone in self.loose_zones],
            edit_all=True,
            query=f"?type={DNSZoneTypeChoices.TYPE_PRIMARY}",
        )
        self.assertIn(f"{self.REFUSAL} <strong>move-member.example</strong>.", body)

    def _apply(self, pk_list=None, edit_all=False, query=""):
        """Submit a bulk edit moving the selection into another view."""
        data = {
            "_apply": "",
            "dns_view": str(self.other_view.pk),
            "pk": [str(pk) for pk in pk_list or []],
        }
        if edit_all:
            data["_all"] = "on"

        return self.client.post(f"{self.bulk_edit_path}{query}", data)

    def _apply_and_read(self, **kwargs):
        """Submit a bulk edit expected to be refused, and return the page it re-rendered."""
        response = self._apply(**kwargs)
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))


class ZoneBulkAddMembershipTest(TestCase):
    """Tests for enrolling a selection of zones in one catalog from the zone list.

    The action exists because enrolling writes `CatalogZoneMembership` rows, which carry permissions of
    their own that the bulk edit job has no user to check and no transaction to undo.
    """

    ADD_WITHHELD = 'name="_apply" class="btn btn-primary" disabled'
    PERMISSION_REFUSED = "Adding to the catalog failed due to object-level permissions violation."
    RACE_REFUSED = "The selection changed while it was being added. Review it and try again."
    VIEW_REFUSED = "Not in this catalog zone"

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("add-catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("add-other.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.unenrolled_zones = [create_zone(f"add-free-{index}.example") for index in range(2)]
        cls.enrolled_zone = create_zone("add-enrolled.example")
        CatalogZoneMembership(catalog_zone=cls.other_catalog_zone, member_zone=cls.enrolled_zone).validated_save()

        cls.add_membership_path = reverse("plugins:nautobot_dns_models:dnszone_bulk_add_membership")
        cls.list_path = reverse("plugins:nautobot_dns_models:dnszone_list")

    def setUp(self):
        """Grant what reaching the action needs, leaving each test to add the membership it exercises."""
        super().setUp()
        self.add_permissions("nautobot_dns_models.view_dnszone", "nautobot_dns_models.change_dnszone")

    def test_the_list_offers_the_action_to_a_user_who_may_enroll(self):
        """With `add_catalogzonemembership`, the zone list offers the Add to Catalog action."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        self.assertIn(self.add_membership_path, self._zone_list())

    def test_the_list_withholds_the_action_without_permission_to_enroll(self):
        """With `change_dnszone` alone, the zone list withholds the action."""
        self.assertNotIn(self.add_membership_path, self._zone_list())

    def test_the_selection_is_confirmed_before_anything_is_written(self):
        """The confirmation pass names each selected zone and writes nothing."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        body = self._post(pk_list=[zone.pk for zone in self.unenrolled_zones])

        for zone in self.unenrolled_zones:
            self.assertIn(zone.name, body)
        self.assertNotIn(self.ADD_WITHHELD, body)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_applying_enrolls_the_selected_zones(self):
        """Applying enrolls each unenrolled zone in the chosen catalog."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        self._apply(self.unenrolled_zones, self.catalog_zone, expect=302)

        for zone in self.unenrolled_zones:
            self.assertEqual(self._catalog_of(zone), self.catalog_zone)

    def test_applying_logs_each_zone_with_its_catalog(self):
        """Each zone's change log names the catalog joined, though the list prefetches the zones' memberships."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        self._apply(self.unenrolled_zones, self.catalog_zone, expect=302)

        for zone in self.unenrolled_zones:
            change = ObjectChange.objects.get(changed_object_id=zone.pk)
            self.assertEqual(change.object_data_v2["catalog"]["id"], str(self.catalog_zone.pk))

    def test_applying_refuses_a_zone_already_enrolled_elsewhere(self):
        """A zone already in a catalog is refused on both passes and its membership is left alone."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        refusal = f"{DNSZoneBulkAddMembershipForm.ALREADY_ENROLLED} <strong>{self.enrolled_zone.name}</strong>."

        self.assertIn(refusal, self._post(pk_list=[self.enrolled_zone.pk]))
        self.assertIn(refusal, self._apply([self.enrolled_zone], self.catalog_zone, expect=200))
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)

    def test_an_enrolled_zone_in_the_selection_takes_the_whole_batch_back(self):
        """An already-enrolled zone in the selection is refused in full; unenrolled zones stay unenrolled."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = self.unenrolled_zones + [self.enrolled_zone]
        refusal = f"{DNSZoneBulkAddMembershipForm.ALREADY_ENROLLED} <strong>{self.enrolled_zone.name}</strong>."

        confirm = self._post(pk_list=[zone.pk for zone in selection])
        self.assertIn(refusal, confirm)
        self.assertIn(self.ADD_WITHHELD, confirm)
        self.assertIn(refusal, self._apply(selection, self.catalog_zone, expect=200))
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)
        for zone in self.unenrolled_zones:
            self.assertIsNone(self._catalog_of(zone))

    def test_a_zone_enrolled_after_the_form_judged_the_selection_takes_the_batch_back(self):
        """A zone enrolled after the form judged the selection is refused, and takes the batch with it.

        The form judges the selection as the confirmation page is built, so it cannot see a membership
        written between that page and the apply. The refusal is the model's: `validated_save()` raises
        on the unique constraint over `member_zone`, which rolls the batch's transaction back.
        """
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = self.unenrolled_zones + [self.enrolled_zone]

        # Stands in for the other writer's commit, which one request cannot stage.
        with patch.object(DNSZoneBulkAddMembershipForm, "_get_selection_errors", return_value=[]):
            body = self._apply(selection, self.catalog_zone, expect=200)

        self.assertIn("This zone already belongs to a catalog zone.", body)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)
        for zone in self.unenrolled_zones:
            self.assertIsNone(self._catalog_of(zone))

    def test_a_zone_enrolled_past_both_checks_is_reported_rather_than_crashing(self):
        """A membership the model's own check missed still meets the unique constraint, and is reported.

        `full_clean()` reads that constraint a moment before the insert, so a writer committing in
        between reaches the database instead. The batch rolls back either way, but the report is the
        difference: an `IntegrityError` left uncaught reaches the user as a server error.
        """
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = self.unenrolled_zones + [self.enrolled_zone]

        # Stands in for that writer, whose commit one request cannot stage.
        with (
            patch.object(DNSZoneBulkAddMembershipForm, "_get_selection_errors", return_value=[]),
            patch.object(CatalogZoneMembership, "full_clean"),
        ):
            body = self._apply(selection, self.catalog_zone, expect=200)

        self.assertIn(self.RACE_REFUSED, body)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)
        for zone in self.unenrolled_zones:
            self.assertIsNone(self._catalog_of(zone))

    def test_a_catalog_zone_in_the_selection_is_refused_by_name(self):
        """A catalog zone in the selection is refused on both passes, named in the report."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = [self.unenrolled_zones[0], self.other_catalog_zone]

        # The confirmation table lists every selected zone, so the name alone would prove nothing.
        refusal = f"{DNSZoneBulkAddMembershipForm.NESTING} <strong>{self.other_catalog_zone.name}</strong>."
        self.assertIn(refusal, self._post(pk_list=[zone.pk for zone in selection]))
        self.assertIn(refusal, self._apply(selection, self.catalog_zone, expect=200))
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_a_long_list_of_offenders_is_capped_at_a_readable_length(self):
        """Past five names the report counts the rest, and the names it gives stay bolded."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        catalogs = [
            create_zone(f"add-many-{index}.example", type=DNSZoneTypeChoices.TYPE_CATALOG) for index in range(7)
        ]

        body = self._post(pk_list=[zone.pk for zone in catalogs])

        self.assertIn("<strong>add-many-0.example</strong>", body)
        self.assertIn(", and 2 more.", body)

    def test_a_refused_selection_is_offered_no_catalog_to_choose(self):
        """A refused selection disables both the Apply button and the catalog picker."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = [self.unenrolled_zones[0], self.other_catalog_zone]

        self.assertIn(self.ADD_WITHHELD, self._post(pk_list=[zone.pk for zone in selection]))

        form = DNSZoneBulkAddMembershipForm(DNSZone.objects.filter(pk__in=[zone.pk for zone in selection]))
        self.assertTrue(form.fields["catalog"].disabled)

    def test_both_faults_in_one_selection_are_reported_together(self):
        """A selection that both nests and spans views reports both refusals at once."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        stranger = create_zone("add-elsewhere.example", dns_view=DNSView.objects.create(name="Add Span View"))

        body = self._post(pk_list=[zone.pk for zone in (self.unenrolled_zones[0], self.other_catalog_zone, stranger)])

        self.assertIn(DNSZoneBulkAddMembershipForm.NESTING, body)
        self.assertIn(DNSZoneBulkAddMembershipForm.SPANS_VIEWS, body)

    def test_the_picker_offers_only_catalogs_in_the_view_the_selection_shares(self):
        """The picker carries the selection's view as a `dns_view` query param."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        body = self._post(pk_list=[zone.pk for zone in self.unenrolled_zones])

        view_id = self.unenrolled_zones[0].dns_view_id
        self.assertIn(f'data-query-param-dns_view="[&quot;{view_id}&quot;]"', body)

    def test_a_selection_spanning_views_cannot_be_enrolled_at_all(self):
        """A selection spanning views is refused on both passes and enrolls nothing."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = [
            self.unenrolled_zones[0],
            create_zone("add-elsewhere.example", dns_view=DNSView.objects.create(name="Add Span View")),
        ]

        self.assertIn(DNSZoneBulkAddMembershipForm.SPANS_VIEWS, self._post(pk_list=[zone.pk for zone in selection]))
        self.assertIn(DNSZoneBulkAddMembershipForm.SPANS_VIEWS, self._apply(selection, self.catalog_zone, expect=200))
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_a_catalog_in_another_view_is_refused(self):
        """A catalog in another view is refused and nothing is enrolled."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        stranger = create_zone(
            "add-stranger.example",
            type=DNSZoneTypeChoices.TYPE_CATALOG,
            dns_view=DNSView.objects.create(name="Add Test View"),
        )

        body = self._apply(self.unenrolled_zones, stranger, expect=200)

        self.assertIn(self.VIEW_REFUSED, body)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_select_all_follows_the_filter_it_was_made_under(self):
        """With `?name=<zone>`, "select all" enrolls only the filtered zone."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        query = f"?name={self.unenrolled_zones[0].name}"

        response = self.client.post(
            f"{self.add_membership_path}{query}",
            {"_all": "on", "_apply": "", "catalog": str(self.catalog_zone.pk)},
        )
        self.assertHttpStatus(response, 302)

        self.assertEqual(self._catalog_of(self.unenrolled_zones[0]), self.catalog_zone)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[1]))

    def test_a_constraint_on_the_membership_is_enforced(self):
        """A membership permission narrowed to one catalog must not reach another."""
        object_permission = ObjectPermission(
            name="Bulk enroll in one catalog only",
            actions=["add"],
            constraints={"catalog_zone__name": self.catalog_zone.name},
        )
        object_permission.save()
        object_permission.users.add(self.user)
        object_permission.object_types.add(ContentType.objects.get_for_model(CatalogZoneMembership))

        self.assertIn(self.PERMISSION_REFUSED, self._apply(self.unenrolled_zones, self.other_catalog_zone, expect=200))
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

        self._apply(self.unenrolled_zones, self.catalog_zone, expect=302)
        self.assertEqual(self._catalog_of(self.unenrolled_zones[0]), self.catalog_zone)

    def _apply(self, zones, catalog, expect):
        """Post the applying pass for `zones`, and return the page when it is redisplayed."""
        return self._post(
            pk_list=[zone.pk for zone in zones],
            data={"_apply": "", "catalog": str(catalog.pk)},
            expect=expect,
        )

    def _catalog_of(self, zone):
        """Return the catalog `zone` is enrolled in, read back from the database."""
        return DNSZone.objects.get(pk=zone.pk).catalog

    def _post(self, pk_list, data=None, expect=200):
        """Post a selection to the action, returning the rendered page for the passes that render one."""
        response = self.client.post(self.add_membership_path, {"pk": [str(pk) for pk in pk_list], **(data or {})})
        self.assertHttpStatus(response, expect)
        if expect != 200:
            return ""

        return extract_page_body(response.content.decode(response.charset))

    def _zone_list(self):
        """Return the zone list page, where the bulk action buttons are rendered."""
        response = self.client.get(self.list_path)
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))


class ZoneBulkRemoveMembershipTest(TestCase):
    """Tests for removing a selection of zones from the catalogs holding them.

    The twin of the enroll action, and separate from it for the same reason: the memberships are
    governed apart from the zones, and the membership itself has no list to delete them from.
    """

    PERMISSION_REFUSED = "Removing from the catalog failed due to object-level permissions violation."
    REMOVE_WITHHELD = 'name="_apply" class="btn btn-danger" disabled'

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("remove-catalog.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("remove-other.example", type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.enrolled_zones = [create_zone(f"remove-member-{index}.example") for index in range(2)]
        for zone in cls.enrolled_zones:
            CatalogZoneMembership(catalog_zone=cls.catalog_zone, member_zone=zone).validated_save()
        cls.free_zone = create_zone("remove-free.example")
        cls.elsewhere_zone = create_zone("remove-elsewhere.example")
        CatalogZoneMembership(catalog_zone=cls.other_catalog_zone, member_zone=cls.elsewhere_zone).validated_save()

        cls.list_path = reverse("plugins:nautobot_dns_models:dnszone_list")
        cls.remove_membership_path = reverse("plugins:nautobot_dns_models:dnszone_bulk_remove_membership")

    def setUp(self):
        """Grant what reaching the action needs, leaving each test to add the withdrawal it exercises."""
        super().setUp()
        self.add_permissions("nautobot_dns_models.view_dnszone", "nautobot_dns_models.change_dnszone")

    def test_the_list_offers_the_action_to_a_user_who_may_withdraw(self):
        """With `delete_catalogzonemembership`, the zone list offers the Remove from Catalog action."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        self.assertIn(self.remove_membership_path, self._zone_list())

    def test_the_list_withholds_the_action_without_permission_to_withdraw(self):
        """With `change_dnszone` alone, the zone list withholds the action."""
        self.assertNotIn(self.remove_membership_path, self._zone_list())

    def test_the_selection_is_confirmed_before_anything_is_removed(self):
        """The confirmation pass counts the memberships at stake and removes nothing."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        body = self._post(pk_list=[zone.pk for zone in self.enrolled_zones])

        self.assertIn("2 of them in a catalog zone", body)
        self.assertNotIn(self.REMOVE_WITHHELD, body)
        # The applying pass is only reachable from this page if it carries the confirmation with it.
        self.assertIn('name="confirm"', body)
        self.assertEqual(self._catalog_of(self.enrolled_zones[0]), self.catalog_zone)

    def test_applying_withdraws_the_selected_zones(self):
        """Applying removes each membership, whichever catalog was holding it."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        self._apply(self.enrolled_zones + [self.elsewhere_zone], expect=302)

        for zone in self.enrolled_zones + [self.elsewhere_zone]:
            self.assertIsNone(self._catalog_of(zone))

    def test_the_catalog_stops_publishing_a_withdrawn_zone(self):
        """A withdrawal drops the member PTR from the catalog zone, leaving the other members' PTRs."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        self._apply([self.enrolled_zones[0]], expect=302)

        published = list(PTRRecord.objects.filter(zone=self.catalog_zone).values_list("ptrdname", flat=True))
        self.assertNotIn(self.enrolled_zones[0].name, published)
        self.assertIn(self.enrolled_zones[1].name, published)

    def test_a_zone_with_no_catalog_is_left_alone_rather_than_refused(self):
        """An unenrolled zone in the selection is counted out and skipped rather than refused."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        body = self._post(pk_list=[self.enrolled_zones[0].pk, self.free_zone.pk])
        self.assertIn("2 DNS Zones selected, 1 of them in a catalog zone", body)

        self._apply([self.enrolled_zones[0], self.free_zone], expect=302)
        self.assertIsNone(self._catalog_of(self.enrolled_zones[0]))

    def test_a_membership_removed_by_another_writer_is_not_counted(self):
        """The message counts the rows this request deleted, not the rows it selected.

        Another writer can remove a selected membership after the selection is read. That row is
        then gone before this request deletes it, so it is not counted as removed here.
        """
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        removed_elsewhere = self.enrolled_zones[0]

        def remove_one_elsewhere(*_):
            CatalogZoneMembership.objects.filter(member_zone=removed_elsewhere).delete()

        with patch.object(
            DNSZoneUIViewSet, "_require_bulk_membership_permission", autospec=True, side_effect=remove_one_elsewhere
        ):
            response = self.client.post(
                self.remove_membership_path,
                {"pk": [str(zone.pk) for zone in self.enrolled_zones], "_apply": "", "confirm": "True"},
            )

        self.assertHttpStatus(response, 302)
        self.assertEqual(
            [str(message) for message in get_messages(response.wsgi_request)],
            ["Removed 1 zones from their catalogs."],
        )
        self.assertIsNone(self._catalog_of(self.enrolled_zones[1]))

    def test_a_selection_holding_no_memberships_is_offered_nothing_to_confirm(self):
        """A selection holding no memberships is counted at zero and its Apply button disabled."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        body = self._post(pk_list=[self.free_zone.pk, self.catalog_zone.pk])

        self.assertIn("2 DNS Zones selected, 0 of them in a catalog zone", body)
        self.assertIn(self.REMOVE_WITHHELD, body)

    def test_withdrawing_without_permission_is_refused(self):
        """Without `delete_catalogzonemembership`, the applying pass is refused with a 403."""
        response = self.client.post(
            self.remove_membership_path,
            {"pk": [str(self.enrolled_zones[0].pk)], "_apply": "", "confirm": "True"},
        )

        self.assertHttpStatus(response, 403)
        self.assertEqual(self._catalog_of(self.enrolled_zones[0]), self.catalog_zone)

    def test_a_constraint_on_the_membership_takes_the_whole_batch_back(self):
        """A withdrawal permission narrowed to one catalog must not reach another, nor half-apply."""
        object_permission = ObjectPermission(
            name="Bulk withdraw from one catalog only",
            actions=["delete"],
            constraints={"catalog_zone__name": self.catalog_zone.name},
        )
        object_permission.save()
        object_permission.users.add(self.user)
        object_permission.object_types.add(ContentType.objects.get_for_model(CatalogZoneMembership))

        body = self._apply(self.enrolled_zones + [self.elsewhere_zone], expect=200)
        self.assertIn(self.PERMISSION_REFUSED, body)
        self.assertEqual(self._catalog_of(self.enrolled_zones[0]), self.catalog_zone)
        self.assertEqual(self._catalog_of(self.elsewhere_zone), self.other_catalog_zone)

        self._apply(self.enrolled_zones, expect=302)
        self.assertIsNone(self._catalog_of(self.enrolled_zones[0]))

    def test_select_all_follows_the_filter_it_was_made_under(self):
        """With `?name=<zone>`, "select all" removes only the filtered zone's membership."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        query = f"?name={self.enrolled_zones[0].name}"

        response = self.client.post(
            f"{self.remove_membership_path}{query}", {"_all": "on", "_apply": "", "confirm": "True"}
        )
        self.assertHttpStatus(response, 302)

        self.assertIsNone(self._catalog_of(self.enrolled_zones[0]))
        self.assertEqual(self._catalog_of(self.enrolled_zones[1]), self.catalog_zone)

    def _apply(self, zones, expect):
        """Post the applying pass for `zones`, and return the page when it is redisplayed."""
        return self._post(
            pk_list=[zone.pk for zone in zones],
            data={"_apply": "", "confirm": "True"},
            expect=expect,
        )

    def _catalog_of(self, zone):
        """Return the catalog `zone` is enrolled in, read back from the database."""
        return DNSZone.objects.get(pk=zone.pk).catalog

    def _post(self, pk_list, data=None, expect=200):
        """Post a selection to the action, returning the rendered page for the passes that render one."""
        response = self.client.post(self.remove_membership_path, {"pk": [str(pk) for pk in pk_list], **(data or {})})
        self.assertHttpStatus(response, expect)
        if expect != 200:
            return ""

        return extract_page_body(response.content.decode(response.charset))

    def _zone_list(self):
        """Return the zone list page, where the bulk action buttons are rendered."""
        response = self.client.get(self.list_path)
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))
