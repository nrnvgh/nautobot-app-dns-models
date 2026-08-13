"""Test the zone pages and forms whose behavior turns on RFC 9432 catalog zones."""

import re

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.urls import reverse
from nautobot.apps.testing import TestCase
from nautobot.core.testing.utils import extract_page_body
from nautobot.users.models import ObjectPermission

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.models import (
    CATALOG_APEX_NS_SERVER,
    CatalogZoneMember,
    DNSView,
    DNSZone,
    NSRecord,
    TXTRecord,
)
from nautobot_dns_models.tests.test_catalog_zones import create_zone


@override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
class ZoneDetailViewByZoneTypeTest(TestCase):
    """Tests for the panels and buttons a zone's detail page offers, which vary by zone type."""

    RECORD_PANELS = frozenset(
        {
            "A RECORDS",
            "AAAA RECORDS",
            "CNAME RECORDS",
            "MX RECORDS",
            "NS RECORDS",
            "PTR RECORDS",
            "SRV RECORDS",
            "TXT RECORDS",
        }
    )

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")
        cls.membership = CatalogZoneMember(catalog_zone=cls.catalog_zone, member_zone=cls.member_zone)
        cls.membership.validated_save()
        cls.member_zone_record = TXTRecord(name="txt", text="a user record", zone=cls.member_zone)
        cls.member_zone_record.validated_save()

    def test_primary_zone_offers_every_record_panel(self):
        """Gating the record panels must leave an ordinary zone exactly as it was."""
        self.assertLessEqual(self.RECORD_PANELS, self._panels(self.member_zone))

    def test_catalog_zone_keeps_only_the_record_panels_it_has_records_for(self):
        """No record type is user-creatable in a catalog zone, but the records it holds are worth showing."""
        self.assertEqual(self.RECORD_PANELS & self._panels(self.catalog_zone), {"NS RECORDS", "TXT RECORDS"})

    def test_catalog_zone_shows_the_version_record(self):
        """The record the renderer will serve, rather than a restatement of the schema version."""
        self.assertIn("version", self._detail(self.catalog_zone))

    def test_catalog_zone_shows_the_apex_ns_record(self):
        """The NS RRset is part of what a renderer serves, so the page accounts for it."""
        self.assertIn(CATALOG_APEX_NS_SERVER, self._detail(self.catalog_zone))

    def test_catalog_zone_offers_no_write_controls_for_the_version_record(self):
        """Every write the selection and action columns start is one the model refuses."""
        self.assertNotIn(self._edit_url(TXTRecord.objects.get(zone=self.catalog_zone)), self._detail(self.catalog_zone))

    def test_catalog_zone_offers_no_write_controls_for_the_apex_ns_record(self):
        """The apex NS is as system-managed as the version TXT, so it is listed the same way."""
        self.assertNotIn(self._edit_url(NSRecord.objects.get(zone=self.catalog_zone)), self._detail(self.catalog_zone))

    def test_primary_zone_keeps_write_controls_for_its_records(self):
        """A system-managed TXT panel is catalog-only; an ordinary zone's TXT records stay editable."""
        self.add_permissions("nautobot_dns_models.change_txtrecord")
        self.assertIn(self._edit_url(self.member_zone_record), self._detail(self.member_zone))

    def test_catalog_zone_offers_no_add_button_for_records(self):
        """A panel supplies its own Add button, which the hidden Add Records menu would otherwise not cover."""
        self.add_permissions("nautobot_dns_models.add_txtrecord")
        self.assertNotIn(self._add_url(), self._detail(self.catalog_zone))

    def test_primary_zone_keeps_the_add_button_on_its_record_panels(self):
        """Suppressing the catalog's Add button must not reach the panels an ordinary zone shares."""
        self.add_permissions("nautobot_dns_models.add_txtrecord")
        self.assertIn(self._add_url(), self._detail(self.member_zone))

    def _add_url(self):
        """Return the add link a record panel's header carries when it offers one."""
        return reverse("plugins:nautobot_dns_models:txtrecord_add")

    def _edit_url(self, record):
        """Return the edit link a record's row carries in a table that offers write controls."""
        return reverse("plugins:nautobot_dns_models:txtrecord_edit", args=(record.pk,))

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
        self.assertIn("MEMBER ZONES", self._panels(self.catalog_zone))
        self.assertIn(self.membership.member_label, self._detail(self.catalog_zone))

    def test_primary_zone_has_no_member_zones_panel(self):
        """Only a zone that publishes members has anything to list here."""
        self.assertNotIn("MEMBER ZONES", self._panels(self.member_zone))

    def test_catalog_zone_has_no_record_statistics(self):
        """The counts are of record types a zone without user records cannot hold."""
        self.assertNotIn("RECORDS STATISTICS", self._panels(self.catalog_zone))

    def test_catalog_zone_has_no_registration_panel(self):
        """A catalog zone is not a registered name, so the registrar row does not belong here."""
        self.assertNotIn("REGISTRATION", self._panels(self.catalog_zone))

    def test_primary_zone_keeps_the_registration_panel(self):
        """Hiding registration on a catalog must not take it off an ordinary zone."""
        self.assertIn("REGISTRATION", self._panels(self.member_zone))

    def test_primary_zone_keeps_record_statistics(self):
        """Gating that panel by capability must leave it standing where the counts mean something."""
        self.assertIn("RECORDS STATISTICS", self._panels(self.member_zone))

    def test_member_zone_names_the_catalog_it_belongs_to(self):
        """The membership is reachable from the member's own page, not just the catalog's."""
        content = self._detail(self.member_zone)
        self.assertInHTML("<td>Catalog Zone</td>", content, 1)
        self.assertIn(self.catalog_zone.name, content)

    def test_catalog_zone_omits_the_catalog_field(self):
        """A zone that cannot belong to a catalog has no enrollment row to show."""
        self.assertInHTML("<td>Catalog Zone</td>", self._detail(self.catalog_zone), 0)

    def _detail(self, zone):
        """Return the rendered body of `zone`'s detail page."""
        response = self.client.get(reverse("plugins:nautobot_dns_models:dnszone", args=(zone.pk,)))
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))

    def _panels(self, zone):
        """Return the panel headings on `zone`'s detail page, upper-cased since Nautobot's own casing varies.

        Headings rather than raw page text: a hidden panel's title survives elsewhere in the markup, in
        the table configuration drawer and the navigation menu, so a substring search sees it either way.
        """
        return {label.upper() for label in re.findall(r"<strong>([^<]*)</strong>", self._detail(zone))}


