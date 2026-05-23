"""Model tests for nautobot_dns_models."""

from unittest.mock import patch

from constance.test import override_config
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from nautobot.apps.testing import ModelTestCases, TestCase
from nautobot.extras.models import Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_dns_models.models import (
    CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_NODE_LABEL_UNIQUE,
    CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_ZONE_UNIQUE,
    CATALOG_ZONE_DEFAULT_NS_TARGET,
    AAAARecord,
    ARecord,
    CatalogMemberNodeLabelGenerationError,
    CatalogZone,
    CatalogZoneMembership,
    CatalogZoneMembershipAlreadyExistsError,
    CNAMERecord,
    DNSRegistrar,
    DNSView,
    DNSViewPrefixAssignment,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
    dns_wire_label_length,
)


# Helper for generating unicode labels of a specific IDNA-encoded length
def _make_unicode_label_with_idna_length(char, target_length):
    """Return a string of repeated `char` whose IDNA-encoded length is exactly `target_length` bytes."""
    label = ""
    while dns_wire_label_length(label) < target_length:
        label += char
    if dns_wire_label_length(label) > target_length:
        label = label[:-1]
    if dns_wire_label_length(label) != target_length:
        raise ValueError(f"Could not generate label of exactly {target_length} bytes in IDNA.")
    return label


class TestDNSView(ModelTestCases.BaseModelTestCase):
    """Test DNSView model."""

    model = DNSView

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSView Model."""
        super().setUpTestData()
        # Create 3 objects for the model test cases.
        DNSView.objects.create(name="View 1", description="First DNS View")
        DNSView.objects.create(name="View 2", description="Second DNS View")
        DNSView.objects.create(name="View 3", description="Third DNS View")

    def test_create_dnsview_only_required(self):
        """Create with only required fields, and validate null description and __str__."""
        dnsview = DNSView.objects.create(name="Test View")
        self.assertEqual(dnsview.name, "Test View")
        self.assertEqual(dnsview.description, "")
        self.assertEqual(str(dnsview), "Test View")

    def test_create_dnsview_all_fields_success(self):
        """Create DNSViewModel with all fields."""
        dnsview = DNSView.objects.create(name="Test View", description="Test Description")
        self.assertEqual(dnsview.name, "Test View")
        self.assertEqual(dnsview.description, "Test Description")

    def test_get_absolute_url(self):
        dns_view_model = DNSView.objects.get(name="View 1")
        self.assertEqual(dns_view_model.get_absolute_url(), f"/plugins/dns/dns-views/{dns_view_model.id}/")


class TestDNSViewPrefixAssignment(ModelTestCases.BaseModelTestCase):
    """Test DNSViewPrefixAssignment model."""

    model = DNSViewPrefixAssignment

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSViewPrefixAssignment Model."""
        super().setUpTestData()
        # Create Prefixes
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        cls.prefixes = (
            Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, status=status),
            Prefix.objects.create(prefix="2001:db8:abcd:99::/64", namespace=namespace, status=status),
        )
        # Create DNS Views
        cls.dns_views = (
            DNSView.objects.create(name="View 1", description="First DNS View"),
            DNSView.objects.create(name="View 2", description="Second DNS View"),
        )

        # Create DNSViewPrefixAssignment
        DNSViewPrefixAssignment.objects.create(dns_view=cls.dns_views[0], prefix=cls.prefixes[0])

    def test_create_dnsviewprefixassignment(self):
        """Create DNSViewPrefixAssignment with all fields."""
        assignment = DNSViewPrefixAssignment.objects.create(dns_view=self.dns_views[1], prefix=self.prefixes[1])
        self.assertEqual(assignment.dns_view, self.dns_views[1])
        self.assertEqual(assignment.prefix, self.prefixes[1])


