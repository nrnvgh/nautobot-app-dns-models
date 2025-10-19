# Automated DNS Record Management

DNS Rules provide automated DNS record creation, updating, and deletion based on changes to Nautobot objects. When objects like devices or interfaces are created, modified, or deleted, DNS rules automatically manage corresponding DNS records using Jinja2 templates.

## Overview

DNS Rules eliminate the need to manually create and maintain DNS records for infrastructure objects. Instead, you define template-based rules that automatically:

- **Create** DNS records when new objects are added
- **Update** DNS records when objects are modified  
- **Delete** DNS records when objects are removed or no longer match rule criteria

## Key Concepts

### Rule Scoping

DNS rules can be **global**, **location-scoped**, **tenant-scoped**, or **location+tenant-scoped**:

- **Global Rules**: Apply to all objects of the specified type, regardless of location or tenant
- **Location-Scoped Rules**: Apply only to objects in specific locations (any tenant)
- **Tenant-Scoped Rules**: Apply only to objects owned by specific tenants (any location)  
- **Location+Tenant-Scoped Rules**: Apply only to objects in specific locations AND owned by specific tenants

### Rule Precedence

When multiple rules exist for the same content type and record type, the system uses **location-first precedence**:

1. **Location+Tenant specific** - Most specific (both location AND tenant match)
2. **Location specific** - Location-wide policy (any tenant in that location)
3. **Tenant specific** - Tenant-wide policy (any location for that tenant)
4. **Global** - Organization-wide policy (any location, any tenant)

**Per-record-type independence**: Different record types can use different rule sources, enabling mixed scenarios like location-specific A records + tenant-specific CNAME records for the same object.

### Multi-Record Support

A single rule can create multiple DNS records:

- Interface with multiple IP addresses → multiple A records
- Template filters like `{{ obj.ip_addresses.all() }}` create one record per IP

## Creating DNS Rules

### Basic Workflow

1. **Navigate** to DNS → DNS Rules in the Nautobot interface
2. **Click** "Add DNS Rule" 
3. **Configure** the rule parameters:
   - **Name**: Unique identifier for the rule
   - **Content Type**: What type of object triggers this rule (Device, Interface, etc.)
   - **Location**: Leave blank for global, or select specific location for scoped rules
   - **Record Type**: Type of DNS record to create (A, AAAA, CNAME, MX, etc.)
4. **Define** Jinja2 templates:
   - **Zone Template**: Which DNS zone to create records in
   - **Name Template**: The record name within the zone
   - **Value Template**: The record value (IP address, hostname, etc.)
   - **Additional Templates**: Record-specific fields (MX preference, SRV priority/weight/port)

### Template Syntax

Templates use Jinja2 syntax with access to the triggering object as `obj`:

- **Basic fields**: `{{ obj.name }}`, `{{ obj.description }}`
- **Related objects**: `{{ obj.device.name }}`, `{{ obj.device.location.name }}`

## Common Use Cases

### Device DNS Records

**Scenario**: Automatically create A records for all devices using their primary IP.

**Rule Configuration**:

- Content Type: `dcim | device`
- Location: (blank for global)
- Record Type: A Record
- Zone Template: `example.com`
- Name Template: `{{ obj.name }}`
- Value Template: `{{ obj.primary_ip4 }}`

**Result**: Device "web-server-01" with IP 192.168.1.100 creates:
```
# Zone: example.com
web-server-01    IN A    192.168.1.100
```

### Location-Specific Naming

**Scenario**: Different DNS naming schemes for different datacenters.

**Global Rule** (fallback for all locations):

- Zone Template: `example.com`
- Name Template: `{{ obj.name }}`

**Location Rule** (London datacenter only):

- Location: London-Datacenter
- Zone Template: `london.example.com`
- Name Template: `{{ obj.name }}.lon`

**Result**: 

- London devices get `device.lon.london.example.com`
- All other devices get `device.example.com`

### Tenant-Specific Naming

**Scenario**: Different DNS zones for different customer tenants.

**Global Rule** (fallback for all tenants):

- Zone Template: `internal.example.com`
- Name Template: `{{ obj.name }}`

**Tenant Rule** (ACME Corp tenant only):

- Tenant: ACME Corp
- Zone Template: `acme.example.com`
- Name Template: `{{ obj.name }}.acme`

**Result**:

