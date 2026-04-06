# DNS Rule Template Reference

DNS rule templates use Jinja2 to render record names, values, views, and zones from Nautobot objects. This page is organized by DNS Rule field. For concrete recipes and patterns, see [DNS Rule Template Patterns](dns_rule_template_patterns.md).

## Template Context

All templates render with `obj` in context.

### Shared `obj` Context

- `obj` is the source object being evaluated (for example `Device`, `Interface`, `Service`, `VirtualMachine`, `VMInterface`).
- You can reference related attributes directly, for example:
  - `{{ obj.name }}`
  - `{{ obj.device.name }}`
  - `{{ obj.parent.name }}`
  - `{{ obj.virtual_machine.cluster.name }}`

### Interfaces (device-backed and module-backed) {#interfaces-topologies}

`Interface` objects may be attached to a `Device` or a `Module`. `obj.device` is set for device-backed interfaces and is `None` for module-backed interfaces. Templates that assume `obj.device` is always present can fail for module-backed interfaces.

Use `obj.parent` when you need a single traversal path across both topologies (for example `{{ obj.parent.name }}` for a parent name, or when walking toward a `Device` for location or tenant fields). For how location and tenant affect which rule applies, see [DNS Rules](dns_rules.md).

### Per-candidate `ip` Context (A/AAAA)

In addition to the `obj` context object, the `view_template` and `zone_template` for A/AAAA records also have access to an `ip` object in context representing the specific `IPAddress` candidate being processed for that record. This allows view and zone selection to vary per IP rather than per object.

| Attribute | Description |
| --- | --- |
| `ip.parent` | Parent `Prefix` containing this IP |
| `ip.parent.prefix` | Network address of the parent prefix (e.g. `10.0.0.0/8`) |
| `ip.parent.tenant` | Tenant assigned to the parent prefix; may be unset |
| `ip.parent.cf.<key>` | Custom field on the parent prefix |
| `ip.get_computed_fields()["<key>"]` | Computed field on the `IPAddress` |

See [DNS Rule Template Patterns](dns_rule_template_patterns.md#dns-view-selection-by-ip) for usage examples.

## Template Syntax

### `name_template`

`name_template` defines the rendered DNS record name.

| Template | Description |
| --- | --- |
| `{{ obj.name }}` | Interface or object name |
| `{{ obj.name }}-{{ obj.parent.name }}` | Interface + owning parent (device-backed and module-backed interfaces) |
| `{{ obj.name }}-{{ obj.device.name }}` | Interface + device (device-backed interfaces only; see [topology note](#interfaces-topologies)) |
| `{{ obj.name }}-{{ obj.virtual_machine.name }}` | VM interface + VM |

Rendered names may be [normalized](../../admin/install.md#normalize_dns_records) before being saved.

### `value_template`

`value_template` provides the primary record value payload for the selected `record_type`. For A/AAAA rules, `value_template` should evaluate to one or more IP addresses.

| Template | Description |
| --- | --- |
| `{{ obj.primary_ip4 }}` | Device primary IPv4 |
| `{{ obj.ip_addresses.first() }}` | First IP on the object |
| `{{ obj.ip_addresses.all() }}` | All IPs on the object |

!!! warning "Do not access IP string attributes"
    Do not use `.address`, `.host`, or similar on IP objects in `DNSRule` templates — these attributes will not behave as expected. Reference the IP object directly.

`{{ obj.ip_addresses.all() }}` is safe to use for A or AAAA rules even when an interface has both IPv4 and IPv6 addresses - the engine will only use addresses that are compatible with the rule's record type.

If the template evaluates to no IP addresses, no record is created for that object - this is not an error.

!!! tip "Template performance: `filter()` / `exclude()` on `ip_addresses`"
    In rule templates, calling `obj.ip_addresses.filter(...)` or `obj.ip_addresses.exclude(...)` may issue additional database queries per object.
    On large cascade updates (for example, many interfaces on one device), this can significantly increase SQL volume.

    Prefer `obj.ip_addresses.all()` or `first()`/`last()` where possible. Use `filter()`/`exclude()` only when needed and expect higher query cost.

### `zone_template`

`zone_template` must render a DNS zone name.

| Template | Description |
| --- | --- |
| `example.com` | Static zone |
| `{{ obj.location.name }}.example.com` | Object-derived zone (for example a `Device`) |
| `{{ obj.device.location.name }}.example.com` | Interface zone via device (device-backed interfaces only; see [topology note](#interfaces-topologies)) |
| `{{ obj.location.cf.dns_zone }}` | From a "DNS Zone" [`CustomField`](https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/customfield/) on the object's location |

For A/AAAA rules, `zone_template` may also use per-candidate `ip` context when needed.

### `view_template` (Optional)

If blank, the default DNS view is used.

When provided, `view_template` should render one or more DNS view names (comma/space delimited).

| Template | Description |
| --- | --- |
| `Internal` | Static view |
| `{{ "RestrictedView" if obj.name.startswith("edge-") else "InternalView" }}` | Conditional view based on object name |

For A/AAAA rules, `view_template` can use per-candidate `ip` context for IP-aware view selection.

## Required vs Optional Fields

Required:

- `zone_template`
- `name_template`
- `value_template`

Optional:

- `view_template`

## Valid Template Forms

Each field must be either:

- Plain literal (no Jinja delimiters), or
- A template including at least one `{{ ... }}` expression.

If a field uses Jinja statements (`{% ... %}`) or comments (`{# ... #}`), it must still include at least one `{{ ... }}` expression.

Plain literal values are validated for DNS safety constraints when the rule is saved. Syntax errors and statement/comment-only fields (no `{{ ... }}`) are also rejected when the rule is saved.

## Best Practices

- Keep templates as short as possible; complex templates can increase processing time significantly for large batches.
- Prefer shallow attribute paths over deep traversals.

## Related Documentation

- [DNS Rule Template Patterns](dns_rule_template_patterns.md)
- [DNS Rules](dns_rules.md)
- [DNS Reconciliation Jobs](reconciliation_jobs.md)
