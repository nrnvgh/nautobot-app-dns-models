# DNS Rule Model

The DNSRule model defines automated DNS record creation rules that trigger when specified Nautobot objects are created, modified, or deleted.

## Model Fields

### Core Fields
- `name` (CharField): Unique identifier, max 100 characters
- `description` (CharField): Optional description, max 200 characters  
- `enabled` (BooleanField): Rule active status, default True
- `content_type` (ForeignKey): ContentType that triggers this rule
- `location` (ForeignKey): Optional Location for rule scoping, null for global rules

### Template Fields
- `zone_template` (TextField): Jinja2 template for DNS zone name
- `record_type` (CharField): DNS record type choice (A, AAAA, CNAME, MX, NS, PTR, SRV, TXT)
- `name_template` (TextField): Jinja2 template for record name
- `value_template` (TextField): Jinja2 template for record value

### Record-Specific Template Fields
- `preference_template` (TextField): MX record preference value, blank for non-MX records
- `priority_template` (TextField): SRV record priority value, blank for non-SRV records  
- `weight_template` (TextField): SRV record weight value, blank for non-SRV records
- `port_template` (TextField): SRV record port number, blank for non-SRV records

## Model Constraints

### Uniqueness Constraint
```python
UniqueConstraint(
    fields=["content_type", "record_type", "location"],
    condition=Q(enabled=True),
    name="unique_enabled_rule_per_content_record_location"
)
```

**Behavior**: Only one enabled rule per (content_type, record_type, location) combination.

### Validation Methods
- `validate_unique()`: Custom validation for global rules (location=None) to handle NULL uniqueness
- `clean()`: Template syntax validation and record-type-specific field requirements

## Model Meta Options
- `ordering = ["name"]`: Rules ordered alphabetically by name
- Inherits from `PrimaryModel`: Includes standard Nautobot model features

## Database Relationships

### Foreign Key Relationships
- `content_type` → `django_content_type` (CASCADE)
- `location` → `dcim_location` (PROTECT)

### Reverse Relationships
- `dnsrulerecord_set`: DNSRuleRecord objects that reference this rule
- Used for tracking auto-created DNS records

## Field Validation

### Required Fields
- `name`, `content_type`, `zone_template`, `record_type`, `name_template`, `value_template`

### Record-Type Specific Requirements
- **MX Records**: `preference_template` required
- **SRV Records**: `priority_template`, `weight_template`, `port_template` required
- **Other Records**: Only core templates required

## Related Models

- [DNSRuleRecord](dnsrulerecord.md): Links rules to created DNS records
- [ContentType](https://docs.djangoproject.com/en/stable/ref/contrib/contenttypes/): Django framework for generic relationships
- [Location](https://docs.nautobot.com/projects/core/en/stable/models/dcim/location/): Nautobot location hierarchy