class TestDNSRegistrar(ModelTestCases.BaseModelTestCase):
    """Test DNSRegistrar model."""

    model = DNSRegistrar

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSRegistrar Model."""
        super().setUpTestData()
        DNSRegistrar.objects.create(name="Registrar 1", url="https://registrar1.example", account_number="ACC-001")
        DNSRegistrar.objects.create(name="Registrar 2", url="https://registrar2.example", account_number="ACC-002")
        DNSRegistrar.objects.create(name="Registrar 3", url="https://registrar3.example", account_number="ACC-003")

    def test_create_dnsregistrar_only_required(self):
        """Create with only required fields."""
        registrar = DNSRegistrar.objects.create(name="Test Registrar")
        self.assertEqual(registrar.name, "Test Registrar")
        self.assertEqual(registrar.url, "")
        self.assertEqual(registrar.account_number, "")
        self.assertEqual(str(registrar), "Test Registrar")

    def test_create_dnsregistrar_all_fields_success(self):
        """Create DNSRegistrar with all fields."""
        registrar = DNSRegistrar.objects.create(
            name="Another Registrar",
            url="https://another-registrar.example",
            account_number="ACCT-1234",
        )
        self.assertEqual(registrar.name, "Another Registrar")
        self.assertEqual(registrar.url, "https://another-registrar.example")
        self.assertEqual(registrar.account_number, "ACCT-1234")

    def test_get_absolute_url(self):
        registrar = DNSRegistrar.objects.get(name="Registrar 1")
        self.assertEqual(registrar.get_absolute_url(), f"/plugins/dns/dns-registrars/{registrar.id}/")


class TestDnsZone(ModelTestCases.BaseModelTestCase):
    """Test DnsZone model."""

    model = DNSZone

    @classmethod
    def setUpTestData(cls):
        """Create test data for DNSZone Model."""
        super().setUpTestData()
        # Create 3 objects for the model test cases.
        DNSZone.objects.create(name="Test One")
        DNSZone.objects.create(name="Test Two")
        DNSZone.objects.create(name="Test Three")

    def test_create_dnszone_only_required(self):
        """Create with only required fields, and validate null description and __str__."""
        dnszone = DNSZone.objects.create(name="Development")
        self.assertEqual(dnszone.name, "Development")
        self.assertEqual(dnszone.description, "")
        self.assertEqual(str(dnszone), "Development")

    def test_create_dnszone_all_fields_success(self):
        """Create DnsZoneModel with all fields."""
        dnszone = DNSZone.objects.create(
            name="Development",
            description="Development Test",
            filename="development.zone",
            soa_mname="ns1.development.example",
            soa_rname="admin@development.example",
        )
        self.assertEqual(dnszone.name, "Development")
        self.assertEqual(dnszone.description, "Development Test")
        self.assertEqual(dnszone.filename, "development.zone")

    def test_get_absolute_url(self):
        dns_zone_model = DNSZone.objects.create(name="example.com")
        self.assertEqual(dns_zone_model.get_absolute_url(), f"/plugins/dns/dns-zones/{dns_zone_model.id}/")

    def test_backing_catalog_zone_returns_wrapper_for_backing_zone(self):
        """Verify backing_catalog_zone resolves wrapper when zone backs a catalog."""
        backing_zone = DNSZone.objects.create(name="associated-backing.example.com")
        catalog_zone = CatalogZone.objects.create(dns_zone=backing_zone)

        self.assertEqual(backing_zone.backing_catalog_zone, catalog_zone)
        self.assertIsNone(backing_zone.member_catalog_zone)

    def test_member_catalog_zone_returns_membership_catalog_zone(self):
        """Verify member_catalog_zone resolves wrapper when zone is a member."""
        catalog_backing_zone = DNSZone.objects.create(name="associated-catalog.example.com")
        member_zone = DNSZone.objects.create(name="associated-member.example.com")
        catalog_zone = CatalogZone.objects.create(dns_zone=catalog_backing_zone)
        CatalogZoneMembership.objects.create(catalog_zone=catalog_zone, member_zone=member_zone)

        self.assertEqual(member_zone.member_catalog_zone, catalog_zone)
        self.assertIsNone(member_zone.backing_catalog_zone)

    def test_catalog_zone_accessors_return_none_without_association(self):
        """Verify both catalog accessors are null for standalone DNS zones."""
        standalone_zone = DNSZone.objects.create(name="associated-standalone.example.com")

        self.assertIsNone(standalone_zone.backing_catalog_zone)
        self.assertIsNone(standalone_zone.member_catalog_zone)


class CatalogZoneTestCase(TestCase):
    """Test the CatalogZone wrapper model."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(name="catalog.example.com")

    def test_catalog_zone_properties(self):
        """Verify read-only schema version and string rendering."""
        catalog_zone = CatalogZone.objects.create(dns_zone=self.zone)
        self.assertEqual(catalog_zone.schema_version, "2")
        self.assertEqual(str(catalog_zone), self.zone.name)

    def test_create_catalog_zone_creates_version_control_record(self):
        """Verify wrapper creation materializes version TXT control record."""
        catalog_zone = CatalogZone.objects.create(dns_zone=self.zone)

        version_records = TXTRecord.objects.filter(zone=self.zone, name="version")
        self.assertEqual(version_records.count(), 1)
        self.assertEqual(version_records.first().text, catalog_zone.schema_version)

    def test_save_catalog_zone_repairs_noncanonical_version_rrset(self):
        """Verify save() repairs duplicate/incorrect version TXT RRset."""
        catalog_zone = CatalogZone.objects.create(dns_zone=self.zone)
        TXTRecord.objects.create(zone=self.zone, name="version", text="legacy")
        TXTRecord.objects.create(zone=self.zone, name="version", text="unexpected")

        catalog_zone.save()
        version_records = TXTRecord.objects.filter(zone=self.zone, name="version")
        self.assertEqual(version_records.count(), 1)
        self.assertEqual(version_records.first().text, catalog_zone.schema_version)

    def test_save_catalog_zone_recreates_missing_version_record(self):
        """Verify save() recreates missing version TXT control record."""
        catalog_zone = CatalogZone.objects.create(dns_zone=self.zone)
        TXTRecord.objects.filter(zone=self.zone, name="version").delete()
        self.assertEqual(TXTRecord.objects.filter(zone=self.zone, name="version").count(), 0)

        catalog_zone.save()
        version_records = TXTRecord.objects.filter(zone=self.zone, name="version")
        self.assertEqual(version_records.count(), 1)
        self.assertEqual(version_records.first().text, catalog_zone.schema_version)

    def test_create_catalog_zone_creates_canonical_apex_ns_record(self):
        """Verify wrapper creation materializes canonical apex NS RRset."""
        CatalogZone.objects.create(dns_zone=self.zone)

        apex_ns_rrset = NSRecord.objects.filter(zone=self.zone, name="@")
        self.assertEqual(apex_ns_rrset.count(), 1)
        self.assertEqual(apex_ns_rrset.first().server, CATALOG_ZONE_DEFAULT_NS_TARGET)

    def test_save_catalog_zone_repairs_noncanonical_apex_ns_rrset(self):
        """Verify save() repairs duplicate/noncanonical apex NS RRset."""
        catalog_zone = CatalogZone.objects.create(dns_zone=self.zone)
        NSRecord.objects.create(zone=self.zone, name="@", server="ns1.example.net.")
        NSRecord.objects.create(zone=self.zone, name="@", server="ns2.example.net.")

        catalog_zone.save()

        apex_ns_rrset = NSRecord.objects.filter(zone=self.zone, name="@")
        self.assertEqual(apex_ns_rrset.count(), 1)
        self.assertEqual(apex_ns_rrset.first().server, CATALOG_ZONE_DEFAULT_NS_TARGET)

    def test_one_wrapper_per_zone(self):
        """Verify a DNSZone cannot have multiple wrappers."""
        CatalogZone.objects.create(dns_zone=self.zone)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CatalogZone.objects.create(dns_zone=self.zone)

    def test_delete_wrapper_cleans_up_backing_zone_and_control_records(self):
        """Verify wrapper deletion removes backing zone and control records."""
        zone = DNSZone.objects.create(name="delete-catalog-controls.example.com")
        catalog_zone = CatalogZone.objects.create(dns_zone=zone)
        zone_id = zone.id
        self.assertTrue(TXTRecord.objects.filter(zone_id=zone_id, name="version").exists())
        self.assertTrue(NSRecord.objects.filter(zone_id=zone_id, name="@").exists())

        catalog_zone.delete()

        self.assertFalse(DNSZone.objects.filter(id=zone_id).exists())
        self.assertFalse(TXTRecord.objects.filter(zone_id=zone_id, name="version").exists())
        self.assertFalse(NSRecord.objects.filter(zone_id=zone_id, name="@").exists())

    def test_zone_delete_is_protected_when_wrapped(self):
        """Verify backing DNSZone deletion is blocked by PROTECT."""
        catalog_zone = CatalogZone.objects.create(dns_zone=self.zone)
        with self.assertRaises(ProtectedError):
            self.zone.delete()

        self.assertTrue(CatalogZone.objects.filter(id=catalog_zone.id).exists())


