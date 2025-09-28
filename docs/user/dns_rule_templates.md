# DNS Rule Template Reference

DNS Rules use Jinja2 templates to dynamically generate DNS record content based on Nautobot object data. This guide provides comprehensive template syntax, filters, and examples for creating effective DNS automation rules.

!!! note "Development Status"
    Template filters may change before final release.

## Template Context

All templates have access to the triggering object as `obj` and can traverse Django ORM relationships:

```jinja2
{{ obj.name }}                    # Object name
{{ obj.device.name }}             # Related device name (e.g. for interfaces)
{{ obj.device.location.name }}    # Device location name
{{ obj.primary_ip4.address }}     # Primary IP address object (e.g. for devices)
```

## Required Templates

Every DNS rule must define these core templates:

- **Zone Template**: Determines which DNS zone contains the record
- **Name Template**: The record name within the zone  
- **Value Template**: The primary record value

Record-specific templates (MX preference, SRV priority/weight/port) are required for those record types.

## Template Filters

### IP Address Filter

**Purpose**: Convert IP address objects to DNS record values for A/AAAA records.

**Usage**:

- `{{ obj.primary_ip4 | ip_address }}` - Creates 1 A record
- `{{ obj.ip_addresses.all() | ip_address }}` - Creates 1 record per IP address  
- `{{ obj.ip_addresses.first() | ip_address }}` - Creates 1 record from first IP
- `{{ obj.ip_addresses.filter(role='primary') | ip_address }}` - Creates 1 record per filtered IP

### DNS Normalize Filter

**Purpose**: Ensure DNS-compliant record names.

**Usage**:

- `{{ obj.name | dns_normalize }}` - Converts to DNS-safe format
- `{{ "Web Server 01" | dns_normalize }}` - Returns `"web-server-01"`
- `{{ "Mgmt/Backup" | dns_normalize }}` - Returns `"mgmt-backup"`

**Transformations**: Lowercase, spaces→hyphens, remove invalid characters

## Template Patterns

### Device Templates

**Basic Device A Record**:
```jinja2
Zone Template: example.com
Name Template: {{ obj.name | dns_normalize }}
Value Template: {{ obj.primary_ip4 | ip_address }}
```

**Location-Aware Device Record**:
```jinja2
Zone Template: {{ obj.location.name | lower }}.example.com
Name Template: {{ obj.name | dns_normalize }}
Value Template: {{ obj.primary_ip4 | ip_address }}
```

### Interface Templates

**Interface A Records (Multi-IP)**:
```jinja2
Zone Template: example.com
Name Template: {{ obj.name | dns_normalize }}.{{ obj.device.name | dns_normalize }}
Value Template: {{ obj.ip_addresses.all() | ip_address }}
```

**Interface CNAME to Device**:
```jinja2
Zone Template: {{ obj.device.location.name | lower }}.example.com
Name Template: {{ obj.name | dns_normalize }}.{{ obj.device.name | dns_normalize }}
Value Template: {{ obj.device.name | dns_normalize }}.mgmt.example.com
```

### Service Templates

**Load Balancer VIP**:
```jinja2
Zone Template: services.example.com
Name Template: {{ obj.name | dns_normalize }}
Value Template: {{ obj.ip_addresses.all() | ip_address }}
```

## Record Type-Specific Templates

### MX Records

**Required Additional Template**:

- `preference_template`: MX record priority value

**Example**:
```jinja2
Zone Template: example.com
Name Template: mail
Value Template: {{ obj.name | dns_normalize }}.example.com
Preference Template: 10
```

**Generated Record**:
```
# Zone: example.com
mail    IN MX    10 web-server-01.example.com.
```

### SRV Records

**Required Additional Templates**:

- `priority_template`: SRV priority value
- `weight_template`: SRV weight value  
- `port_template`: SRV port number

**Example**:
```jinja2
Zone Template: example.com
Name Template: _http._tcp.{{ obj.name | dns_normalize }}
Value Template: {{ obj.name | dns_normalize }}.example.com
Priority Template: 10
Weight Template: 5
Port Template: 80
```

**Generated Record**:
```
# Zone: example.com
_http._tcp.web-server-01    IN SRV    10 5 80 web-server-01.example.com.
```

## Advanced Template Techniques

### Conditional Logic

**Handle Optional Fields**:
```jinja2
{% if obj.primary_ip4 %}
{{ obj.primary_ip4 | ip_address }}
{% else %}
# No primary IP configured
{% endif %}
```

**Location-Specific Behavior**:
```jinja2
{% if obj.device.location.name == "London" %}
{{ obj.name }}.lon.example.com
{% else %}
{{ obj.name }}.example.com
{% endif %}
```

### Complex Naming Schemes

**Hierarchical Names**:
```jinja2
{{ obj.name | dns_normalize }}.{{ obj.device.rack.name | dns_normalize }}.{{ obj.device.location.name | dns_normalize }}
```

**Role-Based Names**:
```jinja2
{% if obj.device.role.name == "Web Server" %}
web-{{ obj.name | dns_normalize }}
{% elif obj.device.role.name == "Database" %}
db-{{ obj.name | dns_normalize }}
{% else %}
{{ obj.name | dns_normalize }}
{% endif %}
```

## Template Validation

### Runtime Validation

Templates are validated when rules are saved:

- **Syntax errors** are caught during rule creation
- **Runtime errors** are tested with sample objects
- **Missing filters** for A/AAAA records are detected

### Testing Templates

**Recommended Approach**:

1. Create rule with simple templates first
2. Test with representative objects
3. Add complexity incrementally
4. Monitor DNS record creation logs

## Common Template Errors

### Missing IP Address Filter

**Problem**:
```jinja2
Value Template: {{ obj.primary_ip4 }}  # Missing | ip_address filter
```

**Solution**:
```jinja2
Value Template: {{ obj.primary_ip4 | ip_address }}
```

### Undefined Variables

**Problem**:
```jinja2
{{ obj.nonexistent_field }}  # Field doesn't exist
```

**Solution**:
```jinja2
{{ obj.nonexistent_field | default('fallback-value') }}
```

### Missing Related Objects

**Problem**:
```jinja2
{{ obj.primary_ip4.address }}  # When primary_ip4 is None
```

**Solution**:
```jinja2
{% if obj.primary_ip4 %}{{ obj.primary_ip4 | ip_address }}{% endif %}
```

## Performance Considerations

### Template Complexity
- Keep templates simple for better performance
- Avoid complex loops or heavy computation
- Use efficient Django ORM patterns

### Filter Usage
- Always use `| ip_address` for A/AAAA records (required)
- Use `| dns_normalize` for names (recommended)
- Minimize custom filter chains

### Object Relationships
- Leverage existing Django relationships
- Avoid deep nested traversals when possible
- Consider database query impact of template logic. For single changes it's not generally noticable but it can become so when more sweeping updates are made (e.g. assigning IPs to hundreds of interfaces)

## Best Practices

### Template Design
1. **Start simple**: Basic templates first, add complexity later
2. **Use filters**: Always apply appropriate filters (`dns_normalize`, `ip_address`)
3. **Handle missing data**: Include conditional logic for optional fields
4. **Test thoroughly**: Validate templates with real objects before deployment

### Rule Organization  
1. **Descriptive names**: Include content type and scope in rule names
2. **Logical grouping**: Group related rules by purpose or location
3. **Documentation**: Use description field to explain complex template logic

### Location Strategy
1. **Global first**: Start with global rules for organization-wide standards
2. **Selective scoping**: Add location scoping only when needed for different behavior
3. **Hierarchy awareness**: Consider parent/child location relationships
