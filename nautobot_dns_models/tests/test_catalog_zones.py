"""Test RFC 9432 catalog zone behavior."""

from unittest import skipIf

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from nautobot.apps.change_logging import web_request_context
from nautobot.apps.testing import TestCase
from nautobot.extras.models import ObjectChange
from packaging import version

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.models import (
    APEX_RECORD_NAME,
    CATALOG_APEX_NS_SERVER,
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

# Change records against the two objects an M2M relates come from core's
# `get_change_logged_m2m_through_side_field_names`, which arrived in Nautobot 3.2.2. Enrollment
# works on the earlier releases this app supports, but goes unrecorded there.
M2M_SIDE_CHANGE_LOG_VERSION = version.parse("3.2.2")


def create_zone(name, **kwargs):
    """Create a zone, supplying the fields the model requires but this module does not care about."""
    return DNSZone.objects.create(
        name=name,
        filename=f"{name}.zone",
        soa_mname=f"ns1.{name}.",
        soa_rname=f"admin@{name}",
        **kwargs,
    )


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

    def test_primary_zone_supports_user_records(self):
        """A primary zone is the ordinary case: users manage its records directly."""
        self.assertTrue(self.primary_zone.supports_user_records())
        self.assertFalse(self.primary_zone.is_catalog_zone)

    def test_catalog_zone_supports_no_record_type(self):
        """A catalog zone offers no user-creatable record type, so it renders no add affordances."""
        for record_model in dns_record_models():
            with self.subTest(record_model=record_model.__name__):
                self.assertFalse(self.catalog_zone.supports_record_type(record_model))

    def test_catalog_zone_holds_only_system_managed_records(self):
        """A catalog maintains its own records and is identified as a catalog zone."""
        self.assertFalse(self.catalog_zone.supports_user_records())
        self.assertTrue(self.catalog_zone.is_catalog_zone)

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
        self.assertFalse(zone.supports_user_records())
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
        """A blank-label re-enrollment must not silently resume prior consumer state."""
        self.assertNotEqual(catalog_member_label(), catalog_member_label())


class CatalogMembershipChangeLogTest(TestCase):
    """Tests that enrollment is recorded against the zones it relates, not only the membership row."""

    @skipIf(
        version.parse(settings.VERSION) < M2M_SIDE_CHANGE_LOG_VERSION,
        f"Nautobot {M2M_SIDE_CHANGE_LOG_VERSION} records changes against both sides of an M2M; this one does not.",
    )
    def test_enrolling_records_a_change_against_both_zones(self):
        """Declaring the membership as an M2M through earns core's side-object change records."""
        catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        member_zone = create_zone("member.example")

        with web_request_context(self.user):
            CatalogZoneMember(catalog_zone=catalog_zone, member_zone=member_zone).validated_save()

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
        membership = CatalogZoneMember(catalog_zone=catalog_zone, member_zone=member_zone)
        membership.validated_save()
        old_pk = membership.pk
        old_label = membership.member_label

        with web_request_context(self.user):
            member_zone.name = "renamed.example"
            member_zone.validated_save()

        membership = CatalogZoneMember.objects.get(member_zone=member_zone)
        self.assertNotEqual(membership.pk, old_pk)
        self.assertNotEqual(membership.member_label, old_label)
        self.assertFalse(CatalogZoneMember.objects.filter(pk=old_pk).exists())
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
        """A manager add is a real enrollment, so it earns a label and a member record."""
        self.member_zone.catalogs.add(self.catalog_zone)

        membership = self.member_zone.catalog_membership.get()
        self.assertEqual(len(membership.member_label), 26)
        self.assertTrue(
            PTRRecord.objects.filter(zone=self.catalog_zone, name=f"{membership.member_label}.zones").exists()
        )

    def test_adding_from_the_catalog_end_enrolls_the_zone_too(self):
        """The reverse accessor writes the same row, so it is held to the same rules."""
        self.catalog_zone.members.add(self.member_zone)

        self.assertEqual(self.member_zone.catalog_membership.get().catalog_zone, self.catalog_zone)

    def test_adding_several_zones_gives_each_its_own_label(self):
        """Bulk-created rows never reach save(), so the label has to come from the field default."""
        second_zone = create_zone("second.example")

        self.catalog_zone.members.add(self.member_zone, second_zone)

        labels = set(CatalogZoneMember.objects.values_list("member_label", flat=True))
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


class CatalogZoneMemberTest(TestCase):
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
        membership = CatalogZoneMember.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone)
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

        membership = CatalogZoneMember.objects.get(member_zone=self.member_zone)
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

        first = CatalogZoneMember.objects.get(member_zone=self.member_zone)
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
        membership = CatalogZoneMember(**fields)
        membership.validated_save()
        return membership