class CatalogZoneMembershipTestCase(TestCase):
    """Test the CatalogZoneMembership through model."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_dns_zone = DNSZone.objects.create(name="catalog.example.com")
        cls.catalog_zone = CatalogZone.objects.create(dns_zone=cls.catalog_dns_zone)
        cls.member_zone_1 = DNSZone.objects.create(name="member-1.example.com")
        cls.member_zone_2 = DNSZone.objects.create(name="member-2.example.com")

    def test_create_membership_auto_generates_label(self):
        """Verify membership creates with an opaque generated member node label."""
        membership = CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        self.assertTrue(membership.member_node_label)
        self.assertEqual(len(membership.member_node_label), 26)
        self.assertTrue(membership.member_node_label.isalnum())

    def test_create_membership_creates_catalog_member_ptr_record(self):
        """Verify membership creation materializes matching PTR record in catalog zone."""
        membership = CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
            member_node_label="membernodeone",
        )

        ptr_record = PTRRecord.objects.get(
            zone=self.catalog_dns_zone,
            name="membernodeone.zones",
        )
        self.assertEqual(ptr_record.ptrdname, self.member_zone_1.name)
        self.assertEqual(ptr_record.zone, self.catalog_dns_zone)
        self.assertEqual(membership.member_node_label, "membernodeone")

    def test_delete_membership_removes_catalog_member_ptr_record(self):
        """Verify deleting membership removes matching PTR record from catalog zone."""
        membership = CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
            member_node_label="membernodedelete",
        )
        ptr_name = f"{membership.member_node_label}.zones"

        self.assertTrue(
            PTRRecord.objects.filter(
                zone=self.catalog_dns_zone, name=ptr_name, ptrdname=self.member_zone_1.name
            ).exists()
        )
        membership.delete()
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=ptr_name).exists())

    def test_queryset_delete_membership_removes_catalog_member_ptr_record(self):
        """Verify queryset delete path also removes derived PTR records."""
        membership = CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
            member_node_label="membernodequerysetdelete",
        )
        ptr_name = f"{membership.member_node_label}.zones"

        CatalogZoneMembership.objects.filter(pk=membership.pk).delete()
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=ptr_name).exists())

    def test_create_membership_fails_when_conflicting_ptr_target_exists(self):
        """Verify membership create fails if backing zone already has another PTR to member zone."""
        PTRRecord.objects.create(
            zone=self.catalog_dns_zone,
            name="existingmemberlabel.zones",
            ptrdname=self.member_zone_1.name,
        )

        with self.assertRaises(ValidationError):
            CatalogZoneMembership.objects.create(
                catalog_zone=self.catalog_zone,
                member_zone=self.member_zone_1,
                member_node_label="newmemberlabel",
            )

        self.assertEqual(
            CatalogZoneMembership.objects.filter(
                catalog_zone=self.catalog_zone, member_zone=self.member_zone_1
            ).count(),
            0,
        )

    def test_one_member_zone_per_catalog_zone(self):
        """Verify same member zone cannot be added twice to one catalog."""
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        with self.assertRaises(CatalogZoneMembershipAlreadyExistsError):
            with transaction.atomic():
                CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)

    def test_member_zone_can_only_belong_to_one_catalog_zone(self):
        """Verify a member zone cannot be assigned to multiple catalog zones."""
        second_catalog_dns_zone = DNSZone.objects.create(name="catalog-2.example.com")
        second_catalog_zone = CatalogZone.objects.create(dns_zone=second_catalog_dns_zone)
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)

        with self.assertRaises(CatalogZoneMembershipAlreadyExistsError):
            with transaction.atomic():
                CatalogZoneMembership.objects.create(catalog_zone=second_catalog_zone, member_zone=self.member_zone_1)

    def test_member_node_label_unique_per_catalog_zone(self):
        """Verify labels are unique within one catalog zone."""
        CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
            member_node_label="memberlabelone",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CatalogZoneMembership.objects.create(
                    catalog_zone=self.catalog_zone,
                    member_zone=self.member_zone_2,
                    member_node_label="memberlabelone",
                )

    def test_member_node_label_is_immutable(self):
        """Verify member label cannot be changed after initial creation."""
        membership = CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone, member_zone=self.member_zone_1
        )
        membership.member_node_label = "changedlabel"
        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_catalog_zone_cannot_be_its_own_member(self):
        """Verify catalog zone backing DNSZone cannot be added as member."""
        membership = CatalogZoneMembership(
            catalog_zone=self.catalog_zone,
            member_zone=self.catalog_dns_zone,
            member_node_label="selfmember",
        )
        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_catalog_zone_dns_zone_cannot_be_member_zone(self):
        """Verify a DNSZone wrapped as a catalog cannot be used as member."""
        wrapped_member_zone = DNSZone.objects.create(name="wrapped-member.example.com")
        CatalogZone.objects.create(dns_zone=wrapped_member_zone)
        membership = CatalogZoneMembership(
            catalog_zone=self.catalog_zone,
            member_zone=wrapped_member_zone,
            member_node_label="wrappedmember",
        )
        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_collision_retry_generates_new_label(self):
        """Verify generated label collisions retry and succeed."""
        CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
            member_node_label="aaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        with patch(
            "nautobot_dns_models.models.generate_catalog_member_node_label",
            side_effect=["aaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbb"],
        ):
            membership = CatalogZoneMembership.objects.create(
                catalog_zone=self.catalog_zone,
                member_zone=self.member_zone_2,
            )
        self.assertEqual(membership.member_node_label, "bbbbbbbbbbbbbbbbbbbbbbbbbb")

    def test_member_zone_constraint_raises_membership_exists_error(self):
        """Verify member-zone uniqueness constraint maps to custom exception."""
        membership = CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        with patch("nautobot_dns_models.models.PrimaryModel.save", side_effect=IntegrityError("constraint failed")):
            with patch.object(
                CatalogZoneMembership,
                "_get_integrity_error_constraint_name",
                return_value=CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_ZONE_UNIQUE,
            ):
                with self.assertRaises(CatalogZoneMembershipAlreadyExistsError):
                    membership.save()

    def test_member_zone_constraint_raises_membership_exists_error_real_db(self):
        """Verify duplicate membership save() maps DB constraint to custom exception."""
        CatalogZoneMembership.objects.create(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        duplicate_membership = CatalogZoneMembership(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        with self.assertRaises(CatalogZoneMembershipAlreadyExistsError):
            duplicate_membership.save()

    def test_label_collision_exhaustion_raises_generation_error(self):
        """Verify repeated label collisions raise custom generation exception."""
        membership = CatalogZoneMembership(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        with patch(
            "nautobot_dns_models.models.CATALOG_MEMBER_NODE_LABEL_MAX_GENERATION_ATTEMPTS",
            2,
        ):
            with patch("nautobot_dns_models.models.PrimaryModel.save", side_effect=IntegrityError("constraint failed")):
                with patch.object(
                    CatalogZoneMembership,
                    "_get_integrity_error_constraint_name",
                    return_value=CATALOG_MEMBERSHIP_CONSTRAINT_MEMBER_NODE_LABEL_UNIQUE,
                ):
                    with self.assertRaises(CatalogMemberNodeLabelGenerationError):
                        membership.save()


class CatalogZoneMembershipWorkflowTestCase(TestCase):
    """Test explicit membership workflow behavior."""

    @classmethod
    def setUpTestData(cls):
        cls.catalog_dns_zone = DNSZone.objects.create(name="catalog-m2m.example.com")
        cls.catalog_zone = CatalogZone.objects.create(dns_zone=cls.catalog_dns_zone)
        cls.member_zone_1 = DNSZone.objects.create(name="member-m2m-1.example.com")
        cls.member_zone_2 = DNSZone.objects.create(name="member-m2m-2.example.com")

    def test_create_assigns_member_node_label(self):
        """Verify create() assigns a generated member-node label."""
        membership = CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        self.assertTrue(membership.member_node_label)
        self.assertEqual(len(membership.member_node_label), 26)
        self.assertTrue(
            PTRRecord.objects.filter(
                zone=self.catalog_dns_zone,
                name=f"{membership.member_node_label}.zones",
                ptrdname=self.member_zone_1.name,
            ).exists()
        )

    def test_create_multiple_assigns_member_node_labels(self):
        """Verify multiple create() calls assign generated labels to multiple members."""
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_2)

        memberships = CatalogZoneMembership.objects.filter(
            catalog_zone=self.catalog_zone,
            member_zone__in=[self.member_zone_1, self.member_zone_2],
        )

        self.assertEqual(memberships.count(), 2)
        labels = list(memberships.values_list("member_node_label", flat=True))
        self.assertEqual(len([label for label in labels if label]), 2)
        self.assertEqual(len([label for label in labels if len(label) == 26]), 2)
        self.assertEqual(len(set(labels)), 2)

    def test_create_multiple_creates_member_ptr_records(self):
        """Verify create() path creates memberships and PTR records."""
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_2)
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

    def test_replace_membership_creates_new_member_ptr_record(self):
        """Verify replacing membership rows creates PTR records for new members."""
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone).delete()
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_2)

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

    def test_create_assigns_ptr_record(self):
        """Verify create() stores matching PTR record."""
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
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

    def test_create_rejects_multiple_catalog_memberships(self):
        """Verify create() rejects multiple-catalog assignment attempts."""
        second_catalog_dns_zone = DNSZone.objects.create(name="catalog-m2m-2.example.com")
        second_catalog_zone = CatalogZone.objects.create(dns_zone=second_catalog_dns_zone)

        with self.assertRaises(CatalogZoneMembershipAlreadyExistsError):
            with transaction.atomic():
                CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
                CatalogZoneMembership.objects.create(catalog_zone=second_catalog_zone, member_zone=self.member_zone_1)

        memberships = CatalogZoneMembership.objects.filter(member_zone=self.member_zone_1)
        self.assertEqual(memberships.count(), 0)

    def test_delete_removes_member_ptr_record(self):
        """Verify delete() removes the derived member PTR record."""
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        membership = CatalogZoneMembership.objects.get(
            catalog_zone=self.catalog_zone,
            member_zone=self.member_zone_1,
        )
        ptr_name = f"{membership.member_node_label}.zones"

        self.assertTrue(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=ptr_name).exists())
        membership.delete()
        self.assertFalse(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name=ptr_name).exists())

    def test_queryset_delete_deletes_member_ptr_records(self):
        """Verify queryset delete() removes all derived member PTR records."""
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_1)
        CatalogZoneMembership.objects.create(catalog_zone=self.catalog_zone, member_zone=self.member_zone_2)
        memberships = CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone)
        ptr_names = [f"{label}.zones" for label in memberships.values_list("member_node_label", flat=True)]

        memberships.delete()
        self.assertEqual(CatalogZoneMembership.objects.filter(catalog_zone=self.catalog_zone).count(), 0)
        self.assertEqual(PTRRecord.objects.filter(zone=self.catalog_dns_zone, name__in=ptr_names).count(), 0)


class NSRecordTestCase(TestCase):
    """Test the NSRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_nsrecord(self):
        ns_record = NSRecord.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)

        self.assertEqual(ns_record.name, "primary")
        self.assertEqual(ns_record.server, "example-server.com.")
        self.assertEqual(str(ns_record), ns_record.name)

    def test_get_absolute_url(self):
        ns_record = NSRecord.objects.create(name="primary", server="example-server.com.", zone=self.dns_zone)
        self.assertEqual(ns_record.get_absolute_url(), f"/plugins/dns/ns-records/{ns_record.id}/")


