# DNS Reconciliation Jobs

Nautobot jobs drive rule-based DNS reconciliation when you need to materialize or repair DNS records for supported source objects. Common cases include newly enabled rules, drift repair, and related data changes that do not emit source-object processing signals.

For day-to-day rule behavior, precedence, and best-effort reconciliation semantics, see [DNS Rules](dns_rules.md).

## Prerequisites

These jobs must be enabled and runnable by your user. For job enablement, permissions, and logging setup, see [Install and Configure](../../admin/install.md#dns-reconciliation-jobs).

## Registered Jobs

| Display name | Class path | Typical use |
| ------------ | ---------- | ----------- |
| Reconcile DNS Records (Object) | `nautobot_dns_models.jobs.ReconcileDNSObjectJob` | Reconcile one primary object (detail-view button or API). |
| Reconcile DNS Records (Bulk) | `nautobot_dns_models.jobs.ReconcileDNSBulkJob` | Reconcile many objects with optional filters (UI or API). |

Supported source types match DNS Rule source models: `Device`, `Interface`, `Service`, `VirtualMachine`, `VMInterface`.

## Reconcile DNS Records (Object)

Reconciles DNS records for a single primary object.

- Intended invocation paths are detail-view **Reconcile DNS** button launches and API runs by class path.
- The object job is registered as hidden, so it may not appear in the default **Jobs > Jobs** listing.
- The button path opens the form with object fields pre-filled.

### Parameters

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `object_model` | yes | Content type of the source object. |
| `object_id` | yes | Primary key (UUID) of the source object. |
| `object_name` | no | Hidden UI display hint; not used in reconciliation logic. |
| `object_has_populated_device_bays` | no | Hidden UI hint for device-bay expansion behavior. |
| `include_child_devices` | no | For `Device` targets, include child devices in populated bays. Always shown in UI; enabled only when applicable. |
| `include_interfaces` | no | Include interfaces for applicable targets. Always shown in UI; enabled only when applicable. |
| `dryrun` | yes | Preview mode: selects targets and logs actions without applying create/update/delete writes. |

Internal processing uses a fixed batch size for target grouping in object runs.

## Reconcile DNS Records (Bulk)

Reconciles DNS records for all matched objects across supported source models.

- Launch from **Jobs > Jobs** or via API by class path.
- Scope is controlled by model/rule/location/tenant filters plus optional `limit`.

### Parameters

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `source_models` | no | Limit to specific source model content types. Empty means inferred from selected rules, or all supported models when no rule filter narrows scope. |
| `rules` | no | Limit to specific `DNSRule` instances. Rules must match selected source models. |
| `locations` | no | Restrict to source objects resolved to these Locations. |
| `tenants` | no | Restrict to source objects resolved to these Tenants. |
| `include_child_devices` | no | Same semantics as object job, but applicability is model-based (`source_models` includes `Device`) rather than per-object hints. |
| `include_interfaces` | no | Same semantics as object job, but applicability is model-based (`source_models` includes `Device` and/or `VirtualMachine`). |
| `limit` | no | Maximum number of in-scope objects to process (positive integer). |
| `batch_size` | no | Chunk size for fetch/render/delta/apply phases. Default `500`, max `5000`. |
| `dryrun` | yes | Preview mode: selects targets and logs actions without applying create/update/delete writes. |

Invalid `source_models` values or rule/model mismatches return a failed result with an `error` key (for example `invalid_source_models`, `rules_source_model_mismatch`).

## Job Result Payload

Successful runs return a JSON-serializable dict. The canonical response schema is defined at:

- `nautobot_dns_models/schemas/reconcile_dns_job_result.schema.json`

Example success payload (bulk run):

```jsonc
{
  "mode": {
    "dryrun": false,                 // True for preview-only runs.
    "single_object": false,          // True for object job runs; false for bulk.
    "include_child_devices": true,   // Whether child-device expansion was enabled.
    "include_interfaces": true,      // Whether interface expansion was enabled.
    "pipeline_stage_metrics": {}     // Bulk-only per-stage timing breakdown.
  },
  "scope": {
    "scanned_models": ["dcim.device", "dcim.interface"], // Model labels scanned while selecting targets.
    "filters": {
      "source_models": ["dcim.device"], // Source-model filters applied.
      "rule_ids": ["2c2f..."],          // DNSRule UUID filters applied.
      "location_ids": [],               // Location UUID filters applied.
      "tenant_ids": [],                 // Tenant UUID filters applied.
      "limit": 5000,                    // Max in-scope targets allowed.
      "batch_size": 500                 // Batch size used during processing.
    }
  },
  "execution": {
    "targets_selected_count": 1250,    // Targets selected after scope/filter evaluation.
    "targets_processed_count": 1250,   // Targets processed by the pipeline.
    "targets_succeeded_count": 1248,   // Processed targets without target-level failure.
    "targets_failed_count": 2,         // Processed targets with target-level failure.
    "runtime_seconds": 7.84            // End-to-end runtime in seconds.
  },
  "reconciliation": {
    "objects_changed": 200,            // Targets with at least one create/update/delete change.
    "record_ops_create_count": 190,    // DNS records created.
    "record_ops_delete_count": 10,     // DNS records deleted.
    "record_ops_update_count": 0,      // DNS records updated in place.
    "record_ops_total_count": 200,     // Total create+delete+update operations.
    "changed_record_count": 200,       // Total DNS records changed across operations.
    "targets_noop_count": 1048         // Targets evaluated with no required changes.
  }
}
```

Operationally useful fields are usually:

- `execution.targets_failed_count`
- `reconciliation.objects_changed`
- `reconciliation.record_ops_total_count`
- `reconciliation.record_ops_update_count`
- `execution.runtime_seconds`

Failure paths can return a reduced payload instead of the full success shape, for example:

```jsonc
{
  "error": "invalid_source_models",                 // Stable machine-readable failure code.
  "message": "Unsupported source_models: foo.bar",  // Human-readable failure detail.
  "invalid_source_models": ["foo.bar"]              // Offending values from caller input.
}
```

## Log Summary Line

At `INFO`, the job emits one summary line similar to:

```text
Reconciliation results: mode=<apply|dryrun> models=[...] seen=<n> processed=<n> success=<n> failure=<n> objects_changed=<n> record_ops(create=<n> delete=<n> update=<n> total=<n>) runtime_s=<seconds>
```

Use this line for quick run review. Use the full result payload for automation and metric reporting.

## Related Documentation

- [DNS Rules](dns_rules.md) - rule configuration and reconciliation behavior.
- [DNS Rule Template Reference](dns_rule_templates.md) - template context and forms.
- [DNS Rule Template Patterns](dns_rule_template_patterns.md) - practical template recipes and troubleshooting.
