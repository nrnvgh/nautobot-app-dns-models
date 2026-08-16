"""Unit tests for views."""
# pylint: disable=too-many-lines

import re
import uuid

from constance import config as constance_config
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.urls import reverse
from nautobot.apps.testing import AssertNoRepeatedQueries, TestCase, ViewTestCases, post_data
from nautobot.core.testing.utils import extract_page_body
from nautobot.extras.models import Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix
from nautobot.users.models import ObjectPermission
from netutils.ip import ipaddress_address

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.forms import DNSZoneBulkAddMembershipForm, DNSZoneWithCatalogBulkEditForm
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
        DNSRegistrar.objects.create(name="Registrar 1", url="https://registrar1.example", account_number="ACC-001")
        DNSRegistrar.objects.create(name="Registrar 2", url="https://registrar2.example", account_number="ACC-002")
        DNSRegistrar.objects.create(name="Registrar 3", url="https://registrar3.example", account_number="ACC-003")

        cls.form_data = {
            "name": "Registrar Test",
            "url": "https://registrar-test.example",
            "account_number": "ACC-TEST",
        }

        cls.csv_data = (
            "name,url,account_number",
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
            "zone_type": DNSZoneTypeChoices.TYPE_PRIMARY,
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

        cls.bulk_edit_data = {"description": "Bulk edit views", "enabled": False}

    def test_list_names_each_zone_catalog_without_per_zone_queries(self):
        """The catalog column reads the membership from the view's prefetch, not once per row."""
        catalog = DNSZone.objects.create(name="catalog-list.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
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
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")
        cls.membership = CatalogZoneMembership(catalog_zone=cls.catalog_zone, member_zone=cls.member_zone)
        cls.membership.validated_save()
        cls.member_zone_record = TXTRecord(name="txt", text="a user record", zone=cls.member_zone)
        cls.member_zone_record.validated_save()

    def test_primary_zone_offers_every_record_panel(self):
        """Gating the record panels must leave an ordinary zone exactly as it was."""
        self.assertLessEqual(self.RECORD_PANELS, self._panel_headings(self.member_zone))

    def test_catalog_zone_keeps_only_the_record_panels_it_has_records_for(self):
        """No record type is user-creatable in a catalog zone, but the records it holds are worth showing."""
        self.assertEqual(self.RECORD_PANELS & self._panel_headings(self.catalog_zone), {"NS RECORDS", "TXT RECORDS"})

    def test_catalog_zone_shows_the_version_record(self):
        """The catalog's RFC 9432 version record."""
        record = TXTRecord.objects.get(zone=self.catalog_zone)
        self.assertIn(record.get_absolute_url(), self._detail(self.catalog_zone))

    def test_catalog_zone_shows_the_apex_ns_record(self):
        """The apex NS RRset is part of a catalog zone's required contents, so the page accounts for it."""
        record = NSRecord.objects.get(zone=self.catalog_zone)
        self.assertIn(record.get_absolute_url(), self._detail(self.catalog_zone))

    def test_catalog_zone_offers_no_write_controls_for_the_version_record(self):
        """Every write the selection and action columns start is one the model refuses."""
        self.add_permissions("nautobot_dns_models.change_txtrecord")
        record = TXTRecord.objects.get(zone=self.catalog_zone)
        url = reverse("plugins:nautobot_dns_models:txtrecord_edit", args=(record.pk,))
        self.assertNotIn(url, self._detail(self.catalog_zone))

    def test_catalog_zone_offers_no_write_controls_for_the_apex_ns_record(self):
        """The apex NS is as system-managed as the version TXT, so it is listed the same way."""
        self.add_permissions("nautobot_dns_models.change_nsrecord")
        record = NSRecord.objects.get(zone=self.catalog_zone)
        url = reverse("plugins:nautobot_dns_models:nsrecord_edit", args=(record.pk,))
        self.assertNotIn(url, self._detail(self.catalog_zone))

    def test_primary_zone_keeps_write_controls_for_its_records(self):
        """A system-managed TXT panel is catalog-only; an ordinary zone's TXT records stay editable."""
        self.add_permissions("nautobot_dns_models.change_txtrecord")
        url = reverse("plugins:nautobot_dns_models:txtrecord_edit", args=(self.member_zone_record.pk,))
        self.assertIn(url, self._detail(self.member_zone))

    def test_catalog_zone_offers_no_add_button_for_records(self):
        """A panel supplies its own Add button, which the hidden Add Records menu would otherwise not cover."""
        self.add_permissions("nautobot_dns_models.add_txtrecord")
        url = reverse("plugins:nautobot_dns_models:txtrecord_add")
        self.assertNotIn(url, self._detail(self.catalog_zone))

    def test_primary_zone_keeps_the_add_button_on_its_record_panels(self):
        """Suppressing the catalog's Add button must not reach the panels an ordinary zone shares."""
        self.add_permissions("nautobot_dns_models.add_txtrecord")
        url = reverse("plugins:nautobot_dns_models:txtrecord_add")
        self.assertIn(url, self._detail(self.member_zone))

    def test_catalog_zone_hides_the_add_records_menu(self):
        """With no children left to offer, the dropdown itself must not draw."""
        self.add_permissions("nautobot_dns_models.change_dnszone", "nautobot_dns_models.add_arecord")
        self.assertNotIn("Add Records", self._detail(self.catalog_zone))

    def test_primary_zone_keeps_the_add_records_menu(self):
        """The gating must not cost an ordinary zone its add affordances."""
        self.add_permissions("nautobot_dns_models.change_dnszone", "nautobot_dns_models.add_arecord")
        self.assertIn("Add Records", self._detail(self.member_zone))

    def test_catalog_zone_lists_its_members(self):
        """The membership is the operator-facing object, so the catalog leads with it."""
        self.assertIn("MEMBER ZONES", self._panel_headings(self.catalog_zone))
        self.assertIn(self.membership.member_label, self._detail(self.catalog_zone))

    def test_primary_zone_has_no_member_zones_panel(self):
        """Only a zone that publishes members has anything to list here."""
        self.assertNotIn("MEMBER ZONES", self._panel_headings(self.member_zone))

    def test_catalog_zone_has_no_record_statistics(self):
        """The counts are of record types a zone without user records cannot hold."""
        self.assertNotIn("RECORDS STATISTICS", self._panel_headings(self.catalog_zone))

    def test_catalog_zone_has_no_registration_panel(self):
        """A catalog zone is not a registered name, so the registrar row does not belong here."""
        self.assertNotIn("REGISTRATION", self._panel_headings(self.catalog_zone))

    def test_primary_zone_keeps_the_registration_panel(self):
        """Hiding registration on a catalog must not take it off an ordinary zone."""
        self.assertIn("REGISTRATION", self._panel_headings(self.member_zone))

    def test_primary_zone_keeps_record_statistics(self):
        """Gating that panel by capability must leave it standing where the counts mean something."""
        self.assertIn("RECORDS STATISTICS", self._panel_headings(self.member_zone))

    def test_member_zone_names_the_catalog_it_belongs_to(self):
        """The membership is reachable from the member's own page, not just the catalog's."""
        content = self._detail(self.member_zone)
        self.assertInHTML("<td>Catalog Zone</td>", content, 1)
        self.assertIn(self.catalog_zone.name, content)

    def test_catalog_zone_omits_the_catalog_field(self):
        """A zone that cannot belong to a catalog has no membership row to show."""
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
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
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
    CHANGE_REFUSED = "You do not have permission to move a zone to another catalog."
    DELETE_REFUSED = "You do not have permission to remove a zone from its catalog."

    def test_enrolling_requires_add_permission(self):
        """Creating a membership from the zone form is still creating a membership."""
        self._assert_refused(self._edit(self.unenrolled_zone, self.catalog_zone), self.ADD_REFUSED)
        self.assertIsNone(self._catalog_of(self.unenrolled_zone))

    def test_enrolling_is_allowed_with_add_permission(self):
        """The field must remain usable by anyone entitled to the membership it writes."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        self.assertHttpStatus(self._edit(self.unenrolled_zone, self.catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.unenrolled_zone), self.catalog_zone)

    def test_moving_requires_change_permission(self):
        """Retargeting the existing row is a change to it, not a new membership."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        self._assert_refused(self._edit(self.enrolled_zone, self.other_catalog_zone), self.CHANGE_REFUSED)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_moving_is_allowed_with_change_permission(self):
        """A move keeps the membership and its label, so change permission is the whole of it."""
        self.add_permissions("nautobot_dns_models.change_catalogzonemembership")
        self.assertHttpStatus(self._edit(self.enrolled_zone, self.other_catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)

    def test_withdrawing_requires_delete_permission(self):
        """Clearing the field deletes the membership and the catalog's PTR along with it."""
        self.add_permissions("nautobot_dns_models.change_catalogzonemembership")
        self._assert_refused(self._edit(self.enrolled_zone), self.DELETE_REFUSED)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_withdrawing_is_allowed_with_delete_permission(self):
        """Nothing is created or retargeted, so delete permission alone must suffice."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        self.assertHttpStatus(self._edit(self.enrolled_zone), 302)
        self.assertIsNone(self._catalog_of(self.enrolled_zone))

    def test_editing_an_enrolled_zone_leaves_its_membership_alone(self):
        """Resubmitting the catalog a zone already has asks for nothing, so it must demand nothing."""
        self.assertHttpStatus(self._edit(self.enrolled_zone, self.catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_renaming_an_enrolled_zone_needs_no_membership_permission(self):
        """Withdrawing and re-enrolling on a rename is not a membership change the user requested.

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

    def test_renaming_and_moving_in_one_submission_is_accepted(self):
        """A rename replaces the membership row, and the move must then act on the replacement.

        `DNSZone.save()` re-enrolls a renamed zone before the form syncs the catalog, so the row the
        form started with is gone by then. Acting on it enrolls the zone twice.
        """
        self.add_permissions("nautobot_dns_models.change_catalogzonemembership")
        data = self._zone_data(zone=self.enrolled_zone, catalog=self.other_catalog_zone)
        data["name"] = "renamed-and-moved.example"

        response = self.client.post(
            reverse("plugins:nautobot_dns_models:dnszone_edit", args=(self.enrolled_zone.pk,)), data
        )

        self.assertHttpStatus(response, 302)
        self.assertEqual(DNSZone.objects.get(pk=self.enrolled_zone.pk).name, "renamed-and-moved.example")
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)

    def test_creating_an_enrolled_zone_requires_add_permission(self):
        """The zone is written before the membership is judged, so the refusal must take it back out."""
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
            "zone_type": DNSZoneTypeChoices.TYPE_PRIMARY,
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


class CatalogZoneMembershipViewTest(
    ViewTestCases.CreateObjectViewTestCase,
    ViewTestCases.EditObjectViewTestCase,
    ViewTestCases.DeleteObjectViewTestCase,
):
    """Test the membership add, edit, and delete pages.

    Create looks up the new row by `member_zone`. The mixin uses `queryset.last()`, which follows
    `ordering = ["catalog_zone", "member_label"]`, and CatalogZoneMembership has no `last_updated`.
    """

    model = CatalogZoneMembership

    @classmethod
    def setUpTestData(cls):
        catalogs = [
            create_zone("view-catalog-0.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG),
            create_zone("view-catalog-1.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG),
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
        # `member_zone` is required on the form. Changing it remints the label, so keep the first
        # row's member and only move the catalog. `label0` is first() under the model's ordering.
        cls.update_data = {
            "catalog_zone": catalogs[1].pk,
            "member_zone": members[0].pk,
        }

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
        """The catalog's Add button names the catalog so the operator only picks a member."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        response = self.client.get(self._get_url("add"), {"catalog_zone": self.catalog_zone.pk})
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertIn('name="catalog_zone"', body)
        self.assertIn(str(self.catalog_zone.pk), body)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_add_page_seeds_the_member_zone_from_the_query(self):
        """Add to Catalog on an unenrolled zone names that zone so the operator only picks a catalog."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        response = self.client.get(self._get_url("add"), {"member_zone": self.unenrolled_zone.pk})
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertIn('name="member_zone"', body)
        self.assertIn(str(self.unenrolled_zone.pk), body)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_adding_follows_the_return_url(self):
        """The form carries ReturnURLForm so the catalog Add button can send the operator back."""
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
    def test_catalog_detail_links_to_add_edit_and_delete(self):
        """The Member Zones panel is how these pages are reached from the catalog."""
        self.add_permissions(
            "nautobot_dns_models.add_catalogzonemembership",
            "nautobot_dns_models.change_catalogzonemembership",
            "nautobot_dns_models.delete_catalogzonemembership",
        )
        add_url = self._get_url("add")
        list_url = reverse("plugins:nautobot_dns_models:dnszone_list")

        response = self.client.get(self.catalog_zone.get_absolute_url())
        self.assertHttpStatus(response, 200)
        body = extract_page_body(response.content.decode(response.charset))

        self.assertIn(f"{add_url}?catalog_zone={self.catalog_zone.pk}", body)
        self.assertIn(self._get_url("edit", self.membership), body)
        self.assertIn(self._get_url("delete", self.membership), body)
        self.assertIn(f"{list_url}?catalog={self.catalog_zone.pk}", body)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_zone_list_links_an_unenrolled_zone_to_add(self):
        """Add to Catalog is the unenrolled row's path onto the add page."""
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
        """Remove is the enrolled row's list action; Move lives on the catalog panel and the zone form."""
        self.add_permissions(
            "nautobot_dns_models.change_catalogzonemembership",
            "nautobot_dns_models.delete_catalogzonemembership",
        )
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
        cls.catalog_zone = create_zone("bulk-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.primary_zones = [create_zone(f"bulk-primary-{index}.example") for index in range(2)]
        cls.bulk_edit_path = reverse("plugins:nautobot_dns_models:dnszone_bulk_edit")

    def setUp(self):
        """Grant the permissions a bulk edit needs before its selection is judged."""
        super().setUp()
        self.add_permissions("nautobot_dns_models.view_dnszone", "nautobot_dns_models.change_dnszone")

    def test_a_selection_of_primary_zones_offers_the_control(self):
        """Every one of these zones can take the flag, so nothing is withheld."""
        content = self._bulk_edit_form(pk_list=[zone.pk for zone in self.primary_zones])
        self.assertIn('name="auto_create_ptr"', content)
        self.assertNotIn(self.WITHDRAWN, content)

    def test_a_selection_holding_a_catalog_zone_withdraws_the_control(self):
        """One catalog zone is enough: the flag is refused per object, not per selection."""
        content = self._bulk_edit_form(pk_list=[self.primary_zones[0].pk, self.catalog_zone.pk])
        self.assertIn(self.WITHDRAWN, content)

    def test_select_all_withdraws_the_control_when_it_includes_a_catalog_zone(self):
        """Nothing narrows this one, so it resolves to the catalog zone without ever naming it."""
        self.assertIn(self.WITHDRAWN, self._bulk_edit_form(edit_all=True))

    def test_select_all_keeps_the_control_when_filtered_to_primary_zones(self):
        """A filter narrows what "select all" resolves to, and the judgement must follow it."""
        content = self._bulk_edit_form(edit_all=True, query=f"?zone_type={DNSZoneTypeChoices.TYPE_PRIMARY}")
        self.assertIn('name="auto_create_ptr"', content)
        self.assertNotIn(self.WITHDRAWN, content)

    def test_a_withdrawn_control_discards_a_submitted_value(self):
        """The job applies the view's cleaned data, so a value the form disowns never reaches a zone."""
        form = DNSZoneWithCatalogBulkEditForm(
            DNSZone,
            {"pk": [str(zone.pk) for zone in self.primary_zones], "auto_create_ptr": "True"},
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


class ZoneBulkAddMembershipTest(TestCase):
    """Tests for enrolling a selection of zones in one catalog from the zone list.

    The action exists because enrolling writes `CatalogZoneMembership` rows, which carry permissions of
    their own that the bulk edit job has no user to check and no transaction to undo.
    """

    ADD_WITHHELD = 'name="_apply" class="btn btn-primary" disabled'
    NESTING_REFUSED = "A catalog zone cannot belong to another catalog zone"
    PERMISSION_REFUSED = "Adding to the catalog failed due to object-level permissions violation."
    VIEW_REFUSED = "Not in this catalog zone"

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("add-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("add-other.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
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
        """The button is offered on the membership's permission, not the zone's."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        self.assertIn(self.add_membership_path, self._zone_list())

    def test_the_list_withholds_the_action_without_permission_to_enroll(self):
        """`change_dnszone` alone does not authorize a membership change, so it does not offer it."""
        self.assertNotIn(self.add_membership_path, self._zone_list())

    def test_the_selection_is_confirmed_before_anything_is_written(self):
        """The first pass names the zones back to the user and leaves them as they were."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        body = self._post(pk_list=[zone.pk for zone in self.unenrolled_zones])

        for zone in self.unenrolled_zones:
            self.assertIn(zone.name, body)
        self.assertNotIn(self.ADD_WITHHELD, body)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_applying_enrolls_the_selected_zones(self):
        """The zones that had no catalog are added to the one chosen."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        self._apply(self.unenrolled_zones, self.catalog_zone, expect=302)

        for zone in self.unenrolled_zones:
            self.assertEqual(self._catalog_of(zone), self.catalog_zone)

    def test_applying_moves_a_zone_already_enrolled_elsewhere(self):
        """Moving is a change to an existing membership, so it takes that permission too."""
        self.add_permissions(
            "nautobot_dns_models.add_catalogzonemembership", "nautobot_dns_models.change_catalogzonemembership"
        )

        self._apply([self.enrolled_zone], self.catalog_zone, expect=302)

        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_a_move_without_change_permission_takes_the_whole_batch_back(self):
        """One refusal rolls the transaction back, so the zones it would have enrolled stay free."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        body = self._apply(self.unenrolled_zones + [self.enrolled_zone], self.catalog_zone, expect=200)

        self.assertIn(self.PERMISSION_REFUSED, body)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)
        for zone in self.unenrolled_zones:
            self.assertIsNone(self._catalog_of(zone))

    def test_a_catalog_zone_in_the_selection_is_refused_by_name(self):
        """Nesting is unsupported, and the report names the zone so the selection can be corrected."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = [self.unenrolled_zones[0], self.other_catalog_zone]

        # The confirmation table lists every selected zone, so the name alone would prove nothing.
        refusal = f"{self.NESTING_REFUSED}, and the selection holds <strong>{self.other_catalog_zone.name}</strong>."
        self.assertIn(refusal, self._post(pk_list=[zone.pk for zone in selection]))
        self.assertIn(refusal, self._apply(selection, self.catalog_zone, expect=200))
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_a_long_list_of_offenders_is_capped_at_a_readable_length(self):
        """Past five names the report counts the rest, and the names it does give stay marked up."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        catalogs = [
            create_zone(f"add-many-{index}.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG) for index in range(7)
        ]

        body = self._post(pk_list=[zone.pk for zone in catalogs])

        self.assertIn("<strong>add-many-0.example</strong>", body)
        self.assertIn(", and 2 more.", body)

    def test_a_refused_selection_is_offered_no_catalog_to_choose(self):
        """The judgement lands before a catalog is asked for, so neither control invites the attempt."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = [self.unenrolled_zones[0], self.other_catalog_zone]

        self.assertIn(self.ADD_WITHHELD, self._post(pk_list=[zone.pk for zone in selection]))

        form = DNSZoneBulkAddMembershipForm(DNSZone.objects.filter(pk__in=[zone.pk for zone in selection]))
        self.assertTrue(form.fields["catalog"].disabled)

    def test_both_faults_in_one_selection_are_reported_together(self):
        """Correcting one fault must not uncover the other on the next attempt."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        stranger = create_zone("add-elsewhere.example", dns_view=DNSView.objects.create(name="Add Span View"))

        body = self._post(pk_list=[zone.pk for zone in (self.unenrolled_zones[0], self.other_catalog_zone, stranger)])

        self.assertIn(self.NESTING_REFUSED, body)
        self.assertIn(DNSZoneBulkAddMembershipForm.SPANS_VIEWS, body)

    def test_the_picker_offers_only_catalogs_in_the_view_the_selection_shares(self):
        """A catalog holds zones from its own view alone, so the rest are never put on offer."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")

        body = self._post(pk_list=[zone.pk for zone in self.unenrolled_zones])

        view_id = self.unenrolled_zones[0].dns_view_id
        self.assertIn(f'data-query-param-dns_view="[&quot;{view_id}&quot;]"', body)

    def test_a_selection_spanning_views_cannot_be_enrolled_at_all(self):
        """No one catalog could hold them, so the page says so rather than offering a choice that fails."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        selection = [
            self.unenrolled_zones[0],
            create_zone("add-elsewhere.example", dns_view=DNSView.objects.create(name="Add Span View")),
        ]

        self.assertIn(DNSZoneBulkAddMembershipForm.SPANS_VIEWS, self._post(pk_list=[zone.pk for zone in selection]))
        self.assertIn(DNSZoneBulkAddMembershipForm.SPANS_VIEWS, self._apply(selection, self.catalog_zone, expect=200))
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_a_catalog_in_another_view_is_refused(self):
        """A catalog can only hold zones from its own view, which the model would reject one at a time."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemembership")
        stranger = create_zone(
            "add-stranger.example",
            zone_type=DNSZoneTypeChoices.TYPE_CATALOG,
            dns_view=DNSView.objects.create(name="Add Test View"),
        )

        body = self._apply(self.unenrolled_zones, stranger, expect=200)

        self.assertIn(self.VIEW_REFUSED, body)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_select_all_follows_the_filter_it_was_made_under(self):
        """ "Select all" is resolved from the filter, not from the rows the browser happened to hold."""
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
        cls.catalog_zone = create_zone("remove-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("remove-other.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
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
        """The button is offered on the membership's permission, not the zone's."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")
        self.assertIn(self.remove_membership_path, self._zone_list())

    def test_the_list_withholds_the_action_without_permission_to_withdraw(self):
        """`change_dnszone` alone does not authorize withdrawal, so it does not offer it either."""
        self.assertNotIn(self.remove_membership_path, self._zone_list())

    def test_the_selection_is_confirmed_before_anything_is_removed(self):
        """The first pass counts the memberships at stake and leaves them as they were."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        body = self._post(pk_list=[zone.pk for zone in self.enrolled_zones])

        self.assertIn("2 of them in a catalog zone", body)
        self.assertNotIn(self.REMOVE_WITHHELD, body)
        # The applying pass is only reachable from this page if it carries the confirmation with it.
        self.assertIn('name="confirm"', body)
        self.assertEqual(self._catalog_of(self.enrolled_zones[0]), self.catalog_zone)

    def test_applying_withdraws_the_selected_zones(self):
        """Each membership goes, whichever catalog was holding it."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        self._apply(self.enrolled_zones + [self.elsewhere_zone], expect=302)

        for zone in self.enrolled_zones + [self.elsewhere_zone]:
            self.assertIsNone(self._catalog_of(zone))

    def test_the_catalog_stops_publishing_a_withdrawn_zone(self):
        """The PTR that published the membership is the point of removing it."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        self._apply([self.enrolled_zones[0]], expect=302)

        published = list(PTRRecord.objects.filter(zone=self.catalog_zone).values_list("ptrdname", flat=True))
        self.assertNotIn(self.enrolled_zones[0].name, published)
        self.assertIn(self.enrolled_zones[1].name, published)

    def test_a_zone_with_no_catalog_is_left_alone_rather_than_refused(self):
        """A selection is rarely all of one kind, so the unenrolled are counted out and skipped."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        body = self._post(pk_list=[self.enrolled_zones[0].pk, self.free_zone.pk])
        self.assertIn("2 DNS Zones selected, 1 of them in a catalog zone", body)

        self._apply([self.enrolled_zones[0], self.free_zone], expect=302)
        self.assertIsNone(self._catalog_of(self.enrolled_zones[0]))

    def test_a_selection_holding_no_memberships_is_offered_nothing_to_confirm(self):
        """With nothing to remove, the page says so rather than inviting a write that does nothing."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemembership")

        body = self._post(pk_list=[self.free_zone.pk, self.catalog_zone.pk])

        self.assertIn("2 DNS Zones selected, 0 of them in a catalog zone", body)
        self.assertIn(self.REMOVE_WITHHELD, body)

    def test_withdrawing_without_permission_is_refused(self):
        """The zone's own change permission does not carry the membership's."""
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
        """ "Select all" is resolved from the filter, not from the rows the browser happened to hold."""
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