class ARecordTestCase(TestCase):
    """Test the ARecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.0.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="10.0.0.1/32", namespace=namespace, status=status)
        # IPv6 Test data
        Prefix.objects.create(prefix="2001:db8:abcd:99::/64", namespace=namespace, type="Pool", status=status)
        cls.ipv6_address = IPAddress.objects.create(
            address="2001:db8:abcd:99::1/128", namespace=namespace, status=status
        )

    def test_create_arecord(self):
        a_record = ARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)

        self.assertEqual(a_record.name, "site.example.com")
        self.assertEqual(a_record.ip_address, self.ip_address)
        self.assertEqual(a_record.ttl, 3600)
        self.assertEqual(str(a_record), a_record.name)

    def test_create_ipv6_arecord_fails(self):
        # Test that creating an IPv6 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = ARecord(name="invalid.example.com", ip_address=self.ipv6_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_create_ipv6_arecord_fails_on_save(self):
        """Creating via ORM should also fail due to save() calling clean()."""
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="invalid-save.example.com", ip_address=self.ipv6_address, zone=self.dns_zone)

    def test_get_absolute_url(self):
        a_record = ARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)
        self.assertEqual(a_record.get_absolute_url(), f"/plugins/dns/a-records/{a_record.id}/")


class AAAARecordTestCase(TestCase):
    """Test the AAAARecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="2001:db8:abcd:12::/64", namespace=namespace, type="Pool", status=status)
        cls.ip_address = IPAddress.objects.create(address="2001:db8:abcd:12::1/128", namespace=namespace, status=status)
        # IPv4 Test Data
        Prefix.objects.create(prefix="10.1.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ipv4_address = IPAddress.objects.create(address="10.1.0.1/32", namespace=namespace, status=status)

    def test_create_aaaarecord(self):
        aaaa_record = AAAARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)

        self.assertEqual(aaaa_record.name, "site.example.com")
        self.assertEqual(aaaa_record.ip_address, self.ip_address)
        self.assertEqual(aaaa_record.ttl, 3600)
        self.assertEqual(str(aaaa_record), aaaa_record.name)

    def test_create_ipv4_aaaarecord_fails(self):
        # Test that creating an IPv4 Address fails
        with self.assertRaises(ValidationError):
            invalid_record = AAAARecord(name="invalid.example.com", ip_address=self.ipv4_address, zone=self.dns_zone)
            invalid_record.full_clean()

    def test_create_ipv4_aaaarecord_fails_on_save(self):
        """Creating via ORM should also fail due to save() calling clean()."""
        with self.assertRaises(ValidationError):
            AAAARecord.objects.create(
                name="invalid-save.example.com",
                ip_address=self.ipv4_address,
                zone=self.dns_zone,
            )

    def test_get_absolute_url(self):
        aaaa_record = AAAARecord.objects.create(name="site.example.com", ip_address=self.ip_address, zone=self.dns_zone)
        self.assertEqual(aaaa_record.get_absolute_url(), f"/plugins/dns/aaaa-records/{aaaa_record.id}/")


