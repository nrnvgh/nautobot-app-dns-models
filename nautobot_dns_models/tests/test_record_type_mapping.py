"""Tests for DNS record type to model mapping helpers."""

from nautobot.apps.testing import TestCase

from nautobot_dns_models.choices import DNSRuleRecordTypeChoices
from nautobot_dns_models.record_type_mapping import get_dns_record_model_class


class RecordTypeMappingTestCase(TestCase):
    """Validate DNS rule record type to model class resolution."""

    def test_get_dns_record_model_class_for_all_supported_choices(self):
        """Return expected model class for each supported record type choice."""
        for record_type, _label in DNSRuleRecordTypeChoices.CHOICES:
            with self.subTest(record_type=record_type):
                model_class = get_dns_record_model_class(record_type)
                self.assertEqual(model_class.__name__, f"{record_type}Record")
                self.assertEqual(model_class._meta.app_label, "nautobot_dns_models")

    def test_get_dns_record_model_class_rejects_unsupported_extant_record_type(self):
        """Raise ValueError for an unsupported but extant record type."""
        unsupported_record_type = "NS"
        with self.assertRaises(ValueError) as exc:
            get_dns_record_model_class(unsupported_record_type)

        self.assertIn('Unsupported DNS rule record_type "NS"', str(exc.exception))

    def test_get_dns_record_model_class_rejects_unsupported_record_type(self):
        """Raise ValueError for an unsupported record type."""
        unsupported_record_type = "UNSUPPORTED"
        with self.assertRaises(ValueError) as exc:
            get_dns_record_model_class(unsupported_record_type)

        self.assertIn('Unsupported DNS rule record_type "UNSUPPORTED"', str(exc.exception))
