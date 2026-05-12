"""Signal tests for catalog zone membership behavior."""

from nautobot.apps.testing import TestCase

from nautobot_dns_models.models import CatalogZone, CatalogZoneMembership, DNSZone


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
