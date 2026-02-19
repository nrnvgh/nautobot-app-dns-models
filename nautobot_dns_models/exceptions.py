"""DNS Models Plugin Exception Classes."""


class DNSProcessingError(Exception):
    """Base exception for DNS rule processing errors."""


class DNSTemplateEmptyError(DNSProcessingError):
    """Template rendered empty result - data missing for DNS processing."""

    def __init__(self, field_name: str, template_str: str, context_keys: list[str] = None):
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


class DNSFilterError(DNSProcessingError):
    """Error in DNS template filter processing."""

    def __init__(self, filter_name: str, message: str):
        """
        Initialize with filter details for debugging.

        Args:
            filter_name: The filter that failed (e.g., 'ip_address')
            message: Specific error message from the filter
        """
        self.filter_name = filter_name
        self.message = message
        super().__init__(f"Filter '{filter_name}' error: {message}")
