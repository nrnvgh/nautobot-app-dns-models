"""Signal tests for catalog zone membership behavior."""

from nautobot.apps.testing import TestCase

from nautobot_dns_models.models import CatalogZone, CatalogZoneMembership, DNSZone, PTRRecord


class CatalogZoneMembershipSignalsTestCase(TestCase):
    """Test m2m signal handling for CatalogZone membership assignment."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_dns_zone = DNSZone.objects.create(name="catalog-signal.example.com")
        cls.catalog_zone = CatalogZone.objects.create(dns_zone=cls.catalog_dns_zone)
        cls.member_zone_1 = DNSZone.objects.create(name="member-signal-1.example.com")
        cls.member_zone_2 = DNSZone.objects.create(name="member-signal-2.example.com")

    def test_members_m2m_add_assigns_member_node_label(self):
        """Verify m2m add() path assigns generated member node labels."""
        self.catalog_zone.members.add(self.member_zone_1)
        membership = CatalogZoneMembership.objects.get(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        self.assertTrue(membership.member_node_label)
        self.assertEqual(len(membership.member_node_label), 26)
        self.assertTrue(
            PTRRecord.objects.filter(
                zone=self.catalog_dns_zone,
                name=f"{membership.member_node_label}.zones",
                ptrdname=self.member_zone_1.name,
            ).exists()
        )

    def test_members_m2m_add_multiple_assigns_member_node_labels(self):
        """Verify one add() call can add two members with generated labels."""
        self.catalog_zone.members.add(self.member_zone_1, self.member_zone_2)

        memberships = CatalogZoneMembership.objects.filter(
            catalog_zone=self.catalog_zone,
            member_zone__in=[self.member_zone_1, self.member_zone_2],
        )

        self.assertEqual(memberships.count(), 2)
        labels = list(memberships.values_list("member_node_label", flat=True))
        self.assertEqual(len([label for label in labels if label]), 2)
        self.assertEqual(len([label for label in labels if len(label) == 26]), 2)
        self.assertEqual(len(set(labels)), 2)

    def test_members_m2m_set_from_empty_creates_member_ptr_records(self):
        """Verify m2m set() from empty creates memberships and PTR records."""
        self.catalog_zone.members.set([self.member_zone_1, self.member_zone_2])
        memberships = CatalogZoneMembership.objects.filter(
            catalog_zone=self.catalog_zone,
            member_zone__in=[self.member_zone_1, self.member_zone_2],
        )
        self.assertEqual(memberships.count(), 2)
        for membership in memberships:
            self.assertTrue(
                PTRRecord.objects.filter(
                    zone=self.catalog_dns_zone,
                    name=f"{membership.member_node_label}.zones",
                    ptrdname=membership.member_zone.name,
                ).exists()
            )

    def test_members_m2m_set_clear_true_creates_new_member_ptr_record(self):
        """Verify m2m set(clear=True) creates PTR records for newly-associated members."""
        self.catalog_zone.members.add(self.member_zone_1)
        self.catalog_zone.members.set([self.member_zone_2], clear=True)

        membership = CatalogZoneMembership.objects.get(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_2,
        )
        self.assertTrue(
            PTRRecord.objects.filter(
                zone=self.catalog_dns_zone,
                name=f"{membership.member_node_label}.zones",
                ptrdname=self.member_zone_2.name,
            ).exists()
        )

    def test_reverse_m2m_add_creates_member_ptr_record(self):
        """Verify reverse m2m add() creates membership and PTR record."""
        self.member_zone_1.member_of_catalog_zones.add(self.catalog_zone)
        membership = CatalogZoneMembership.objects.get(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        self.assertTrue(
            PTRRecord.objects.filter(
                zone=self.catalog_dns_zone,
                name=f"{membership.member_node_label}.zones",
                ptrdname=self.member_zone_1.name,
            ).exists()
        )

    def test_reverse_m2m_set_creates_member_ptr_records(self):
        """Verify reverse m2m set() creates memberships and PTR records."""
        second_catalog_dns_zone = DNSZone.objects.create(name="catalog-signal-3.example.com")
        second_catalog_zone = CatalogZone.objects.create(dns_zone=second_catalog_dns_zone)

        self.member_zone_1.member_of_catalog_zones.set([self.catalog_zone, second_catalog_zone])
        memberships = CatalogZoneMembership.objects.filter(
            member_zone=self.member_zone_1,
            catalog_zone__in=[self.catalog_zone, second_catalog_zone],
        )
        self.assertEqual(memberships.count(), 2)
        for membership in memberships:
            self.assertTrue(
                PTRRecord.objects.filter(
                    zone=membership.catalog_zone.dns_zone,
                    name=f"{membership.member_node_label}.zones",
                    ptrdname=self.member_zone_1.name,
                ).exists()
            )

    def test_members_m2m_remove_deletes_member_ptr_record(self):
        """Verify m2m remove() also removes derived member PTR record."""
        self.catalog_zone.members.add(self.member_zone_1)
        membership = CatalogZoneMembership.objects.get(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        ptr_name = f"{membership.member_node_label}.zones"

        self.assertTrue(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=ptr_name).exists())
        self.catalog_zone.members.remove(self.member_zone_1)
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=ptr_name).exists())

    def test_members_m2m_clear_deletes_member_ptr_records(self):
        """Verify m2m clear() removes all derived member PTR records."""
        self.catalog_zone.members.add(self.member_zone_1, self.member_zone_2)
        memberships = CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone)
        ptr_names = [f"{label}.zones" for label in memberships.values_list("member_node_label", flat=True)]

        self.catalog_zone.members.clear()
        self.assertEqual(CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone).count(), 0)
        self.assertEqual(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name__in=ptr_names).count(), 0)

    def test_members_m2m_set_replaces_and_deletes_removed_member_ptr_record(self):
        """Verify m2m set() removes stale member PTR records."""
        self.catalog_zone.members.add(self.member_zone_1, self.member_zone_2)
        removed_membership = CatalogZoneMembership.objects.get(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        removed_ptr_name = f"{removed_membership.member_node_label}.zones"

        self.catalog_zone.members.set([self.member_zone_2])
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=removed_ptr_name).exists())
        self.assertTrue(
            CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone, member_zone=self.member_zone_2).exists()
        )

    def test_members_m2m_set_clear_true_deletes_all_member_ptr_records(self):
        """Verify m2m set(clear=True) removes all derived member PTR records."""
        self.catalog_zone.members.add(self.member_zone_1, self.member_zone_2)
        memberships = CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone)
        ptr_names = [f"{label}.zones" for label in memberships.values_list("member_node_label", flat=True)]

        self.catalog_zone.members.set([], clear=True)
        self.assertEqual(CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone).count(), 0)
        self.assertEqual(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name__in=ptr_names).count(), 0)

    def test_reverse_m2m_remove_deletes_member_ptr_record(self):
        """Verify reverse m2m remove() removes derived member PTR record."""
        self.catalog_zone.members.add(self.member_zone_1)
        membership = CatalogZoneMembership.objects.get(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        ptr_name = f"{membership.member_node_label}.zones"

        self.member_zone_1.member_of_catalog_zones.remove(self.catalog_zone)
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=ptr_name).exists())

    def test_reverse_m2m_clear_deletes_member_ptr_records(self):
        """Verify reverse m2m clear() removes all related PTR records for that member."""
        second_catalog_dns_zone = DNSZone.objects.create(name="catalog-signal-2.example.com")
        second_catalog_zone = CatalogZone.objects.create(dns_zone=second_catalog_dns_zone)
        self.catalog_zone.members.add(self.member_zone_1)
        second_catalog_zone.members.add(self.member_zone_1)

        memberships = CatalogZoneMembership.objects.filter(member_zone=self.member_zone_1)
        expected_ptrs = {
            (membership.catalog_zone.dns_zone_id, f"{membership.member_node_label}.zones")
            for membership in memberships
        }

        self.member_zone_1.member_of_catalog_zones.clear()

        self.assertEqual(CatalogZoneMembership.objects.filter(member_zone=self.member_zone_1).count(), 0)
        for zone_id, ptr_name in expected_ptrs:
            self.assertFalse(PTRRecord.objects.filter(zone_id=zone_id, name=ptr_name).exists())