- ACME Corp devices get `device.acme.acme.example.com`
- All other devices get `device.internal.example.com`

### Combined Location+Tenant Scoping

**Scenario**: Specific naming for tenant devices in specific locations.

**Location+Tenant Rule** (ACME Corp devices in NYC only):

- Location: NYC-Datacenter
- Tenant: ACME Corp
- Zone Template: `acme-nyc.example.com`
- Name Template: `{{ obj.name }}`

**Precedence Result**:

- ACME Corp devices in NYC get the location+tenant rule (most specific)
- ACME Corp devices elsewhere get tenant-only rule
- Non-ACME devices in NYC get location-only rule
- All others get global rule

### Interface Multi-IP Records

**Scenario**: Create A records for all IP addresses on network interfaces.

**Rule Configuration**:

- Content Type: `dcim | interface`
- Value Template: `{{ obj.ip_addresses.all() }}`

**Result**: Interface with 3 IP addresses creates 3 separate A records.

### Service DNS Records

**Scenario**: Automatically create DNS records for services (load balancers, web services, databases).

#### Service A Records

**Rule Configuration**:

- Content Type: `ipam | service`
- Location: (blank for global)
- Record Type: A Record
- Zone Template: `services.example.com`
- Name Template: `{{ obj.name }}`
- Value Template: `{{ obj.ip_addresses.all() }}`

**Result**: Service "web-lb" with IPs 10.1.1.100 and 10.1.1.101 creates:
```
# Zone: services.example.com
web-lb    IN A    10.1.1.100
web-lb    IN A    10.1.1.101
```

#### Service Location and Tenant Inheritance

Services inherit location and tenant from their parent object:

- **Device-attached Service**: Inherits `device.location` and `device.tenant`
- **VM-attached Service**: Inherits `virtual_machine.location` (from cluster) and `virtual_machine.tenant` (with `cluster.tenant` fallback)

**Example**: Service attached to VM in "ACME Corp" tenant with cluster in "London" location will match:
- Location+Tenant rules for London + ACME Corp (highest precedence)
- Location rules for London (if no location+tenant rule)
- Tenant rules for ACME Corp (if no location rule)
- Global rules (lowest precedence)

## Template Filters

### IP Address Filter

Convert IP address objects to UUIDs for A/AAAA record values:

- **Single IP**: `{{ obj.primary_ip4 }}`
- **Multiple IPs**: `{{ obj.ip_addresses.all() }}`
- **Filtered IPs**: `{{ obj.ip_addresses.filter(role="primary") }}`

### DNS Normalize Filter

Ensure DNS-compliant names:

- **Basic**: `{{ obj.name | dns_normalize }}` 
- **Effect**: Converts spaces to hyphens, lowercases text, removes invalid characters

## Rule Management

### Enabling and Disabling Rules

- **Disable** rules to stop automatic DNS record creation without deleting the rule
- **Enable** rules to resume automatic processing
- Existing DNS records remain when rules are disabled

### Rule Conflicts

The system prevents conflicting rules:

- Only one enabled rule per `(content_type, record_type, location)` combination
- Global and location-scoped rules can coexist for the same content type and record type
- Different record types (A, CNAME, MX) can have separate rules

### Location Changes

When objects move between locations:

- Location-specific rules may stop applying
- New location-specific rules may start applying  
- Global rules continue to apply regardless of location
- DNS records are automatically updated to reflect the change

## Troubleshooting

### Rules Not Creating Records

**Check**:

1. Rule is **enabled**
2. Content type matches your objects
3. Location scoping is appropriate (global vs location-specific)
4. Templates render successfully
5. Required IP addresses exist for A/AAAA records

### Template Errors

**Common Issues**:

- Missing IP addresses: `{{ obj.primary_ip4  }}` when device has no primary IP
- Invalid object references: `{{ obj.nonexistent_field }}`

**Resolution**:

- Test templates with representative objects before deployment

## Best Practices

### Start Simple

- Begin with global rules before adding location scoping
- Test with a single object type before expanding
- Use basic templates before adding complex logic

### Template Design

- Include conditional logic for optional fields

### Rule Organization

- Use descriptive rule names that indicate scope and purpose
- Group related rules by content type or location
- Document complex template logic in rule descriptions

### Location Strategy

- Use global rules for organization-wide naming standards
- Use location-scoped rules for datacenter-specific requirements
- Consider location hierarchy when designing rule scopes
