# DNS Rule Record Model

The DNS Rule Record model serves as a linking table that tracks the relationship between source objects, DNS rules, and the DNS records that were automatically created. This model enables efficient updates and cleanup when source objects are modified or deleted.

## Purpose

When a DNS rule triggers and creates a DNS record, a DNSRuleRecord entry is created to maintain the connection between:
1. The source object that triggered the rule (e.g., a Device or Interface)
2. The DNS rule that was applied
3. The DNS record that was created

This linking approach avoids the need to re-render Jinja2 templates when performing updates or deletions, making operations more efficient and reliable.

## Fields

- `rule` (DNSRule): Foreign key to the DNS rule that created the record.
- `content_type` (ContentType): Content type of the source object that triggered the rule.
- `object_id` (UUID): Primary key of the source object.
- `source_object` (GenericForeignKey): Generic foreign key to the actual source object.
- `dns_record_content_type` (ContentType): Content type of the created DNS record.
- `dns_record_object_id` (UUID): Primary key of the created DNS record.
- `dns_record` (GenericForeignKey): Generic foreign key to the actual DNS record.

## Inherited Fields

As a BaseModel, DNSRuleRecord automatically includes:
- `id` (UUID): Primary key
- `created` (DateTime): Timestamp when the record was created
- `last_updated` (DateTime): Timestamp when the record was last modified

## Constraints

- **Unique Together**: The combination of rule, content_type, object_id, dns_record_content_type, and dns_record_object_id must be unique to prevent duplicate linkage records.

## Use Cases

### Record Creation
When a DNS rule creates a new DNS record, a DNSRuleRecord is created to link them:
```python
# Example: Interface gets an IP, rule creates A record
source_obj = Interface.objects.get(name="eth0")
dns_record = ARecord.objects.create(...)
rule = DNSRule.objects.get(name="interface-a-record")

DNSRuleRecord.objects.create(
    rule=rule,
    content_type=ContentType.objects.get_for_model(Interface),
    object_id=source_obj.id,
    dns_record_content_type=ContentType.objects.get_for_model(ARecord),
    dns_record_object_id=dns_record.id
)
```

### Record Updates
When the source object changes, the system can:
1. Find all DNSRuleRecord entries for that object
2. Update the linked DNS records with new template-rendered values
3. Avoid re-rendering templates to "search" for existing records

### Record Cleanup
When a source object is deleted or no longer matches rule criteria:
1. Find DNSRuleRecord entries for the object
2. Delete the associated DNS records
3. Delete the DNSRuleRecord entries

## Relationship Diagram

```
Source Object (Device/Interface/etc.)
    ↓ (triggers)
DNS Rule
    ↓ (creates)
DNS Record (A/AAAA/CNAME/etc.)
    ↑
    └── DNSRuleRecord (tracks relationship)
```

## Related Models

- [DNS Rule Model](dnsrule.md): The rule definition that creates DNS records
- Various DNS record models: [A Record](arecordmodel.md), [AAAA Record](aaaarecordmodel.md), [CNAME Record](cnamerecordmodel.md), etc.