class CNAMERecordTestCase(TestCase):
    """Test the CNAMERecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_cnamerecord(self):
        cname_record = CNAMERecord.objects.create(name="www.example.com", alias="site.example.com", zone=self.dns_zone)

        self.assertEqual(cname_record.name, "www.example.com")
        self.assertEqual(cname_record.alias, "site.example.com")
        self.assertEqual(str(cname_record), cname_record.name)

    def test_get_absolute_url(self):
        cname_record = CNAMERecord.objects.create(name="www.example.com", alias="site.example.com", zone=self.dns_zone)
        self.assertEqual(cname_record.get_absolute_url(), f"/plugins/dns/cname-records/{cname_record.id}/")


class MXRecordTestCase(TestCase):
    """Test the MXRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_mxrecord(self):
        mx_record = MXRecord.objects.create(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)

        self.assertEqual(mx_record.name, "mail-record")
        self.assertEqual(mx_record.preference, 10)
        self.assertEqual(mx_record.mail_server, "mail.example.com")
        self.assertEqual(str(mx_record), mx_record.name)

    def test_get_absolute_url(self):
        mx_record = MXRecord.objects.create(name="mail-record", mail_server="mail.example.com", zone=self.dns_zone)
        self.assertEqual(mx_record.get_absolute_url(), f"/plugins/dns/mx-records/{mx_record.id}/")


