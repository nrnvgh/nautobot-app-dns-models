"""Test RFC 9432 catalog zone behavior."""

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from nautobot.apps.testing import TestCase

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CNAMERecord,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
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
