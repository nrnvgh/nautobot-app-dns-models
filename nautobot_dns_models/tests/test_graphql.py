"""GraphQL tests for nautobot_dns_models."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from nautobot.apps.testing import TestCase

from nautobot_dns_models.models import CatalogZone, DNSView, DNSZone


class DNSZoneGraphQLTestCase(TestCase):
    """Ensure DNSZone GraphQL excludes catalog backing zones."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_view = DNSView.objects.get(name="Default")
        cls.visible_zone = DNSZone.objects.create(
            name="graphql-visible-zone.example",
            dns_view=cls.dns_view,
            filename="graphql-visible-zone.example.zone",
            soa_mname="ns1.graphql-visible-zone.example",
            soa_rname="admin@graphql-visible-zone.example",
        )
        cls.catalog_zone = CatalogZone.create_with_backing_zone_payload(
            name="graphql-catalog-backing-zone.example",
            filename="graphql-catalog-backing-zone.example.zone",
            dns_view=cls.dns_view,
            soa_refresh=3600,
            soa_retry=600,
            soa_expire=3600000,
            soa_minimum=3600,
            description="GraphQL backing zone should be hidden from DNSZone queries.",
        )

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="graphql-phase63-admin",
            email="graphql-phase63-admin@example.com",
            password="graphql-phase63-admin",
        )
        self.client.force_login(self.user)
        self.graphql_url = reverse("graphql-api")

    def test_dns_zones_excludes_catalog_backing_zones(self):
        """The dns_zones query should return only non-backing DNS zones."""
        response = self.client.post(
            self.graphql_url,
            data={"query": "query { dns_zones { id name } }"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("errors", payload)
        returned_names = {zone["name"] for zone in payload["data"]["dns_zones"]}

        self.assertIn(self.visible_zone.name, returned_names)
        self.assertNotIn(self.catalog_zone.name, returned_names)

    def test_dns_zones_name_filter_excludes_catalog_backing_zones(self):
        """The dns_zones query should not return catalog backing zones, even when filtered by name."""
        response = self.client.post(
            self.graphql_url,
            data={"query": f'query {{ dns_zones(name: ["{self.catalog_zone.name}"]) {{ id name }} }}'},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("errors", payload)
        self.assertEqual(payload["data"]["dns_zones"], [])

    def test_dns_zones_catalog_zone_argument_is_rejected(self):
        """The dns_zones query should reject catalog_zone as an unsupported argument."""
        response = self.client.post(
            self.graphql_url,
            data={"query": f'query {{ dns_zones(catalog_zone: "{self.catalog_zone.id}") {{ id name }} }}'},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("errors", payload)
        self.assertIn("Unknown argument 'catalog_zone' on field 'Query.dns_zones'.", payload["errors"][0]["message"])

    def test_dns_zones_catalog_zone_field_is_rejected(self):
        """The dns_zones query should reject catalog_zone in the selection set."""
        response = self.client.post(
            self.graphql_url,
            data={"query": "query { dns_zones { id name catalog_zone { id } } }"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("errors", payload)
        self.assertIn(
            "Cannot query field 'catalog_zone' on type 'DNSZoneType'.",
            payload["errors"][0]["message"],
        )
