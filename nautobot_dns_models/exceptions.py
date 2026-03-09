"""DNS Models Plugin Exception Classes."""


class DNSProcessingError(Exception):
    """Base exception for DNS rule processing errors."""


class DNSTemplateEmptyError(DNSProcessingError):
    """Template rendered empty result - data missing for DNS processing."""

    def __init__(self, field_name, template_str, context_keys=None):
        """
        Initialize with template details for debugging.

        Args:
            field_name: The template field that failed (e.g., 'name_template')
            template_str: The actual template that rendered empty
            context_keys: Available context variables (for debugging)
        """
        self.field_name = field_name
        self.template_str = template_str
        self.context_keys = context_keys or []

        super().__init__(f"Template {field_name} rendered empty: {template_str}")
