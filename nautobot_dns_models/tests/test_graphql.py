"""Test the GraphQL schema this app contributes."""

from graphene_django.settings import graphene_settings
from graphql import parse, validate
from nautobot.apps.graphql import execute_query
from nautobot.apps.testing import TestCase

from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.models import CatalogZoneMembership, DNSZone


def create_zone(name, **kwargs):
    """Create a zone, supplying the fields the model requires but this module does not care about."""
    return DNSZone.objects.create(
        name=name,
        filename=f"{name}.zone",
        soa_mname=f"ns1.{name}.",
        soa_rname=f"admin@{name}",
        **kwargs,
    )


class GraphQLQueryMixin:
    """Runs a query as the test user, holding the schema to what the query asks of it."""

    def run_query(self, query, **variables):
        """Return the data `query` selects, failing if the schema does not accept it or execution errors.

        Validated separately because `execute_query` parses without validating, so a field the schema does
        not define would otherwise be dropped from the response rather than reported.
        """
        schema_errors = validate(graphene_settings.SCHEMA.graphql_schema, parse(query))
        self.assertEqual(schema_errors, [])

        result = execute_query(query, variables=variables or None, user=self.user)
        self.assertIsNone(result.errors)
        return result.data


class DNSZoneTestCase(GraphQLQueryMixin, TestCase):
    """Tests the catalog a zone belongs to as read over GraphQL.

    `DNSZone.catalog` is a property rather than a field, so the auto-generated type does not expose it and
    the REST API's `catalog` has no GraphQL counterpart.
    """

    ZONES_QUERY = """
        query ($name: [String]) {
            dns_zones(name: $name) {
                name
                catalog {
                    name
                }
            }
        }
    """

    MEMBERS_QUERY = """
        query ($name: [String]) {
            dns_zones(name: $name) {
                members {
                    name
                }
            }
        }
    """

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")
        cls.other_member_zone = create_zone("other-member.example")
        cls.solo_zone = create_zone("solo.example")
        CatalogZoneMembership.objects.create(catalog_zone=cls.catalog_zone, member_zone=cls.member_zone)
        CatalogZoneMembership.objects.create(catalog_zone=cls.catalog_zone, member_zone=cls.other_member_zone)

    def test_catalog_names_the_catalog_a_zone_belongs_to(self):
        self.add_permissions("nautobot_dns_models.view_dnszone")

        zones = self.run_query(self.ZONES_QUERY, name=["member.example"])["dns_zones"]

        self.assertEqual(zones[0]["catalog"]["name"], "catalog.example")

    def test_catalog_is_null_for_a_zone_in_no_catalog(self):
        self.add_permissions("nautobot_dns_models.view_dnszone")

        zones = self.run_query(self.ZONES_QUERY, name=["solo.example"])["dns_zones"]

        self.assertIsNone(zones[0]["catalog"])

    def test_catalog_is_null_for_a_catalog_zone(self):
        """A catalog zone cannot belong to another, so it reports no catalog rather than itself."""
        self.add_permissions("nautobot_dns_models.view_dnszone")

        zones = self.run_query(self.ZONES_QUERY, name=["catalog.example"])["dns_zones"]

        self.assertIsNone(zones[0]["catalog"])

    def test_catalog_is_reported_when_the_catalog_zone_can_be_viewed(self):
        """A constrained user reads the catalog zones the constraint covers, rather than none at all."""
        self.add_permissions(
            "nautobot_dns_models.view_dnszone",
            constraints={"name__in": ["member.example", "catalog.example"]},
        )

        zones = self.run_query(self.ZONES_QUERY, name=["member.example"])["dns_zones"]

        self.assertEqual(zones[0]["catalog"]["name"], "catalog.example")

    def test_catalog_is_null_when_the_catalog_zone_cannot_be_viewed(self):
        """A property-backed related object must honor object permissions, per GHSA-mfwj-pjgx-22v2."""
        self.add_permissions("nautobot_dns_models.view_dnszone", constraints={"name": "member.example"})

        zones = self.run_query(self.ZONES_QUERY, name=["member.example"])["dns_zones"]

        self.assertEqual(zones[0]["name"], "member.example")
        self.assertIsNone(zones[0]["catalog"])

    def test_members_omits_a_zone_that_cannot_be_viewed(self):
        """`members` is core's, but the app defining its own type is what keeps core's enforcing resolver."""
        self.add_permissions(
            "nautobot_dns_models.view_dnszone",
            constraints={"name__in": ["catalog.example", "member.example"]},
        )

        zones = self.run_query(self.MEMBERS_QUERY, name=["catalog.example"])["dns_zones"]

        self.assertEqual(zones[0]["members"], [{"name": "member.example"}])


class CatalogZoneMembershipTestCase(GraphQLQueryMixin, TestCase):
    """Tests the membership itself over GraphQL, for which core generates a type from `extras_features`."""

    MEMBERSHIPS_QUERY = """
        query {
            catalog_zone_memberships {
                member_label
                catalog_zone {
                    name
                }
                member_zone {
                    name
                }
            }
        }
    """

    @classmethod
    def setUpTestData(cls):
        cls.catalog_zone = create_zone("catalog.example", zone_type=DNSZoneTypeChoices.TYPE_CATALOG)
        cls.member_zone = create_zone("member.example")
        cls.membership = CatalogZoneMembership.objects.create(
            catalog_zone=cls.catalog_zone, member_zone=cls.member_zone
        )

    def test_memberships_are_hidden_without_the_membership_permission(self):
        self.add_permissions("nautobot_dns_models.view_dnszone")

        memberships = self.run_query(self.MEMBERSHIPS_QUERY)["catalog_zone_memberships"]

        self.assertEqual(memberships, [])

    def test_memberships_report_both_zones_and_the_member_label(self):
        self.add_permissions(
            "nautobot_dns_models.view_catalogzonemembership",
            "nautobot_dns_models.view_dnszone",
        )

        memberships = self.run_query(self.MEMBERSHIPS_QUERY)["catalog_zone_memberships"]

        self.assertEqual(
            memberships,
            [
                {
                    "member_label": self.membership.member_label,
                    "catalog_zone": {"name": "catalog.example"},
                    "member_zone": {"name": "member.example"},
                }
            ],
        )
