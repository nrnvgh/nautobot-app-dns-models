"""Unit tests for RuleSetSelector precedence and filtering."""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from nautobot.dcim.models import Device

from nautobot_dns_models.models import DNSRule
from nautobot_dns_models.rules.engine.ruleset import RuleSetSelector
from nautobot_dns_models.tests.mixins.rule_engine import BaseRuleEngineMixin


class RuleSetSelectorTestCase(BaseRuleEngineMixin, TestCase):
    """Validate RuleSetSelector logic directly."""

    def setUp(self):  # pylint: disable=invalid-name
        """Initialize selector under test."""
        self.selector = RuleSetSelector()
        self.device_content_type = ContentType.objects.get_for_model(Device)

    def _create_rule(self, name, record_type="A", location=None, tenant=None):
        """Create a DNS rule with minimal required fields."""
        return DNSRule.objects.create(
            name=name,
            content_type=self.device_content_type,
            location=location,
            tenant=tenant,
            zone_template="example.com",
            record_type=record_type,
            name_template="{{ obj.name }}",
            value_template="{{ obj.primary_ip4 }}",
        )

    def test_resolve_for_scope_prefers_most_specific_per_record_type(self):
        """Use Location+Tenant over Location/Tenant/Global for each record type."""
        global_a = self._create_rule("global-a", record_type="A")
        tenant_a = self._create_rule("tenant-a", record_type="A", tenant=self.tenant)
        location_a = self._create_rule("location-a", record_type="A", location=self.location)
        location_tenant_a = self._create_rule(
            "location-tenant-a", record_type="A", location=self.location, tenant=self.tenant
        )
        global_aaaa = self._create_rule("global-aaaa", record_type="AAAA")

        rules = self.selector.resolve_for_scope(
            self.device_content_type,
            self.location,
            self.tenant,
        )
        rule_ids = {rule.pk for rule in rules}

        self.assertIn(location_tenant_a.pk, rule_ids)
        self.assertIn(global_aaaa.pk, rule_ids)
        self.assertNotIn(global_a.pk, rule_ids)
        self.assertNotIn(tenant_a.pk, rule_ids)
        self.assertNotIn(location_a.pk, rule_ids)

    def test_resolve_for_scope_global_fallback_when_no_specific_rule(self):
        """Return global rule for scoped variants without matching specific rules."""
        global_rule = self._create_rule("global-a", record_type="A")
        test_cases = (
            ("location-and-tenant", self.location, self.tenant),
            ("location-only", self.location, None),
            ("tenant-only", None, self.tenant),
        )

        for label, object_location, object_tenant in test_cases:
            with self.subTest(scope=label):
                rules = self.selector.resolve_for_scope(
                    self.device_content_type,
                    object_location,
                    object_tenant,
                )
                self.assertEqual({rule.pk for rule in rules}, {global_rule.pk})

    def test_resolve_for_scope_with_no_location_or_tenant_returns_global_only(self):
        """When object scope is null/null, return only global rules."""
        self._create_rule("location-only-a", record_type="A", location=self.location)
        self._create_rule("tenant-only-a", record_type="A", tenant=self.tenant)
        global_rule = self._create_rule("global-a", record_type="A")

        rules = self.selector.resolve_for_scope(
            self.device_content_type,
            None,
            None,
        )

        self.assertEqual({rule.pk for rule in rules}, {global_rule.pk})

    def test_resolve_for_scope_applies_selected_rule_filter_before_precedence(self):
        """Restrict candidate rules with selected_rule_ids before precedence selection."""
        self._create_rule("location-tenant-a", record_type="A", location=self.location, tenant=self.tenant)
        selected_global = self._create_rule("global-a", record_type="A")

        rules = self.selector.resolve_for_scope(
            self.device_content_type,
            self.location,
            self.tenant,
            selected_rule_ids={selected_global.pk},
        )

        self.assertEqual({rule.pk for rule in rules}, {selected_global.pk})

    def test_resolve_for_scope_excludes_disabled_rules(self):
        """Ignore disabled rules even when they are otherwise most specific."""
        disabled_location_tenant = self._create_rule(
            "disabled-location-tenant-a",
            record_type="A",
            location=self.location,
            tenant=self.tenant,
        )
        disabled_location_tenant.enabled = False
        disabled_location_tenant.validated_save()

        global_rule = self._create_rule("global-a", record_type="A")

        rules = self.selector.resolve_for_scope(
            self.device_content_type,
            self.location,
            self.tenant,
        )

        self.assertEqual({rule.pk for rule in rules}, {global_rule.pk})