@override_settings(EXEMPT_VIEW_PERMISSIONS=["*"])
class ZoneFormEnrollmentPermissionTest(TestCase):
    """Tests that the zone form's catalog field is governed by the membership's own permissions.

    The field writes `CatalogZoneMember` rows, so `change_dnszone` alone must not carry a user
    through an enrollment they could not have made from the membership's own pages.
    """

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.unenrolled_zone = create_zone("unenrolled.example")
        cls.enrolled_zone = create_zone("enrolled.example")
        CatalogZoneMember(catalog_zone=cls.catalog_zone, member_zone=cls.enrolled_zone).validated_save()

    def setUp(self):
        """Grant the zone permissions every one of these edits needs before its enrollment is judged."""
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
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        self.assertHttpStatus(self._edit(self.unenrolled_zone, self.catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.unenrolled_zone), self.catalog_zone)

    def test_moving_requires_change_permission(self):
        """Retargeting the existing row is a change to it, not a new membership."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        self._assert_refused(self._edit(self.enrolled_zone, self.other_catalog_zone), self.CHANGE_REFUSED)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_moving_is_allowed_with_change_permission(self):
        """A move keeps the membership and its label, so change permission is the whole of it."""
        self.add_permissions("nautobot_dns_models.change_catalogzonemember")
        self.assertHttpStatus(self._edit(self.enrolled_zone, self.other_catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)

    def test_withdrawing_requires_delete_permission(self):
        """Clearing the field deletes the membership and the catalog's PTR along with it."""
        self.add_permissions("nautobot_dns_models.change_catalogzonemember")
        self._assert_refused(self._edit(self.enrolled_zone), self.DELETE_REFUSED)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_withdrawing_is_allowed_with_delete_permission(self):
        """Nothing is created or retargeted, so delete permission alone must suffice."""
        self.add_permissions("nautobot_dns_models.delete_catalogzonemember")
        self.assertHttpStatus(self._edit(self.enrolled_zone), 302)
        self.assertIsNone(self._catalog_of(self.enrolled_zone))

    def test_editing_an_enrolled_zone_leaves_its_enrollment_alone(self):
        """Resubmitting the catalog a zone already has asks for nothing, so it must demand nothing."""
        self.assertHttpStatus(self._edit(self.enrolled_zone, self.catalog_zone), 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_renaming_an_enrolled_zone_needs_no_membership_permission(self):
        """Withdrawing and re-enrolling on a rename is not an enrollment the user requested.

        The zone stays in the catalog it was already in. The membership row is replaced because a
        renamed zone is a different zone to a consumer, and that replacement is derived state this
        app maintains, like the catalog's PTR records. Demanding `add_catalogzonemember` or
        `delete_catalogzonemember` would block a rename the user is entitled to make on a model
        they need not know exists.
        """
        data = self._zone_data(zone=self.enrolled_zone, catalog=self.catalog_zone)
        data["name"] = "renamed.example"

        response = self.client.post(
            reverse("plugins:nautobot_dns_models:dnszone_edit", args=(self.enrolled_zone.pk,)), data
        )

        self.assertHttpStatus(response, 302)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

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
        object_permission.object_types.add(ContentType.objects.get_for_model(CatalogZoneMember))

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
        """Post `zone`'s edit form, offering `catalog` in the field that governs its enrollment."""
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
