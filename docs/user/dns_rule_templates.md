# DNS Rule Template Reference

DNS Rules use Jinja2 templates to dynamically generate DNS record content based on Nautobot object data. This guide provides comprehensive template syntax, filters, and examples for creating effective DNS automation rules.

!!! note "Development Status"
    Template filters may change before final release.

## Template Context

All templates have access to the triggering object as `obj` and can traverse Django ORM relationships:

### `Interface` Examples
```jinja2
{{ obj.name }}                    # Object name
{{ obj.device.name }}             # Related device name
{{ obj.device.location.name }}    # Device location name
```

### `Device` Examples
```jinja
{{ obj.primary_ip4.address }}     # Primary IP address object (e.g. for devices)
```

### Service Object Examples

Service objects provide access to their parent (device or virtual machine) and service-specific fields:

```jinja2
# Service basic fields
{{ obj.name }}                    # Service name
{{ obj.protocol }}                # Service protocol (HTTP, SSH, etc.)
{{ obj.ports }}                   # List of port numbers

# Device-attached service
{{ obj.device.name }}             # Parent device name
{{ obj.device.location.name }}    # Device location

# VM-attached service  
{{ obj.virtual_machine.name }}    # Parent VM name
{{ obj.virtual_machine.cluster.location.name }}  # VM cluster location
{{ obj.virtual_machine.tenant.name }}            # VM tenant
{{ obj.virtual_machine.cluster.tenant.name }}    # VM cluster tenant (fallback)
```

## Required Templates

Every DNS rule must define these core templates:

- **Zone Template**: Determines which DNS zone contains the record
- **Name Template**: The record name within the zone  
- **Value Template**: The primary record value

## Template Filters

### IP Address Filter

**Purpose**: Convert IP address objects to DNS record values for A/AAAA records.

**Usage**:

- `{{ obj.primary_ip4 }}` - Creates 1 A record
- `{{ obj.ip_addresses.all() }}` - Creates 1 record per IP address  
- `{{ obj.ip_addresses.first() }}` - Creates 1 record from first IP
- `{{ obj.ip_addresses.filter(role="primary") }}` - Creates 1 record per filtered IP


## Template Patterns

### Device Templates

**Basic Device A Record**:
```jinja2
Zone Template: example.com
Name Template: {{ obj.name }}
Value Template: {{ obj.primary_ip4 }}
```

**Location-Aware Device Record**:
```jinja2
Zone Template: {{ obj.location.name | lower }}.example.com
Name Template: {{ obj.name }}
Value Template: {{ obj.primary_ip4 }}
```

### Interface Templates

**Interface A Records or AAAA (Multi-IP)**:
```jinja2
Zone Template: example.com
Name Template: {{ obj.name }}.{{ obj.device.name }}
Value Template: {{ obj.ip_addresses.all() }}
```

### Service Templates

**Basic Service A or AAAA Record**:
```jinja2
Zone Template: services.example.com
Name Template: {{ obj.name }}
Value Template: {{ obj.ip_addresses.all() }}
```

**Service with Parent Context**:
```jinja2
# Device-attached service
Zone Template: {{ obj.device.location.name | lower }}.example.com
Name Template: {{ obj.name }}.{{ obj.device.name }}
Value Template: {{ obj.ip_addresses.all() }}

# VM-attached service  
Zone Template: {{ obj.virtual_machine.cluster.location.name | lower }}.example.com
Name Template: {{ obj.name }}.{{ obj.virtual_machine.name }}
Value Template: {{ obj.ip_addresses.all() }}
```

**Conditional Service Templates**:
```jinja2
# Handle both device and VM-attached services
Zone Template: {% if obj.device %}{{ obj.device.location.name }}{% else %}{{ obj.virtual_machine.cluster.location.name }}{% endif %}.example.com
Name Template: {{ obj.name }}
Value Template: {{ obj.ip_addresses.all() }}
```

## Advanced Template Techniques

### Conditional Logic

**Handle Optional Fields**:
```jinja2
{% if obj.primary_ip4 %}
{{ obj.primary_ip4 }}
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
{{ obj.name }}.{{ obj.device.rack.name }}.{{ obj.device.location.name }}
```

**Role-Based Names**:
```jinja2
{% if obj.device.role.name == "Web Server" %}
web-{{ obj.name }}
{% elif obj.device.role.name == "Database" %}
db-{{ obj.name }}
{% else %}
{{ obj.name }}
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
The rendering engine expects a Nautobot `IPAddress` object, so referencing the `.address` attribute, which isn't an `IPAddress` object, will do no good. Use this:

```jinja2
{{ obj.primary_ip4 }}
```

...and one of two things will happen. Either an `IPAddress` in the `.primary_ip4` field or it isn't. If it is, the template render will complete successfully and a DNS record will be created. If there's `.primary_ip4` is not set, the template render will fail and no DNS record will be created.

## Performance Considerations

### Template Complexity
- Keep templates simple for better performance
- Avoid complex loops or heavy computation
- Use efficient Django ORM patterns

### Object Relationships
- Leverage existing Django relationships
- Avoid deep nested traversals when possible
- Consider database query impact of template logic. For single changes it's not generally noticable but it can become so when more sweeping updates are made (e.g. assigning IPs to hundreds of interfaces)

## Best Practices

### Template Design
1. **Start simple**: Basic templates first, add complexity later
2. **Handle missing data**: Include conditional logic for optional fields
3. **Test thoroughly**: Validate templates with real objects before deployment

### Rule Organization  
1. **Descriptive names**: Include content type and scope in rule names
2. **Logical grouping**: Group related rules by purpose or location
3. **Documentation**: Use description field to explain complex template logic

### Location Strategy
1. **Global first**: Start with global rules for organization-wide standards
2. **Selective scoping**: Add location scoping only when needed for different behavior
3. **Hierarchy awareness**: Consider parent/child location relationships
