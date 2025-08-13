# DNS Rule Model

The DNS Rule model is used to define automated DNS record creation rules. When objects of specified content types are created or modified, these rules trigger the automatic creation of corresponding DNS records using Jinja2 templates.

## Fields

- `name` (string): Unique name identifier for the DNS rule (max 100 characters).
- `description` (string): Optional description of the DNS rule's purpose.
- `enabled` (boolean): Whether this rule is currently active (default: True).
- `content_type` (ContentType): The Nautobot content type that triggers this rule (e.g., dcim.Device, dcim.Interface).
- `priority` (integer): Rule execution priority when multiple rules apply (lower values = higher priority, default: 100).

## Template Fields

All template fields use Jinja2 syntax and have access to the triggering object as `obj`:

- `zone_template` (text): Template to determine the DNS zone for the record.
- `record_type` (choice): Type of DNS record to create. Available options:
  - A Record
  - AAAA Record  
  - CNAME Record
  - MX Record
  - NS Record
  - PTR Record
  - SRV Record
  - TXT Record
- `name_template` (text): Template for the DNS record name.
- `value_template` (text): Template for the primary record value (used by all record types).

## Record Type-Specific Templates

### MX Records
- `preference_template` (text): Template for MX record preference/priority value.

### SRV Records  
- `priority_template` (text): Template for SRV record priority value.
- `weight_template` (text): Template for SRV record weight value.
- `port_template` (text): Template for SRV record port number.

## Template Context

Templates have access to:
- `obj`: The object that triggered the rule (e.g., Device, Interface, IPAddress)
- Related objects through Django ORM (e.g., `obj.device` for Interface objects)

## Examples

### Device A Record Rule
```yaml
Name: device-a-record
Content Type: dcim | device  
Zone Template: example.com
Record Type: A Record
Name Template: {{ obj.name }}
Value Template: {{ obj.primary_ip4.address.ip }}
```

### Interface A Record Rule
```yaml
Name: interface-a-record
Content Type: dcim | interface
Zone Template: {{ obj.device.location.name }}.example.com  
Record Type: A Record
Name Template: {{ obj.name }}.{{ obj.device.name }}
Value Template: {{ obj.ip_addresses.first.id }}
```

### MX Record Rule
```yaml
Name: mail-mx-record
Content Type: dcim | device
Zone Template: example.com
Record Type: MX Record  
Name Template: mail
Value Template: {{ obj.name }}.example.com
Preference Template: 10
```

## Related Models

DNS rules create linkage records via the [DNSRuleRecord model](dnsrulerecord.md) to track which DNS records were auto-created and enable proper cleanup during updates and deletions.
