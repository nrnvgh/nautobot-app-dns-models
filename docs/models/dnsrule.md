# DNS Rule Model

The DNSRule model defines automated DNS record creation rules that trigger when specified Nautobot objects are created, modified, or deleted.

## Model Fields

### Core Fields

- `name` (string): Unique identifier, max 100 characters.
- `description` (string): Description of the rule.
- `enabled` (boolean): Rule active status. (default: `True`)
- `content_type` (ContentType): ContentType (e.g., `Device`, `Interface`, etc), which triggers this rule.
- `location` (Location): Optional Location for rule scoping, null for global rules.
- `tenant` (Tenant): Optional Tenant for rule scoping, null for global rules.

### Template Fields
- `view_template` (string): Jinja2 template for DNS view names (blank uses Default view).
- `zone_template` (string): Jinja2 template for DNS zone name.
- `record_type` (string): DNS record type choice (A, AAAA).
- `name_template` (string): Jinja2 template for record name.
- `value_template` (string): Jinja2 template for record value.

### Reverse Relationships
- `rule_records`: DNSRuleRecord objects that reference this rule and track auto-created DNS records.

## Model Constraints

### Uniqueness Enforcement
Enabled rules are unique per `(content_type, record_type, location, tenant)`, enforced in `validate_unique()` for backend portability.

### Validation
- `validate_unique()`: Enforces enabled-scope uniqueness and emits field-aware conflict errors.
- `clean()`: Runs template validation and verifies the selected content type resolves to a model class.

## Related Models

- [DNSRuleRecord](dnsrulerecord.md): Links rules to created DNS records
- [ContentType](https://docs.djangoproject.com/en/stable/ref/contrib/contenttypes/): Django framework for generic relationships
- [Location](https://docs.nautobot.com/projects/core/en/stable/models/dcim/location/): Nautobot location hierarchy
- [Tenant](https://docs.nautobot.com/projects/core/en/stable/models/tenancy/tenant/): Nautobot tenant model
