"""Test transform registry and transform functions."""

from nautobot.apps.testing import TestCase


class TransformSystemTestCase(TestCase):
    """Test the transform registry and function system."""

    def test_transform_registration(self):
        """Test that transforms are properly registered."""
        from nautobot_dns_models.transform_registry import list_transforms, get_transform_choices
        
        # Should have registered transforms
        transforms = list_transforms()
        self.assertGreater(len(transforms), 0)
        
        # Check specific transforms exist
        self.assertIn("normalize", transforms)
        self.assertIn("replace_slashes", transforms)
        self.assertIn("lower", transforms)

    def test_transform_choices_generation(self):
        """Test dynamic choices generation for model fields."""
        from nautobot_dns_models.transform_registry import get_transform_choices
        
        choices = get_transform_choices()
        
        # Should have "No Transform" option
        choice_values = [choice[0] for choice in choices]
        self.assertIn("", choice_values)
        
        # Should have registered transforms
        self.assertIn("normalize", choice_values)
        self.assertIn("replace_slashes", choice_values)

    def test_transform_execution(self):
        """Test actual transform function execution."""
        from nautobot_dns_models.transform_registry import apply_transform
        
        # Test normalize transform
        result = apply_transform("normalize", "Ethernet1/1")
        self.assertEqual(result, "ethernet11")
        
        # Test replace_slashes transform  
        result = apply_transform("replace_slashes", "ge-0/0/1")
        self.assertEqual(result, "ge-0-0-1")
        
        # Test non-existent transform
        result = apply_transform("nonexistent", "test")
        self.assertEqual(result, "test")  # Should return original
        
        # Test empty transform name
        result = apply_transform("", "test")
        self.assertEqual(result, "test")

    def test_transform_error_handling(self):
        """Test transform error handling."""
        from nautobot_dns_models.transform_registry import apply_transform
        
        # Should handle None gracefully
        result = apply_transform("normalize", None)
        self.assertIsNone(result)
        
        # Should handle empty string
        result = apply_transform("normalize", "")
        self.assertEqual(result, "")
