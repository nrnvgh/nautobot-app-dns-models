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

## Advanced Techniques

### Conditional Logic

```jinja2
{% if obj.primary_ip4 %}
{{ obj.primary_ip4 }}
{% else %}
{{ "NoPrimaryIP" }}
{% endif %}
```

### Role-Based Naming

```jinja2
{% if obj.device.role.name == "Web Server" %}
web-{{ obj.name }}
{% elif obj.device.role.name == "Database" %}
db-{{ obj.name }}
{% else %}
{{ obj.name }}
{% endif %}
```

## Advanced Examples
### DNS View Selection by IP

These examples are for `view_template` and use per-candidate `ip` context for A/AAAA.

#### Prefix Match
```jinja2
{{ "RestrictedView" if ip.parent.prefix|string == "172.1.1.0/24" else "InternalView" }}
```

#### Ancestor Walk with Fallback
```jinja2
{%- set ns = namespace(current=ip.parent, value=None) -%}
{%- for _ in range(20) -%}
  {%- if not ns.current -%}{%- break -%}{%- endif -%}
  {%- if ns.current.cf.dns_view -%}
    {%- set ns.value = ns.current.cf.dns_view -%}
    {%- break -%}
  {%- endif -%}
  {%- set ns.current = ns.current.parent -%}
{%- endfor -%}
{{ ns.value or "Default" }}
```

#### Relationship-Based View Resolution via IPAddress Computed Field

Use this approach when view intent is modeled as a relationship on `Prefix` and you want DNS rules to consume a pre-resolved value from `IPAddress`. This is one way to do this, but there are others.

1. Create a relationship on `Prefix`, in this example called `Prefix to DNS View`, which points to DNS view objects.
2. Add an `IPAddress` computed field (for example `dns_view_relationship`) that walks parent prefixes and resolves the first relationship match.
3. Use that computed field in the DNS rule `view_template`.

**Example `IPAddress` computed field template**

Create an computed field name called `DNS View Relationship` with the following template:

```jinja2
{%- set relationship_key = "prefix_to_dns_view" -%}
{%- set resolved = namespace(value="") -%}

{%- if obj.parent -%}
  {%- for prefix in obj.parent.supernets(include_self=True).order_by("-prefix_length") -%}
    {%- if not resolved.value -%}
      {%- set rels = prefix.get_relationships_with_related_objects(include_hidden=True).source -%}
      {%- for relationship, related in rels.items() -%}
        {%- if relationship.key == relationship_key and related -%}
          {%- set joined = namespace(text="") -%}
          {%- for dns_view in related -%}
            {%- if joined.text -%}{%- set joined.text = joined.text ~ ", " -%}{%- endif -%}
            {%- set joined.text = joined.text ~ dns_view.name -%}
          {%- endfor -%}
          {%- set resolved.value = joined.text -%}
        {%- endif -%}
      {%- endfor -%}
    {%- endif -%}
  {%- endfor -%}
{%- endif -%}

{{ resolved.value or "Default" }}
```

**View template**
```jinja2
{{ ip.get_computed_fields()["dns_view_relationship"] }}
```

Returning `Default` from the computed field itself is usually preferable to adding fallback logic in each rule template.


## Template Validation

### Runtime Validation

- Syntax errors are rejected on save.
- Statement/comment-only fields (no `{{ ... }}`) are rejected.
- Literal fragments are validated for DNS safety constraints.

### Testing Approach

1. Start with simple templates.
2. Test with representative objects.
3. Add complexity incrementally.
4. Review logs for skipped candidates and reasons.

## Common Template Errors

### Undefined Variables

**Problem**
```jinja2
{{ obj.nonexistent_field }}
```

**Solution**
```jinja2
{{ obj.nonexistent_field | default("fallback-value") }}
```

### Missing Related Objects

For this plugin, prefer rendering `IPAddress` objects directly:

```jinja2
{{ obj.primary_ip4 }}
```

Avoid dereferencing `.address` when the field can be unset.

## Performance Considerations

- Keep templates simple for predictable performance.
- Avoid deep traversals where possible.
- Be cautious with expensive lookups when processing large batches.

## Best Practices

1. Start simple, then iterate.
2. Handle missing data intentionally.
3. Keep rule names and descriptions descriptive.
4. Prefer clear, maintainable templates over compact complexity.

## Related Documentation

- [DNS Rule Template Reference](dns_rule_templates.md)
- [DNS Rules](dns_rules.md)
