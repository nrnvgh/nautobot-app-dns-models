# DNS Rule Template Patterns

Template patterns and troubleshooting examples for DNS Rule fields.

## Template Patterns

### Device Templates

#### Device A Record

**Zone template**
```jinja2
example.com
```

**Name template**
```jinja2
{{ obj.name }}
```

**Value template**
```jinja2
{{ obj.primary_ip4 }}
```

#### Zone selection based on Device location

**Zone template**
```jinja2
{{ obj.location.name | lower }}.example.com
```

**Name template**
```jinja2
{{ obj.name }}
```

**Value template**
```jinja2
{{ obj.primary_ip4 }}
```

### Interface Templates

#### Interface Multi-IP A/AAAA

**Zone template**
```jinja2
example.com
```

**Name template**
```jinja2
{{ obj.name }}.{{ obj.parent.name }}
```

**Value template**
```jinja2
{{ obj.ip_addresses.all() }}
```

Use `obj.parent` for interface parent naming so the template behaves the same for both device-backed and module-backed interface topologies.

### Service Templates

#### Service A/AAAA

**Zone template**
```jinja2
services.example.com
```

**Name template**
```jinja2
{{ obj.name }}
```

**Value template**
```jinja2
{{ obj.ip_addresses.all() }}
```

#### Conditional Parent Context

**Zone template**
```jinja2
{% if obj.device %}
  {{ obj.device.location.name }}.example.com
{% else %}
  {{ obj.virtual_machine.cluster.location.name }}.example.com
{% endif %}
```

**Name template**
```jinja2
{{ obj.name }}
```

**Value template**
```jinja2
{{ obj.ip_addresses.all() }}
```

## Advanced Examples

Some examples of more advanced templates. In some cases, these are showing what's possible and not making specific suggestions.

### Conditional Logic

For `zone_template`, selecting a zone based on tenant:

```jinja2
{% if obj.tenant.name == "Corp" %}
corp.example.com
{% else %}
external.example.com
{% endif %}
```

Using a custom field named "DNS Zone" with a fallback if unset:

```jinja2
{% if obj.location.cf.dns_zone %}
{{ obj.location.cf.dns_zone }}
{% else %}
default.example.com
{% endif %}
```

### DNS View Selection by IP

In some cases, an object may have multiple IPs for which DNS records are needed in different views. For example, an `Interface` may have two IPv4 addresses and one needs to go in one view and the other in a different view. For this purpose, the `view_template` has an `ip` context object available to it. If a template uses an `ip` context object, it will be rendered for each applicable IPAddress rendered by the `value_template`.

The `ip` context is also available in `zone_template`, so all patterns shown here apply equally to zone selection - the only difference is that the output must be a valid DNS zone name.

#### Direct Comparison

An overly simplistic example which demonstrates how `ip` can be used:
```jinja2
{{ "RestrictedView" if ip.parent.prefix|string == "172.1.1.0/24" else "InternalView" }}
```

#### Conditional Selection

Select a view based on the tenant assigned to the IP's parent prefix:

```jinja2
{{ "CorpView" if ip.parent.tenant and ip.parent.tenant.name == "Corp" else "ExternalView" }}
```

The `ip.parent.tenant` check guards against prefixes with no tenant assigned.

For more than two cases, a block form is clearer:

```jinja2
{% if not ip.parent.tenant %}
    ExternalView
{% elif ip.parent.tenant.name == "Corp" %}
    CorpView
{% elif ip.parent.tenant.name == "DMZ" %}
    DMZView
{% else %}
    ExternalView
{% endif %}
```

Indenting values to make the template easier to read is safe as the rendering engine strips leading and trailing whitespace appropriately.

#### Using a Custom Field

A more scalable solution than the hardcoding seen above is to set the value for the DNS view; on a `CustomField`, for example. This version uses a custom field named `"DNS View"` on an IP's parent prefix if it's set, with a fallback if it's not:

```jinja2
{{ ip.parent.cf.dns_view or "Default" }}
```

#### Moving Logic to a Computed Field

For complex view selection logic, another option is to place a [`ComputedField`](https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/computedfield/) on an object, such as the `IPAddress` or `Prefix`, and then using a simpler template in the `DNSRule`:

**`IPAddress` computed field template** (runs with the `IPAddress` as `obj`):

Starting from the IP's direct parent prefix, this walks up the prefix hierarchy looking for a `"DNS View"` custom field. The loop runs up to 10 levels; once a value is found or the top of the hierarchy is reached, remaining iterations are no-ops. If no prefix in the hierarchy has the custom field set, it returns `"Default"`.

```jinja2
{%- set ns = namespace(current=obj.parent, value=None) -%}
{%- for _ in range(10) -%}
  {%- if ns.current and not ns.value -%}
    {%- if ns.current.cf.dns_view -%}
      {%- set ns.value = ns.current.cf.dns_view -%}
    {%- else -%}
      {%- set ns.current = ns.current.parent -%}
    {%- endif -%}
  {%- endif -%}
{%- endfor -%}
{{ ns.value or "Default" }}
```

**`view_template`**:

```jinja2
{{ ip.get_computed_fields()["dns_view"] }}
```

This keeps the rule template stable even if the view selection logic changes - only the computed field needs updating.


#### Moving Relationship Logic to a Computed Field

Use this approach when view intent is modeled as a relationship on `Prefix` and you want DNS rules to consume a pre-resolved value from `IPAddress`. This is one way to do this, but there are others.

1. Create a relationship on `Prefix`, in this example called `"Prefix to DNS View"`, which points to DNS view objects.
2. Add an `IPAddress` computed field (for example `dns_view_relationship`) that resolves the relationship on the IP's parent prefix.
3. Use that computed field in the DNS rule `view_template`.

**Example `IPAddress` computed field template**

Create an computed field, in this example named `"DNS View Relationship"`, with the following template:

```jinja2
{%- set relationship_key = "prefix_to_dns_view" -%}
{%- set resolved = namespace(value="") -%}
{%- if obj.parent -%}
  {%- set rels = obj.parent.get_relationships_with_related_objects(include_hidden=True).source -%}
  {%- for relationship, related in rels.items() -%}
    {%- if relationship.key == relationship_key and related -%}
      {%- for dns_view in related -%}
        {%- if resolved.value -%}{%- set resolved.value = resolved.value ~ ", " -%}{%- endif -%}
        {%- set resolved.value = resolved.value ~ dns_view.name -%}
      {%- endfor -%}
    {%- endif -%}
  {%- endfor -%}
{%- endif -%}
{{ resolved.value or "Default" }}
```

**`view_template`**:

With the computed field set above, it can be accessed from the `view_template`:

```jinja2
{{ ip.get_computed_fields()["dns_view_relationship"] }}
```

## Related Documentation

- [DNS Rule Template Reference](dns_rule_templates.md)
- [DNS Rules](dns_rules.md)