class TXTRecordTestCase(TestCase):
    """Test the TXTRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_txtrecord(self):
        txt_record = TXTRecord.objects.create(name="txt-record", text="spf-record", zone=self.dns_zone)

        self.assertEqual(txt_record.name, "txt-record")
        self.assertEqual(txt_record.text, "spf-record")
        self.assertEqual(str(txt_record), txt_record.name)

    def test_get_absolute_url(self):
        txt_record = TXTRecord.objects.create(name="txt-record", text="spf-record", zone=self.dns_zone)
        self.assertEqual(txt_record.get_absolute_url(), f"/plugins/dns/txt-records/{txt_record.id}/")


class PTRRecordTestCase(TestCase):
    """Test the PTRRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com")

    def test_create_ptrrecord(self):
        ptr_record = PTRRecord.objects.create(name="ptr-record", ptrdname="ptr-record", zone=self.dns_zone)

        self.assertEqual(ptr_record.ptrdname, "ptr-record")
        self.assertEqual(str(ptr_record), ptr_record.ptrdname)

    def test_get_absolute_url(self):
        ptr_record = PTRRecord.objects.create(ptrdname="ptr-record", zone=self.dns_zone)
        self.assertEqual(ptr_record.get_absolute_url(), f"/plugins/dns/ptr-records/{ptr_record.id}/")


