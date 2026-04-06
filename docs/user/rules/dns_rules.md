# Automated DNS Record Management

DNS Rules provide automated DNS management of A and AAAA records and can replace manual record lifecycle work with template-driven behavior. When DNS Rules are applied to source objects, corresponding DNS records are created, updated, or deleted as necessary.

## Key Concepts

### Rule Scoping

Rules can be:

- **Global**: applies to all objects of the selected content type.
- **Location-scoped**: applies only to objects resolved to that location.
- **Tenant-scoped**: applies only to objects resolved to that tenant.
- **Location+Tenant-scoped**: applies only when both match.

### Rule Precedence

When multiple rules could match the same object and record type, precedence is location-first:

1. Location+Tenant
2. Location
3. Tenant
4. Global

Per-record-type behavior is independent. For example, A and AAAA can resolve from different winning rules.

### Multi-Record Support

A single rule can produce multiple records, for example:

- `{{ obj.ip_addresses.all() }}` creates one candidate per IP.
- A multi-IP interface or service can produce multiple A/AAAA records.

## Creating DNS Rules

### Basic Workflow

1. Navigate to **DNS > DNS Rules**.
2. Click **Add DNS Rule**.
3. Configure name, content type, optional scope, and record type.
4. Define templates:
   - `name_template`
   - `value_template`
   - `view_template` (optional; blank uses `Default`)
   - `zone_template`

### Template Field Behavior

All template fields have access to `obj` (the source object). Rule processing uses object-level rendering and per-candidate rendering.

For template syntax and object context see [DNS Rule Templates](dns_rule_templates.md); for concrete recipes and patterns see [DNS Rule Template Patterns](dns_rule_template_patterns.md).

For valid template forms see [DNS Rule Templates](dns_rule_templates.md#valid-template-forms).

#### Evaluation Order

Rule processing evaluates fields in this order:

1. `name_template` (object-level)
2. `value_template` (object-level, then candidate expansion)
3. `view_template` (per-candidate view selection)
4. `zone_template` (per-candidate zone lookup in selected views)

#### Best-Effort Reconciliation

Processing is best effort in both create and update paths:

- Valid candidates continue even if other candidates fail.
- Failed candidates are skipped or reconciled away.
- If all candidates fail during update reconciliation, previously managed records for that rule/object can be removed. ## FIXME this probably needs to be reworded

When related context changes do not trigger source-object signals, run reconciliation jobs to repair drift. See [DNS Reconciliation Jobs](reconciliation_jobs.md).

## Common Rule Outcomes

### Scope and Precedence Matrix

| Scenario | Matching rules present | Winning rule | Fallback path |
| --- | --- | --- | --- |
| Global only | Global | Global | None |
| Location-specific deployment | Global + Location | Location (in-scope objects) | Global |
| Tenant-specific deployment | Global + Tenant | Tenant (in-scope objects) | Global |
| Full scoped deployment | Global + Location + Tenant + Location+Tenant | Location+Tenant (exact match) | Location -> Tenant -> Global |

### End-to-End Scope Examples

#### Example Rule Set

All examples below assume these enabled A-record rules for `dcim.device`:

| Rule name | Scope | Zone template | Name template |
| --- | --- | --- | --- |
| `device-a-global` | Global | `global.example.com` | `{{ obj.name }}` |
| `device-a-nyc` | Location = `NYC` | `nyc.example.com` | `{{ obj.name }}` |
| `device-a-acme` | Tenant = `ACME Corp` | `acme.example.com` | `{{ obj.name }}` |
| `device-a-acme-nyc` | Location = `NYC`, Tenant = `ACME Corp` | `acme-nyc.example.com` | `{{ obj.name }}` |

#### Example Objects and Winning Rule

| Object | Resolved location | Resolved tenant | Winning rule name | Winning zone | Why |
| --- | --- | --- | --- | --- | --- |
| `edge-01` | `SFO` | `Globex` | `device-a-global` | `global.example.com` | Only global rule matches. |
| `spine-05` | `NYC` | *(unset)* | `device-a-nyc` | `nyc.example.com` | Location rule matches; tenant-scoped rules do not apply when tenant is unset. |
| `leaf-02` | `NYC` | `Globex` | `device-a-nyc` | `nyc.example.com` | Location rule matches; no location+tenant match. |
| `web-03` | `SFO` | `ACME Corp` | `device-a-acme` | `acme.example.com` | Tenant rule matches; no location+tenant match. |
| `api-04` | `NYC` | `ACME Corp` | `device-a-acme-nyc` | `acme-nyc.example.com` | Most-specific location+tenant rule matches. |

This shows the full fallback chain in practice: `Location+Tenant -> Location -> Tenant -> Global`.

## Rule Management

### Enabling and Disabling

- Disable to stop automatic processing without deleting the rule.
- Re-enable to resume processing.

While a rule is disabled, existing records created by it will not be updated, nor will new records be created by it.

### Conflicts

The system prevents conflicting enabled rules in the same `(content_type, record_type, location, tenant)` scope tuple.

### Location or Tenant Changes

When source objects change location or tenant:

- Previously matching scoped rules can stop applying.
- New scoped rules can begin applying.
- Global rules remain eligible.
- Reconciliation updates records to the new desired state when processing runs.

## Troubleshooting

### Rules Not Creating Records

Check:

1. Rule is enabled.
2. Content type matches the source objects.
3. Scope (location/tenant) is correct.
4. Templates render successfully.
5. Required data exists (for example IPs for A/AAAA records).

### Records Were Removed

Common causes:

1. Candidate rendering or resolution started failing.
2. Scope applicability changed.
3. Rule changed or was disabled.
4. Related context data changed and later reconciliation removed obsolete records.