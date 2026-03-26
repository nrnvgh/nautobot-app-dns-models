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

**Per-record-type independence**: Different record types can use different rule sources, enabling mixed scenarios like location-specific A records + tenant-specific AAAA records for the same object.

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
   - **Location**: Leave blank for non-location-scoped rules, or select a location for location-scoped rules
   - **Tenant**: Leave blank for non-tenant-scoped rules, or select a tenant for tenant-scoped rules
   - **Record Type**: Type of DNS record to create (A, AAAA)
4. **Define** Jinja2 templates:
   - **Name Template**: The record name within the zone
   - **Value Template**: The record value (IP address, hostname, etc.)
   - **View Template**: Optional DNS view selector template (leave blank to use `Default`)
   - **Zone Template**: Which DNS zone to create records in

### Template Field Behavior

Templates use Jinja2 syntax, and all template fields have access to `obj` (the source object). Rule processing has two phases: object-level rendering and per-candidate rendering. For full template syntax, object context, per-candidate context, filters, patterns, and troubleshooting, see `dns_rule_templates.md`.

#### Valid template forms

Each template field must be either a **plain literal** (no Jinja2 delimiters) or a template that includes at least one **expression** (`{{ ... }}`).

- **Plain literal**: A string with no `{{`, `{%`, or `{#` is used as-is (for example, `Default`, `example.com`). This is the most efficient form for static values.
- **Template with expression**: If the field contains Jinja2 control tags (`{% ... %}`) or comments (`{# ... #}`), it must also contain at least one `{{ ... }}` expression. Saving a rule whose template has only `{%` and/or `{#` (and no `{{`) will raise a validation error: *"Template uses Jinja control or comment tags but has no {{ expression. Use a plain literal or add at least one {{ ... }} expression."*

This rule avoids ambiguous cases where a template would be interpreted differently by the engine (for example, `{# comment #}Default` renders to `Default` in Jinja2 but would otherwise be treated as a literal string).

For **name_template** and **value_template**, using Jinja expressions (for example `{{ obj.name }}`, `{{ obj.primary_ip4 }}`) is nearly always the right approach, so that record names and values vary per source object. Plain literals are valid for all fields but, if used at all, are generally only recommended for view/zone (e.g. `Default`, `example.com`); static name or value is only for special cases.

#### Evaluation Order

Rule processing follows this order:

1. `name_template` (object-level)
2. `value_template` (object-level render, then candidate expansion)
3. `view_template` (per-candidate view selection)
4. `zone_template` (per-candidate zone lookup within selected view(s))

#### Name Template

`name_template` defines the DNS record name. It is evaluated once per source object and reused for each candidate generated from that object.

#### Value Template

`value_template` defines record data values and can expand into multiple candidates. This is the main source of one-to-many record generation for a single object.
- May expand to multiple candidate records (for example, one candidate per IP from `{{ obj.ip_addresses.all() }}`).

#### View Template

`view_template` selects target DNS view(s) for each candidate. If unset, the engine uses `Default`; if set, rendered names must resolve to existing views.

- Optional field that selects one or more DNS views for each candidate.
- Blank `view_template` -> use `Default`.
- Rendered view names are matched case-sensitively.
- Multiple names are supported with comma and/or whitespace separators.
- Configured `view_template` that renders empty -> candidate is skipped (best-effort).
- Unknown rendered view name(s) -> candidate is skipped (best-effort).

#### Zone Template

`zone_template` resolves the zone after view selection. Zone lookup is constrained to the selected view(s) for that candidate.
- If no matching zone exists in selected view(s), the candidate is skipped (best-effort).

#### Best-Effort Reconciliation Behavior

Best-effort processing applies to both create and update reconciliation paths.

- **Mixed update outcome**: if some candidates still render/resolve and others fail (for example, empty `view_template`, unknown view name, or zone missing in selected view), the valid candidates are kept/created and only failed candidates are removed or skipped.
- **DNS records removed during reconciliation**: if a later update to the source object or related template context data causes candidate failures, failed candidates are reconciled away; if all candidates fail, previously created DNS records for that rule/object are cleaned up and their tracking rows are removed.

##### When reconciliation runs