class SRVRecordTestCase(TestCase):
    """Test the SRVRecord model."""

    @classmethod
    def setUpTestData(cls):
        cls.dns_zone = DNSZone.objects.create(name="example.com", ttl=7200)

    def test_create_srvrecord(self):
        srv_record = SRVRecord.objects.create(
            name="_sip._tcp.example.com",
            priority=10,
            weight=5,
            port=5060,
            target="sip.example.com",
            zone=self.dns_zone,
            ttl=3600,
            description="SIP server",
            comment="Primary SIP server",
        )

        self.assertEqual(srv_record.name, "_sip._tcp.example.com")
        self.assertEqual(srv_record.priority, 10)
        self.assertEqual(srv_record.weight, 5)
        self.assertEqual(srv_record.port, 5060)
        self.assertEqual(srv_record.target, "sip.example.com")
        self.assertEqual(srv_record.ttl, 3600)
        self.assertEqual(srv_record.description, "SIP server")
        self.assertEqual(srv_record.comment, "Primary SIP server")
        self.assertEqual(str(srv_record), srv_record.name)

    def test_create_srvrecord_wo_ttl(self):
        srv_record = SRVRecord.objects.create(
            name="_sip._tcp.example.com",
            priority=10,
            weight=5,
            port=5060,
            target="sip.example.com",
            zone=self.dns_zone,
            description="SIP server",
            comment="Primary SIP server",
        )

        self.assertEqual(srv_record.name, "_sip._tcp.example.com")
        self.assertEqual(srv_record.priority, 10)
        self.assertEqual(srv_record.weight, 5)
        self.assertEqual(srv_record.port, 5060)
        self.assertEqual(srv_record.target, "sip.example.com")
        self.assertEqual(srv_record.ttl, 7200)  # Inherits from DNSZone
        self.assertEqual(srv_record.description, "SIP server")
        self.assertEqual(srv_record.comment, "Primary SIP server")
        self.assertEqual(str(srv_record), srv_record.name)

    def test_get_absolute_url(self):
        srv_record = SRVRecord.objects.create(
            name="_sip._tcp.example.com", priority=10, weight=5, port=5060, target="sip.example.com", zone=self.dns_zone
        )
        self.assertEqual(srv_record.get_absolute_url(), f"/plugins/dns/srv-records/{srv_record.id}/")


