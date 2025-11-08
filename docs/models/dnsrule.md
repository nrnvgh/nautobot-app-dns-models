# DNS Rule Model

The DNSRule model defines automated DNS record creation rules that trigger when specified Nautobot objects are created, modified, or deleted.

## Model Fields

### Core Fields
- `name` (CharField): Unique identifier, max 100 characters
- `description` (CharField): Optional description, max 200 characters  
- `enabled` (BooleanField): Rule active status, default True
- `content_type` (ForeignKey): ContentType that triggers this rule
- `location` (ForeignKey): Optional Location for rule scoping, null for global rules
- `tenant` (ForeignKey): Optional Tenant for rule scoping, null for global rules

### Template Fields
- `zone_template` (TextField): Jinja2 template for DNS zone name
- `record_type` (CharField): DNS record type choice (A, AAAA)
- `name_template` (TextField): Jinja2 template for record name
- `value_template` (TextField): Jinja2 template for record value

## Model Constraints

### Uniqueness Constraint
```python
UniqueConstraint(
    fields=["content_type", "record_type", "location", "tenant"],
    condition=Q(enabled=True),
    name="unique_enabled_rule_per_content_record_location_tenant"
)
```

**Behavior**: Only one enabled rule per (content_type, record_type, location, tenant) combination.

### Validation Methods
- `validate_unique()`: Custom validation for global rules (location=None, tenant=None) to handle NULL uniqueness
- `clean()`: Template syntax validation and record-type-specific field requirements

## Model Meta Options
- `ordering = ["name"]`: Rules ordered alphabetically by name
- Inherits from `PrimaryModel`: Includes standard Nautobot model features

## Database Relationships

### Foreign Key Relationships
- `content_type` → `django_content_type` (CASCADE)
- `location` → `dcim_location` (PROTECT)
- `tenant` → `tenancy_tenant` (PROTECT)

### Reverse Relationships
- `rule_records`: DNSRuleRecord objects that reference this rule
- Used for tracking auto-created DNS records

## Field Validation

### Required Fields
- `name`, `content_type`, `zone_template`, `record_type`, `name_template`, `value_template`

## Related Models

- [DNSRuleRecord](dnsrulerecord.md): Links rules to created DNS records
- [ContentType](https://docs.djangoproject.com/en/stable/ref/contrib/contenttypes/): Django framework for generic relationships
- [Location](https://docs.nautobot.com/projects/core/en/stable/models/dcim/location/): Nautobot location hierarchy
- [Tenant](https://docs.nautobot.com/projects/core/en/stable/models/tenancy/tenant/): Nautobot tenant model