Candidate cleanup happens when rule processing runs again for the source object and enters update reconciliation.

Typical triggers include:

- Saving supported source objects (for example: `Device`, `Interface`, `Service`)
- IP assignment relationship changes (add/remove/clear operations)
- Explicit/manual processing calls

Important caveat:

- Some related data changes used by templates do not emit source-object rule-processing signals (for example, certain Prefix/Zone/View/relationship context changes). In those cases, stale records can remain until a later object trigger, manual processing, or a reconciliation job runs.

##### Reconciliation job workflows

Use reconciliation jobs when you need to repair drift, or to create rule-driven records for objects that already existed before a new rule was introduced (bulk or per-object runs). Supported source objects (`Device`, `Interface`, `Service`, `VirtualMachine`, `VMInterface`) can open **Reconcile DNS Records (Object)** from detail views when rules are in scope; bulk runs use **Reconcile DNS Records (Bulk)** under **Jobs**. Parameters, result payload, class paths for the API, and log output are documented in [Reconciliation jobs](reconciliation_jobs.md).

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

## Rule Management

### Enabling and Disabling Rules

- **Disable** rules to stop automatic DNS record creation without deleting the rule
- **Enable** rules to resume automatic processing
- Existing DNS records remain when rules are disabled

### Rule Conflicts

The system prevents conflicting rules:

- Only one enabled rule per `(content_type, record_type, location, tenant)` scope combination
- Rules in different scopes can coexist for the same content type and record type (for example, global + location-scoped, or location-scoped + tenant-scoped)
- A rule with tenant set and tenant unset are different scopes; conflicts are checked within the exact scope
- Different record types (A, AAAA) can have separate rules

### Location Changes

When objects move between locations:

- Location-specific rules may stop applying
- New location-specific rules may start applying  
- Global rules continue to apply regardless of location
- DNS records are automatically updated to reflect the change

### Tenant Changes

When objects change tenants:

- Tenant-specific rules may stop applying
- New tenant-specific rules may start applying
- Global rules continue to apply regardless of tenant
- DNS records are automatically updated to reflect the change

## Troubleshooting

### What "candidate records" means

A candidate record is an intermediate DNS record item produced from a rule/object evaluation before final DNS create/update/delete operations are applied.

Examples:

- Interface rule with `{{ obj.ip_addresses.all() }}`: one candidate per interface IP
- Service rule with multiple IPs: one candidate per service IP
- Any template expansion that yields multiple values: one candidate per value

Each candidate is processed independently for template rendering and zone/view resolution.

### Rules Not Creating Records

**Check**:

1. Rule is **enabled**
2. Content type matches your objects (e.g. dcim.interface)
3. Location scoping is appropriate (global vs location-specific)
4. Templates render successfully
5. Required IP addresses exist for A/AAAA records

### Template Errors

**Common Issues**:

- **Template uses Jinja control or comment tags but has no {{ expression**: You used `{%` and/or `{#` in a template field without any `{{ ... }}` expression. Use a plain literal (e.g. `Default`, `example.com`) for static values, or add at least one expression (e.g. `{{ obj.name }}`) when using control flow or comments.
- Missing IP addresses: `{{ obj.primary_ip4  }}` when device has no primary IP
- Invalid object references: `{{ obj.nonexistent_field }}`

**Resolution**:

- Test templates with representative objects before deployment

### DNS records were removed

If records previously existed and later disappeared, most commonly:

1. A later reconciliation run determined one or more candidates no longer rendered/resolved successfully (see "Best-Effort Reconciliation Behavior")
2. Rule scope applicability changed (for example, location or tenant changed), so the old rule no longer applies
3. A rule was disabled or changed, and a later object-triggered reconciliation removed records that were no longer desired
4. Related context data used by templates changed (for example, view/zone/prefix/relationship data), changing rendered outcomes

### Some DNS records are not being created

If A records are being created for v4 addresses and AAAA records are not being created for v6 addresses (or vice-versa), ensure you have DNS Rules for both A and AAAA.

Rule execution is best-effort per candidate record. If one candidate fails template/render/view/zone resolution, other valid candidates from the same rule can still be created. Check warning logs for skipped candidates and failure reasons.

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
