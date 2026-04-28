"""Signal behavior tests for rule-aware DNS processing gates."""

from unittest import skip
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from nautobot_dns_models.models import DNSRule, DNSRuleFailureState
from nautobot_dns_models.tests.mixins.rule_engine import BaseRuleEngineMixin


class RuleAwareSignalTriggerTestCase(BaseRuleEngineMixin, TestCase):
    """Validate signal trigger gating for changed-field-aware DNS processing."""

    def _create_interface_rule(self, name, name_template):
        return DNSRule.objects.create(
            name=name,
            content_type=ContentType.objects.get_for_model(type(self.interface)),
            record_type="A",
            zone_template="example.com",
            name_template=name_template,
            value_template="{{ obj.ip_addresses.first() }}",
            enabled=True,
        )

    @skip("Template-aware preflight check is not yet implemented")
    def test_interface_unrelated_field_change_skips_dns_processing(self):
        """Changing an unrelated interface field should skip DNS engine processing."""
        self._create_interface_rule(
            name="interface-name-only-rule",
            name_template="{{ obj.name }}",
        )
        self.interface.ip_addresses.set([self.ip_addresses[0]])

        with patch("nautobot_dns_models.signals.DNSRuleEngine.process_object") as process_object:
            self.interface.description = "updated-description"
            self.interface.validated_save()

        process_object.assert_not_called()

    def test_interface_referenced_field_change_processes_dns_rules(self):
        """Changing a referenced interface field should trigger DNS engine processing."""
        self._create_interface_rule(
            name="interface-name-change-rule",
            name_template="{{ obj.name }}",
        )
        self.interface.ip_addresses.set([self.ip_addresses[0]])

        with patch("nautobot_dns_models.signals.DNSRuleEngine.process_object") as process_object:
            self.interface.name = "eth0-renamed"
            self.interface.validated_save()

        process_object.assert_called_once()

    @skip("Template-aware preflight check is not yet implemented")
    def test_parent_change_skips_interface_cascade_when_no_parent_dependencies(self):
        """Device field changes should not cascade when interface rules do not use parent fields."""
        self._create_interface_rule(
            name="interface-local-only-rule",
            name_template="{{ obj.name }}",
        )
        self.interface.ip_addresses.set([self.ip_addresses[0]])

        with patch("nautobot_dns_models.signals.DNSRuleEngine.process_objects_pipeline") as process_pipeline:
            self.device.comments = "parent-changed"
            self.device.validated_save()

        process_pipeline.assert_not_called()

    def test_parent_change_runs_interface_cascade_when_parent_dependencies_exist(self):
        """Device field changes should cascade when interface rules reference parent attributes."""
        self._create_interface_rule(
            name="interface-parent-dependent-rule",
            name_template="{{ obj.device.name }}-{{ obj.name }}",
        )
        self.interface.ip_addresses.set([self.ip_addresses[0]])

        with patch("nautobot_dns_models.signals.DNSRuleEngine.process_objects_pipeline") as process_pipeline:
            self.device.name = "test-device-renamed"
            self.device.validated_save()

        process_pipeline.assert_called_once()

    def test_interface_delete_removes_dns_rule_failure_state_rows(self):
        """Deleting a source object should remove its failure-state rows."""
        source_object_id = self.interface.id
        source_content_type = ContentType.objects.get_for_model(type(self.interface))
        now = timezone.now()
        DNSRuleFailureState.objects.create(
            source_content_type=source_content_type,
            source_object_id=source_object_id,
            rule=None,
            candidate_record_type="A",
            candidate_name="delete-source-test",
            candidate_zone_id=None,
            candidate_address_id=None,
            latest_exception_type="IntegrityError",
            latest_error="synthetic failure",
            latest_pgcode="23505",
            latest_constraint="synthetic_constraint",
            first_seen=now,
            last_seen=now,
            attempt_count=1,
            consecutive_failures=1,
        )
        self.assertEqual(
            DNSRuleFailureState.objects.filter(
                source_content_type=source_content_type,
                source_object_id=source_object_id,
            ).count(),
            1,
        )

        self.interface.delete()

        self.assertEqual(
            DNSRuleFailureState.objects.filter(
                source_content_type=source_content_type,
                source_object_id=source_object_id,
            ).count(),
            0,
        )
