# DNS Reconciliation Jobs

Nautobot Jobs drive rule-driven DNS reconciliation when you need to materialize or update DNS records for supported source objects. Common cases include new or newly enabled rules, drift repair, and related data changes that do not trigger automatic rule processing. Objects already in the database at the time a rule is created or enabled are not retroactively processed; a job run is required to cover them. How rules evaluate objects and when reconciliation runs in normal operation is described in [DNS Rules](dns_rules.md); this page documents the Jobs themselves.

## Prerequisites

These jobs must be enabled and runnable by your user. For setup details (job enablement, permissions, and logging), see [Install and Configure](../admin/install.md#dns-reconciliation-jobs).

## Registered Jobs

| Display name | Class path | Typical use |
| ------------ | ---------- | ----------- |
| Reconcile DNS Records (Object) | `nautobot_dns_models.jobs.ReconcileDNSObjectJob` | One primary object (detail-view button or API invocation). |
| Reconcile DNS Records (Bulk) | `nautobot_dns_models.jobs.ReconcileDNSBulkJob` | Scan many objects with optional filters (API or UI). |

Supported source types for the object Job match [DNS Rules](dns_rules.md): `Device`, `Interface`, `Service`, `VirtualMachine`, `VMInterface`.

## Reconcile DNS Records (Object)

Reconciles DNS records for a single primary object. Detail views for supported types can expose a **Reconcile DNS** button when at least one enabled rule is in scope; it opens this Job with the object pre-filled. The same class path can also be invoked via API.

### Parameters

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `object_model` | yes | Content type of the source object. |
| `object_id` | yes | Primary key (UUID) of the object. |
| `object_name` | no | Hidden display hint when launched from the UI; not used for reconciliation logic. |
| `object_has_populated_device_bays` | no | Hidden UI hint for devices with bays; not used for reconciliation logic. |
| `include_child_devices` | no | For `Device` targets, include child devices in populated device bays. When not applicable to the selected object/model context, it is disabled and submitted as unchecked. |
| `include_interfaces` | no | Include interfaces on applicable targets. When not applicable to the selected object/model context, it is disabled and submitted as unchecked. |
| `dryrun` | yes | Same semantics as the bulk Job. |

Internal processing uses a fixed batch size for grouping targets derived from the primary object and optional children.

## Reconcile DNS Records (Bulk)

Reconciles DNS records for all matched objects of the supported source types (`Device`, `Interface`, `Service`, `VirtualMachine`, `VMInterface`). Job parameters narrow the scope: which models to scan, which rules apply, location and tenant filters, and an optional `limit`.

Launch from **Jobs > Jobs** or via API by class path.

### Parameters

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `source_models` | no | Limit to specific source model content types. Empty means models implied by selected rules (or all supported models when no rule filter narrows scope). |
| `rules` | no | Limit to specific `DNSRule` instances. Must match the selected source models; otherwise the Job fails validation. |
| `locations` | no | Restrict to source objects related to these Locations. |
| `tenants` | no | Restrict to source objects related to these Tenants. |
| `include_child_devices` | no | Same semantics as the object Job parameter, but in bulk runs applicability is model-based (`source_models` includes `Device`) rather than per-object populated-bay hints. |
| `include_interfaces` | no | Same semantics as the object Job parameter, but in bulk runs applicability is model-based (`source_models` includes `Device` and/or `VirtualMachine`) rather than per-object interface hints. |
| `limit` | no | Maximum number of in-scope objects to process (positive integer). |
| `batch_size` | no | Chunk size for fetch/render/delta/apply phases. Defaults to `500`, max `5000`. |
| `dryrun` | yes | When enabled, selects targets and logs them but does not apply create/update/delete reconciliation. |

Invalid `source_models` or rule or model mismatches produce a failed Job result with an `error` key in the returned dict (for example `invalid_source_models`, `rules_source_model_mismatch`).

## Job result payload

Successful runs return a JSON-serializable dict. The canonical response schema is defined in-repo at `nautobot_dns_models/schemas/reconcile_dns_job_result.schema.json`.

Example success payload (bulk run):

```jsonc
{
  "mode": {
    "dryrun": false,                 // True for preview-only runs (no create/update/delete writes).
    "single_object": false,          // True for object job runs; false for bulk runs.
    "include_child_devices": true,   // Whether child-device expansion was enabled for this run.
    "include_interfaces": true,      // Whether interface expansion was enabled for this run.
    "pipeline_stage_metrics": {}     // Bulk-only per-stage timing breakdown from the rule-engine pipeline.
  },
  "scope": {
    "scanned_models": ["dcim.device", "dcim.interface"], // Model labels scanned while selecting/processing targets.
    "filters": {
      "source_models": ["dcim.device"], // Source-model filters applied (empty means all supported/inferred models).
      "rule_ids": ["2c2f..."],          // DNSRule UUID filters applied.
      "location_ids": [],               // Location UUID filters applied.
      "tenant_ids": [],                 // Tenant UUID filters applied.
      "limit": 5000,                    // Maximum number of in-scope targets allowed for processing.
      "batch_size": 500                 // Pipeline batch size used during processing.
    }
  },
  "execution": {
    "targets_selected_count": 1250,    // Targets selected after scope/filter evaluation.
    "targets_processed_count": 1250,   // Targets actually processed by the reconciliation pipeline.
    "targets_succeeded_count": 1248,   // Processed targets that completed without target-level failure.
    "targets_failed_count": 2,         // Processed targets that failed reconciliation.
    "runtime_seconds": 7.84            // End-to-end job runtime in seconds.
  },
  "reconciliation": {
    "objects_changed": 200,            // Targets with at least one DNS record create/update/delete change.
    "record_ops_create_count": 190,    // DNS records created.
    "record_ops_delete_count": 10,     // DNS records deleted.
    "record_ops_update_count": 0,      // DNS records updated in place (for example, renames).
    "record_ops_total_count": 200,     // Total create+delete+update operations.
    "changed_record_count": 200,       // Total DNS records changed across all operations.
    "targets_noop_count": 1048         // Targets evaluated with no required DNS record changes.
  }
}
```

Operationally, the most useful fields are usually `execution.targets_failed_count`, `reconciliation.objects_changed`, `reconciliation.record_ops_total_count`, `reconciliation.record_ops_update_count`, and `execution.runtime_seconds`.

Failure paths can return a reduced payload instead of the full success shape, for example:

```jsonc
{
  "error": "invalid_source_models",                 // Stable machine-readable failure code.
  "message": "Unsupported source_models: foo.bar",  // Human-readable error detail.
  "invalid_source_models": ["foo.bar"]              // Offending values provided by the caller.
}
```

## Log summary line
At **INFO**, the Job emits one summary line similar to:

```text
Reconciliation results: mode=<apply|dryrun> models=[...] seen=<n> processed=<n> success=<n> failure=<n> objects_changed=<n> record_ops(create=<n> delete=<n> update=<n> total=<n>) runtime_s=<seconds>
```

Use this line for quick post-run review; use the full result payload for automation or detailed metrics.

## Related documentation

- [DNS Rules](dns_rules.md) — rule configuration, best-effort reconciliation, and when jobs are needed.
- [Install and Configure](../admin/install.md) — enable Jobs, permissions, and logging.
