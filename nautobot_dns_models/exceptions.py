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


class DNSRuleEngineIntegrityError(DNSProcessingError):
    """Base exception for unrecoverable DNS rule engine integrity failures."""


class DNSRecordContentTypeResolutionError(DNSRuleEngineIntegrityError):
    """Raised when a DNS record ContentType cannot be resolved to a model class."""


class DNSRuleRenderedValueLookupError(DNSProcessingError):
    """
    Rendered DNS rule value could not be resolved to required database objects.

    This is used when a template renders syntactically valid output (for example DNS view names,
    zone names, or address UUIDs), but those rendered values cannot be resolved to objects required
    for record creation or reconciliation in the current database state.
    """

    def __init__(self, field_name, message, reason_code=None):
        """
        Initialize with lookup-failure context for logging and reason-code inference.

        Args:
            field_name: Template field associated with the failed lookup.
            message: Human-readable description of the lookup failure.
            reason_code: Optional stable reason code for structured log classification.
        """
        self.field_name = field_name
        self.reason_code = reason_code
        super().__init__(message)
