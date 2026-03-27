# DNS Rule Template Reference

DNS rule templates use Jinja2 to render record names, values, views, and zones from Nautobot objects.

## Template Context

All fields render with `obj` in context.

### `Interface` Examples

| Template | Description |
| --- | --- |
| `{{ obj.name }}` | Interface name |
| `{{ obj.device.name }}` | Related device name |
| `{{ obj.parent.name }}` | Owning device name across device-backed and module-backed interface topologies |
| `{{ obj.device.location.name }}` | Device location name |
| `{{ obj.ip_addresses.first() }}` | First IP address on the interface |
| `{{ obj.ip_addresses.all() }}` | All IP addresses on the interface |

!!! note
    `Interface` objects may be attached to a `Device` or a `Module`. `obj.device` is set for device-backed interfaces and is `None` for module-backed interfaces. To handle both topologies consistently in interface templates, use `obj.parent` as the stable parent reference.

    For location/tenant scope resolution semantics, see [DNS Rules](dns_rules.md).

### `Device` Examples

| Template | Description |
| --- | --- |
| `{{ obj.name }}` | Device name |
| `{{ obj.primary_ip4 }}` | Primary IPv4 address object |

### `Service` Examples

| Template | Description |
| --- | --- |
| `{{ obj.name }}` | Service name |
| `{{ obj.protocol }}` | Service protocol |
| `{{ obj.ports }}` | Service port list |
| `{{ obj.device.name }}` | Parent device name (device-attached service) |
| `{{ obj.device.location.name }}` | Device location (device-attached service) |
| `{{ obj.virtual_machine.name }}` | Parent virtual machine name (VM-attached service) |
| `{{ obj.virtual_machine.cluster.location.name }}` | VM cluster location (VM-attached service) |
| `{{ obj.virtual_machine.tenant.name }}` | VM tenant (VM-attached service) |
| `{{ obj.virtual_machine.cluster.tenant.name }}` | Cluster tenant fallback (VM-attached service) |
| `{{ obj.ip_addresses.first() }}` | First IP address on the service |
| `{{ obj.ip_addresses.all() }}` | All IP addresses on the service |

### `VirtualMachine` Examples

| Template | Description |
| --- | --- |
| `{{ obj.name }}` | Virtual machine name |
| `{{ obj.cluster.name }}` | Cluster name |
| `{{ obj.location.name }}` | VM location (resolved via cluster location) |
| `{{ obj.tenant.name }}` | VM tenant |
| `{{ obj.cluster.tenant.name }}` | Cluster tenant fallback |
| `{{ obj.primary_ip4 }}` | Primary IPv4 address object |

### `VMInterface` Examples

| Template | Description |
| --- | --- |
| `{{ obj.name }}` | VM interface name |
| `{{ obj.virtual_machine.name }}` | Parent virtual machine name |
| `{{ obj.virtual_machine.cluster.name }}` | Parent cluster name |
| `{{ obj.virtual_machine.location.name }}` | Parent VM location (resolved via cluster location) |
| `{{ obj.ip_addresses.first() }}` | First IP address on the VM interface |
| `{{ obj.ip_addresses.all() }}` | All IP addresses on the VM interface |

## Required Templates

Every DNS Rule requires:

- `zone_template`
- `name_template`
- `value_template`

Optional:

- `view_template`

## Valid Template Forms

Each field must be either:

- **Plain literal**: no Jinja delimiters.
- **Template with expression**: at least one `{{ ... }}` expression.

If a field uses Jinja statements (`{% ... %}`) or comments (`{# ... #}`), it must still include at least one `{{ ... }}` expression.

## Pattern Cookbook

For concrete patterns (basic records, conditional templates, DNS view selection, troubleshooting, and performance guidance), see [DNS Rule Template Patterns](dns_rule_template_patterns.md).

## Related Documentation

- [DNS Rules](dns_rules.md)
- [DNS Reconciliation Jobs](reconciliation_jobs.md)