@override_config(nautobot_dns_models__CNAME_RESTRICTION_ENABLED=True)
class CNAMEExclusivityModelTestCase(TestCase):
    """Model-level tests for exact-match CNAME exclusivity."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(name="example.com")
        # IP setup for ARecord use
        status = Status.objects.get(name="Active")
        namespace = Namespace.objects.get(name="Global")
        Prefix.objects.create(prefix="10.9.0.0/24", namespace=namespace, type="Pool", status=status)
        cls.ipv4_1 = IPAddress.objects.create(address="10.9.0.1/32", namespace=namespace, status=status)
        cls.ipv4_2 = IPAddress.objects.create(address="10.9.0.2/32", namespace=namespace, status=status)

    def test_cname_blocked_when_arecord_exists(self):
        ARecord.objects.create(name="app", ip_address=self.ipv4_1, zone=self.zone)
        with self.assertRaises(ValidationError):
            cname_record = CNAMERecord(name="app", alias="target.example.com", zone=self.zone)
            cname_record.validated_save()

    def test_non_cname_blocked_when_cname_exists(self):
        CNAMERecord.objects.create(name="web", alias="web.example.com", zone=self.zone)
        # TODO: remove `save` overwrite from ARecord model and revisit this test
        with self.assertRaises(ValidationError):
            ARecord.objects.create(name="web", ip_address=self.ipv4_2, zone=self.zone)

    def test_zone_qualified_name_allowed(self):
        """A(name='host') does NOT block CNAME(name='host.zone') since names must match exactly."""
        ARecord.objects.create(name="testrecord", ip_address=self.ipv4_1, zone=self.zone)
        # Allowed because name differs (zone-qualified vs relative)
        CNAMERecord.objects.create(name=f"testrecord.{self.zone.name}", alias="x.example.com", zone=self.zone)

    def test_trailing_dot_zone_qualified_allowed(self):
        """A(name='host') does NOT block CNAME(name='host.zone.') (trailing dot normalized)."""
        ARecord.objects.create(name="td", ip_address=self.ipv4_1, zone=self.zone)
        # Trailing dot is removed to "td.zone", still zone-qualified and thus different from "td"
        CNAMERecord.objects.create(name=f"td.{self.zone.name}.", alias="x.example.com", zone=self.zone)

    @override_config(nautobot_dns_models__CNAME_RESTRICTION_ENABLED=False)
    def test_opt_out_allows_coexistence(self):
        ARecord.objects.create(name="opt", ip_address=self.ipv4_1, zone=self.zone)
        # Should succeed when enforcement disabled
        CNAMERecord.objects.create(name="opt", alias="opt.example.com", zone=self.zone)


class DNSRecordNameLengthValidationTest(TestCase):
    """Test DNS record name validation rules from RFC 1035 §3.1."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(name="example.com")

    # ASCII Label Tests
    def test_accepts_valid_ascii_label(self):
        record = TXTRecord(name="www", text="test", zone=self.zone)
        record.full_clean()  # Should not raise
        record = TXTRecord(name="www.subdomain", text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_accepts_ascii_label_of_63_bytes(self):
        label_63 = "a" * 63
        record = TXTRecord(name=label_63, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_ascii_label_of_64_bytes(self):
        label_64 = "a" * 64
        record = TXTRecord(name=label_64, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            f"Label '{label_64}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Unicode Label Tests
    def test_accepts_valid_unicode_label(self):
        label = "ü"
        record = TXTRecord(name=label, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_accepts_unicode_label_of_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63)
        record = TXTRecord(name=label, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_unicode_label_exceeding_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63) + "ü"
        record = TXTRecord(name=label, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            f"Label '{label}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Enforcement Flag Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_label_exceeding_63_bytes_when_enforcement_disabled(self):
        record = TXTRecord(name="a" * 64, text="test", zone=self.zone)
        record.full_clean()  # Should not raise

    def test_rejects_label_exceeding_63_bytes_when_enforcement_enabled(self):
        record = TXTRecord(name="a" * 64, text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            "Label 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' exceeds the maximum length of 63 bytes (octets) in wire format",
            str(context.exception),
        )

    # FQDN Length Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_fqdn_exceeding_255_bytes_when_enforcement_disabled(self):
        zone = DNSZone.objects.create(
            name="x" * 63, filename="x" * 63 + ".zone", soa_mname="ns1." + "x" * 63 + ".", soa_rname="admin@example.com"
        )
        record = TXTRecord(name="x" * 63 + "." + "x" * 63 + "." + "x" * 63, text="test", zone=zone)
        record.full_clean()  # Should not raise

    def test_rejects_fqdn_exceeding_255_bytes_when_enforcement_enabled(self):
        zone_label = "z" * 63
        zone = DNSZone.objects.create(
            name=zone_label,
            filename=zone_label + ".zone",
            soa_mname="ns1." + zone_label + ".",
            soa_rname="admin@example.com",
        )
        record = TXTRecord(name="a" * 63 + "." + "b" * 63, text="test", zone=zone)
        record.full_clean()  # Should not raise
        record = TXTRecord(name="a" * 63 + "." + "b" * 63 + "." + "c" * 63, text="test", zone=zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn(
            "Total length of DNS name cannot exceed 255 bytes (octets) in wire format", str(context.exception)
        )

    # Structure/Format Tests
    def test_rejects_empty_label(self):
        record = TXTRecord(name="www..subdomain", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

    def test_rejects_label_with_leading_or_trailing_dot(self):
        # Leading dot
        record = TXTRecord(name=".example", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))
        # Trailing dot
        record = TXTRecord(name="example.", text="test", zone=self.zone)
        with self.assertRaises(ValidationError) as context:
            record.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))


class DNSZoneNameLengthValidationTest(TestCase):
    """Test DNS zone name validation rules from RFC 1035 §3.1.

    Note: We don't test wire format length for zones because the model's CharField
    max_length=200 constraint is stricter than the DNS wire format limit of 255 octets.
    The wire format test is only needed for records, which can have longer names
    when combined with their zone.
    """

    @classmethod
    def setUpTestData(cls):
        cls.zone = DNSZone.objects.create(name="example.com")

    # ASCII Label Tests
    def test_accepts_valid_ascii_label(self):
        zone = DNSZone(name="test1", filename="test1.zone", soa_mname="ns1.test1.", soa_rname="admin@example.com")
        zone.full_clean()  # Should not raise
        zone = DNSZone(
            name="test2.example.com",
            filename="test2.example.com.zone",
            soa_mname="ns1.test2.example.com.",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_accepts_ascii_label_of_63_bytes(self):
        label_63 = "a" * 63
        zone = DNSZone(
            name=label_63,
            filename=label_63 + ".zone",
            soa_mname="ns1." + label_63 + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_rejects_ascii_label_of_64_bytes(self):
        label_64 = "a" * 64
        zone = DNSZone(
            name=label_64,
            filename=label_64 + ".zone",
            soa_mname="ns1." + label_64 + ".",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn(
            f"Label '{label_64}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Unicode Label Tests
    def test_accepts_valid_unicode_label(self):
        label = "ü"
        zone = DNSZone(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_accepts_unicode_label_of_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63)
        zone = DNSZone(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        zone.full_clean()  # Should not raise

    def test_rejects_unicode_label_exceeding_63_idna_bytes(self):
        label = _make_unicode_label_with_idna_length("ü", 63) + "ü"
        zone = DNSZone(
            name=label,
            filename=label + ".zone",
            soa_mname="ns1." + label + ".",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn(
            f"Label '{label}' exceeds the maximum length of 63 bytes (octets) in wire format", str(context.exception)
        )

    # Enforcement Flag Tests
    @override_config(nautobot_dns_models__DNS_VALIDATION_LEVEL=False)
    def test_accepts_label_exceeding_63_bytes_when_enforcement_disabled(self):
        zone = DNSZone(
            name="a" * 64, filename="a" * 64 + ".zone", soa_mname="ns1." + "a" * 64 + ".", soa_rname="admin@example.com"
        )
        zone.full_clean()  # Should not raise

    def test_rejects_label_exceeding_63_bytes_when_enforcement_enabled(self):
        zone = DNSZone(
            name="a" * 64, filename="a" * 64 + ".zone", soa_mname="ns1." + "a" * 64 + ".", soa_rname="admin@example.com"
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn(
            "Label 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' exceeds the maximum length of 63 bytes (octets) in wire format",
            str(context.exception),
        )

    # Structure/Format Tests
    def test_rejects_empty_label(self):
        zone = DNSZone(
            name="example..com",
            filename="example..com.zone",
            soa_mname="ns1.example..com.",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))

    def test_rejects_label_with_leading_or_trailing_dot(self):
        # Leading dot
        zone = DNSZone(
            name=".example",
            filename=".example.zone",
            soa_mname="ns1..example.",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))
        # Trailing dot
        zone = DNSZone(
            name="example.",
            filename="example..zone",
            soa_mname="ns1.example..",
            soa_rname="admin@example.com",
        )
        with self.assertRaises(ValidationError) as context:
            zone.full_clean()
        self.assertIn("Empty labels are not allowed", str(context.exception))
