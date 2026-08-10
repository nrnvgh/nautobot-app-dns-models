"""Test bulk operations on zones where a catalog zone changes what they may do."""

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from nautobot.apps.testing import TestCase
from nautobot.core.testing.utils import extract_page_body
from nautobot.users.models import ObjectPermission

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.forms import DNSZoneBulkAssignCatalogForm, DNSZoneWithCatalogBulkEditForm
from nautobot_dns_models.models import CatalogZoneMember, DNSView, DNSZone
from nautobot_dns_models.tests.test_catalog_zones import create_zone


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


class ZoneBulkAssignCatalogTest(TestCase):
    """Tests for enrolling a selection of zones in one catalog from the zone list.

    The action exists because enrollment writes `CatalogZoneMember` rows, which carry permissions of
    their own that the bulk edit job has no user to check and no transaction to undo.
    """

    ENROLL_WITHHELD = 'name="_apply" class="btn btn-primary" disabled'
    NESTING_REFUSED = "A catalog zone cannot belong to another catalog zone"
    PERMISSION_REFUSED = "Enrollment failed due to object-level permissions violation."
    VIEW_REFUSED = "Not in this catalog zone"

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("assign-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.other_catalog_zone = create_zone("assign-other.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.unenrolled_zones = [create_zone(f"assign-free-{index}.example") for index in range(2)]
        cls.enrolled_zone = create_zone("assign-enrolled.example")
        CatalogZoneMember(catalog_zone=cls.other_catalog_zone, member_zone=cls.enrolled_zone).validated_save()

        cls.assign_path = reverse("plugins:nautobot_dns_models:dnszone_bulk_assign_catalog")
        cls.list_path = reverse("plugins:nautobot_dns_models:dnszone_list")

    def setUp(self):
        """Grant what reaching the action needs, leaving each test to add the enrollment it exercises."""
        super().setUp()
        self.add_permissions("nautobot_dns_models.view_dnszone", "nautobot_dns_models.change_dnszone")

    def test_the_list_offers_the_action_to_a_user_who_may_enroll(self):
        """The button is offered on the membership's permission, not the zone's."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        self.assertIn(self.assign_path, self._zone_list())

    def test_the_list_withholds_the_action_without_permission_to_enroll(self):
        """`change_dnszone` alone does not authorize enrollment, so it does not offer it either."""
        self.assertNotIn(self.assign_path, self._zone_list())

    def test_the_selection_is_confirmed_before_anything_is_written(self):
        """The first pass names the zones back to the user and leaves them as they were."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")

        body = self._post(pk_list=[zone.pk for zone in self.unenrolled_zones])

        for zone in self.unenrolled_zones:
            self.assertIn(zone.name, body)
        self.assertNotIn(self.ENROLL_WITHHELD, body)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_applying_enrolls_the_selected_zones(self):
        """The zones that had no catalog are added to the one chosen."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")

        self._apply(self.unenrolled_zones, self.catalog_zone, expect=302)

        for zone in self.unenrolled_zones:
            self.assertEqual(self._catalog_of(zone), self.catalog_zone)

    def test_applying_moves_a_zone_already_enrolled_elsewhere(self):
        """Moving is a change to an existing membership, so it takes that permission too."""
        self.add_permissions(
            "nautobot_dns_models.add_catalogzonemember", "nautobot_dns_models.change_catalogzonemember"
        )

        self._apply([self.enrolled_zone], self.catalog_zone, expect=302)

        self.assertEqual(self._catalog_of(self.enrolled_zone), self.catalog_zone)

    def test_a_move_without_change_permission_takes_the_whole_batch_back(self):
        """One refusal rolls the transaction back, so the zones it would have enrolled stay free."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")

        body = self._apply(self.unenrolled_zones + [self.enrolled_zone], self.catalog_zone, expect=200)

        self.assertIn(self.PERMISSION_REFUSED, body)
        self.assertEqual(self._catalog_of(self.enrolled_zone), self.other_catalog_zone)
        for zone in self.unenrolled_zones:
            self.assertIsNone(self._catalog_of(zone))

    def test_a_catalog_zone_in_the_selection_is_refused_by_name(self):
        """Nesting is unsupported, and the report names the zone so the selection can be corrected."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        selection = [self.unenrolled_zones[0], self.other_catalog_zone]

        # The confirmation table lists every selected zone, so the name alone would prove nothing.
        refusal = f"{self.NESTING_REFUSED}, and the selection holds <strong>{self.other_catalog_zone.name}</strong>."
        self.assertIn(refusal, self._post(pk_list=[zone.pk for zone in selection]))
        self.assertIn(refusal, self._apply(selection, self.catalog_zone, expect=200))
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_a_long_list_of_offenders_is_capped_at_a_readable_length(self):
        """Past five names the report counts the rest, and the names it does give stay marked up."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        catalogs = [
            create_zone(f"assign-many-{index}.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG) for index in range(7)
        ]

        body = self._post(pk_list=[zone.pk for zone in catalogs])

        self.assertIn("<strong>assign-many-0.example</strong>", body)
        self.assertIn(", and 2 more.", body)

    def test_a_refused_selection_is_offered_no_catalog_to_choose(self):
        """The judgement lands before a catalog is asked for, so neither control invites the attempt."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        selection = [self.unenrolled_zones[0], self.other_catalog_zone]

        self.assertIn(self.ENROLL_WITHHELD, self._post(pk_list=[zone.pk for zone in selection]))

        form = DNSZoneBulkAssignCatalogForm(DNSZone.objects.filter(pk__in=[zone.pk for zone in selection]))
        self.assertTrue(form.fields["catalog"].disabled)

    def test_both_faults_in_one_selection_are_reported_together(self):
        """Correcting one fault must not uncover the other on the next attempt."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        stranger = create_zone("assign-elsewhere.example", dns_view=DNSView.objects.create(name="Assign Span View"))

        body = self._post(pk_list=[zone.pk for zone in (self.unenrolled_zones[0], self.other_catalog_zone, stranger)])

        self.assertIn(self.NESTING_REFUSED, body)
        self.assertIn(DNSZoneBulkAssignCatalogForm.SPANS_VIEWS, body)

    def test_the_picker_offers_only_catalogs_in_the_view_the_selection_shares(self):
        """A catalog holds zones from its own view alone, so the rest are never put on offer."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")

        body = self._post(pk_list=[zone.pk for zone in self.unenrolled_zones])

        view_id = self.unenrolled_zones[0].dns_view_id
        self.assertIn(f'data-query-param-dns_view="[&quot;{view_id}&quot;]"', body)

    def test_a_selection_spanning_views_cannot_be_enrolled_at_all(self):
        """No one catalog could hold them, so the page says so rather than offering a choice that fails."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        selection = [
            self.unenrolled_zones[0],
            create_zone("assign-elsewhere.example", dns_view=DNSView.objects.create(name="Assign Span View")),
        ]

        self.assertIn(DNSZoneBulkAssignCatalogForm.SPANS_VIEWS, self._post(pk_list=[zone.pk for zone in selection]))
        self.assertIn(DNSZoneBulkAssignCatalogForm.SPANS_VIEWS, self._apply(selection, self.catalog_zone, expect=200))
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_a_catalog_in_another_view_is_refused(self):
        """A catalog can only hold zones from its own view, which the model would reject one at a time."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        stranger = create_zone(
            "assign-stranger.example",
            zone_type=DNSZoneTypeChoices.TYPE_CATALOG,
            dns_view=DNSView.objects.create(name="Assign Test View"),
        )

        body = self._apply(self.unenrolled_zones, stranger, expect=200)

        self.assertIn(self.VIEW_REFUSED, body)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[0]))

    def test_select_all_follows_the_filter_it_was_made_under(self):
        """ "Select all" is resolved from the filter, not from the rows the browser happened to hold."""
        self.add_permissions("nautobot_dns_models.add_catalogzonemember")
        query = f"?name={self.unenrolled_zones[0].name}"

        response = self.client.post(
            f"{self.assign_path}{query}",
            {"_all": "on", "_apply": "", "catalog": str(self.catalog_zone.pk)},
        )
        self.assertHttpStatus(response, 302)

        self.assertEqual(self._catalog_of(self.unenrolled_zones[0]), self.catalog_zone)
        self.assertIsNone(self._catalog_of(self.unenrolled_zones[1]))

    def test_a_constraint_on_the_membership_is_enforced(self):
        """An enrollment permission narrowed to one catalog must not reach another."""
        object_permission = ObjectPermission(
            name="Bulk enroll in one catalog only",
            actions=["add"],
            constraints={"catalog_zone__name": self.catalog_zone.name},
        )
        object_permission.save()
        object_permission.users.add(self.user)
        object_permission.object_types.add(ContentType.objects.get_for_model(CatalogZoneMember))

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
        response = self.client.post(self.assign_path, {"pk": [str(pk) for pk in pk_list], **(data or {})})
        self.assertHttpStatus(response, expect)
        if expect != 200:
            return ""

        return extract_page_body(response.content.decode(response.charset))

    def _zone_list(self):
        """Return the zone list page, where the bulk action buttons are rendered."""
        response = self.client.get(self.list_path)
        self.assertHttpStatus(response, 200)
        return extract_page_body(response.content.decode(response.charset))
