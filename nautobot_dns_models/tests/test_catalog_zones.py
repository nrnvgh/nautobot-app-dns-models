"""Test RFC 9432 catalog zone behavior."""

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from nautobot.apps.testing import TestCase

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CatalogZoneMember,
    CNAMERecord,
    DNSView,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
    catalog_member_label,
    dns_record_models,
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


class CatalogZoneRecordGatingTest(TestCase):
    """Tests for the record types a zone accepts and for the immutability of system-managed records."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.primary_zone = create_zone("primary.example")

    def test_primary_zone_supports_every_record_type(self):
        """Every record type this app models remains user-creatable in a primary zone."""
        for record_model in dns_record_models():
            with self.subTest(record_model=record_model.__name__):
                self.assertTrue(self.primary_zone.supports_record_type(record_model))

    def test_catalog_zone_supports_no_record_type(self):
        """A catalog zone offers no user-creatable record type, so it renders no add affordances."""
        for record_model in dns_record_models():
            with self.subTest(record_model=record_model.__name__):
                self.assertFalse(self.catalog_zone.supports_record_type(record_model))

    def test_record_fixtures_cover_every_record_model(self):
        """The hand-built fixtures below must keep pace with the record models discovered at runtime."""
        self.assertEqual(
            {type(record) for record in self._unsaved_records(self.catalog_zone)},
            set(dns_record_models()),
        )

    def test_unknown_zone_type_supports_no_record_type(self):
        """A zone type missing from the registry denies everything rather than defaulting to open."""
        zone = DNSZone(name="future.example", zone_type="future")
        self.assertFalse(zone.supports_record_type(ARecord))

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
    """Tests for the BIND-compatible member label generator."""

    def test_matches_the_labels_bind_documents(self):
        """The two worked examples ISC publishes for catzhash.py, which pin the algorithm exactly."""
        self.assertEqual(catalog_member_label("domain.example"), "5960775ba382e7a4e09263fc06e7c00569b6a05c")
        self.assertEqual(catalog_member_label("example.com"), "c5e4b4da1e5a620ddaa3635e55c3732a5b49c7f4")

    def test_ignores_case_and_a_trailing_dot(self):
        """A zone name differing only in case or absolute form is the same name, so it hashes the same."""
        expected = catalog_member_label("example.com")
        self.assertEqual(catalog_member_label("Example.COM"), expected)
        self.assertEqual(catalog_member_label("example.com."), expected)

    def test_fits_within_a_dns_label(self):
        """A SHA-1 hex digest is 40 characters, comfortably inside the 63-byte limit of RFC 1035 §3.1."""
        self.assertEqual(len(catalog_member_label("example.com")), 40)


class CatalogZoneMemberTest(TestCase):
    """Tests for the membership model that enrolls a zone in a catalog zone."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")

    def test_label_is_generated_from_the_member_zone_name(self):
        """Leaving the label blank adopts the BIND convention rather than demanding operator input."""
        membership = self._membership()
        self.assertEqual(membership.member_label, catalog_member_label("member.example"))

    def test_label_is_generated_without_validation(self):
        """An ORM caller that skips full_clean() still gets a label, since save() cannot store a blank one."""
        membership = CatalogZoneMember.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone)
        self.assertEqual(membership.member_label, catalog_member_label("member.example"))

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
        """Enrollment is a property of the member zone, so it should not outlive it."""
        membership = self._membership()
        self.member_zone.delete()
        self.assertFalse(CatalogZoneMember.objects.filter(pk=membership.pk).exists())

    def test_catalog_zone_cannot_be_deleted_while_it_has_members(self):
        """Losing a catalog silently unprovisions every member zone, so the operator has to unenroll first."""
        self._membership()
        with self.assertRaises(ProtectedError):
            self.catalog_zone.delete()
        self.assertTrue(DNSZone.objects.filter(pk=self.catalog_zone.pk).exists())

    def _membership(self, **overrides):
        """Create and return a validated membership, defaulting to the fixture zones."""
        fields = {"catalog_zone": self.catalog_zone, "member_zone": self.member_zone}
        fields.update(overrides)
        membership = CatalogZoneMember(**fields)
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

    def test_retargeting_a_membership_moves_the_ptr(self):
        """The label is the member's identity, so a new target updates the existing owner name."""
        membership = self._membership()
        second_zone = create_zone("second.example")
        membership.member_zone = second_zone
        membership.validated_save()

        record = PTRRecord.objects.get(zone=self.catalog_zone)
        self.assertEqual(record.name, f"{membership.member_label}.zones")
        self.assertEqual(record.ptrdname, "second.example")

    def test_moving_a_membership_between_catalogs_moves_the_ptr(self):
        """The catalog it left must stop advertising a member it no longer has."""
        membership = self._membership()
        other_catalog = create_zone("other-catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        membership.catalog_zone = other_catalog
        membership.validated_save()

        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())
        self.assertEqual(PTRRecord.objects.get(zone=other_catalog).ptrdname, "member.example")

    def test_deleting_a_membership_withdraws_the_ptr(self):
        """Unenrolling a zone has to stop a consumer from provisioning it."""
        membership = self._membership()
        membership.delete()
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_zone).exists())

    def test_bulk_deleting_memberships_withdraws_the_ptr(self):
        """Bulk delete routes through QuerySet.delete(), which sends post_delete per instance."""
        self._membership()
        CatalogZoneMember.objects.all().delete()
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

        self.assertEqual(
            PTRRecord.objects.get(zone=self.catalog_zone).name, f"{membership.member_label}.zones"
        )

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
        membership = CatalogZoneMember(**fields)
        membership.validated_save()
        return membership
