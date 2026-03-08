# Reconcile Update Performance Tally

This document is a running, developer-level log of reconciliation performance work for bulk update runs.

Scope:
- Bulk reconcile update path (`ReconcileDNSBulkJob` -> `DNSRuleEngine.process_object(..., created=False)`).
- Emphasis on the slow "name-changing update" benchmark case.

---

## 0) Initial benchmark baseline (before profiling)

User-reported benchmark on laptop:

- 100 DNS records created: `~3.0s`
- 100 NOOP updates: `~1.9s`
- 100 updates with name changes: `~6.2s`

Interpretation:
- Rename/update path was the primary outlier.
- At this point no code changes had been made.

---

## 1) First captured profile (control run, not update-heavy)

Profile:
- `nautobot-jobresult-ffcb1691-f1d3-4709-a019-66eb978f0164.pstats`
- Total: `0.527s`

Notable data:
- Dominated by target scan and queryset/relationship fetch overhead.
- `engine.py` reconcile methods were effectively absent from hot path.

Conclusion:
- This profile did not represent the expensive rename update workload.

Changes made after this profile:
- None.

---

## 2) Update-heavy profile (pre-identity optimization)

Profile:
- `nautobot-jobresult-7e46c044-14fd-48de-98e8-c01f735e00e6-update2.pstats`
- Total: `6.398s`

Top cumulative hotspots:
- `engine.py:79(process_object)`: `6.056s`
- `engine.py:407(_update_dns_records_for_object)`: `5.683s`
- `engine.py:686(_reconcile_records_for_rule)`: `5.350s`
- `engine.py:1027(_delete_tracking_and_dns_record)`: `2.518s`
- `engine.py:926(_create_records_from_data)`: `2.050s`
- `validated_save`: `1.938s`
- Change logging serialization path:
  - `change_logging.py:34(to_objectchange)`: `2.867s`
  - `utils.py:140(serialize_object_v2)`: `2.614s`

Diagnosis:
- Rename updates were treated as delete old + create new.
- That triggered high write churn, signal dispatch, and object-change serialization overhead.

Changes made before next rerun:

### `nautobot_dns_models/rules/engine.py`
- Added identity-key reconciliation concept for A/AAAA:
  - identity key excludes mutable `name`.
  - used to match existing/desired records for in-place updates.
- Reworked `_reconcile_records_for_rule()`:
  - delete/create by identity set differences.
  - in-place update on identity matches.
- Added `_update_tracking_record_dns_record()` helper.
- Added `_log_record_update_failure()` helper.
- `changed_record_count` now includes in-place updates.

### `nautobot_dns_models/jobs.py`
- `_process_targets()` now resolves location/tenant only when corresponding filters are provided.

---

## 3) Update-heavy profile after identity in-place update

Profile:
- `nautobot-jobresult-ccaf3f06-fd5e-4378-9978-02e97489c053-UPDATE-identity.pstats`
- Total: `3.172s`

Measured improvement:
- From `6.398s` -> `3.172s` (~50% reduction).

Top remaining hotspots:
- `engine.py:711(_reconcile_records_for_rule)`: `2.370s`
- `engine.py:945(_update_tracking_record_dns_record)`: `1.743s`
- `validated_save`: `1.740s`
- Change logging still heavy:
  - `change_logging.py:34(to_objectchange)`: `1.174s`
  - `serialize_object_v2`: `1.069s`

Diagnosis:
- Delete/create churn was reduced successfully.
- Remaining cost concentrated in model `validated_save()` on in-place updates, including downstream change-logging and serializer work.

Changes made before next rerun:

### `nautobot_dns_models/rules/engine.py`
- In `_update_tracking_record_dns_record()`, switched rename-only update from `validated_save()` to direct ORM `update(name=...)`:
  - `type(dns_record).objects.filter(pk=dns_record.pk).update(name=desired_name)`
- Kept error handling and logging for update failures.

---

## 4) Update-heavy profile after direct DB update (no change log emphasis)

Profile:
- `nautobot-jobresult-62724743-ad06-4fef-9ff9-7aa62eac3219-UPDATE-identity-nochangelog.pstats`
- Total: `1.532s`

Measured improvement:
- From `3.172s` -> `1.532s` (~51.7% reduction).
- From `6.398s` -> `1.532s` (~76.1% reduction).

Top cumulative hotspots now:
- `engine.py:79(process_object)`: `1.338s`
- `engine.py:432(_update_dns_records_for_object)`: `0.980s`
- `engine.py:711(_reconcile_records_for_rule)`: `0.705s`
- SQL/query overhead dominates:
  - `compiler.py:1532(execute_sql)`: `0.854s`
  - `query.py:87(__iter__)`: `0.836s`
  - `query.py:1884(_fetch_all)`: `0.831s`
- Template and rule-resolution are now meaningful portions:
  - `_calculate_desired_record_data`: `0.526s`
  - `render_jinja2`: `0.287s`
  - `_get_applicable_rules`: `0.233s`
  - `_get_object_tenant`: `0.176s`
  - `_cleanup_orphaned_records`: `0.145s`

Diagnosis:
- Write-path cost was dramatically reduced.
- Next limiting factor is mostly read/query/template overhead.

---

## 5) Current unprofiled optimization pass (applied after run #4)

Code changes have been applied but not yet benchmarked/profiled:

### `nautobot_dns_models/rules/engine.py`
- Added `DNSRuleEngine.__init__()` runtime caches:
  - `_default_view_cache`
  - `_zone_lookup_cache`
- `_get_applicable_rules()` now returns a materialized `list[DNSRule]`:
  - avoids extra trailing `DNSRule.objects.filter(pk__in=...)` fetch.
  - global rule branch now returns a list directly.
- `process_object()` now uses `len(rules)` instead of queryset `count()`.
- Updated create/update helpers to accept `list[DNSRule]`.
- Added short-circuit to skip per-candidate IP context hydration unless `view_template` or `zone_template` references `ip`.
- Added zone lookup caching by `(zone_name, sorted(view_ids))`.
- Added default view caching for no-`view_template` path.

Expected impact before next run:
- Fewer repeat DB hits in rule resolution and zone/view lookup.
- Reduced per-candidate query overhead in desired-record calculation.

---

## Summary table

| Stage | Profile | Total time |
|---|---|---:|
| Pre-change update-heavy | `...update2.pstats` | `6.398s` |
| After identity in-place update | `...UPDATE-identity.pstats` | `3.172s` |
| After direct DB rename update | `...UPDATE-identity-nochangelog.pstats` | `1.532s` |

Current status:
- Performance has improved materially.
- Remaining optimization opportunities are primarily in read/query/template-resolution path, not write churn.

---

## 6) Checkpoint after latest update round: time-budget split

Reference profile:
- `nautobot-jobresult-62724743-ad06-4fef-9ff9-7aa62eac3219-UPDATE-identity-nochangelog.pstats`
- Total runtime: `1.532s`

Two views are useful for engineers:

### End-to-end cumulative view (wall-time oriented)

This approximates "where runtime is spent waiting" in major stacks.

- Jinja rendering stack: `~0.287s` (`~18.7%`)
- SQL/ORM execution stack: `~0.854s` (`~55.7%`)
- Other Python/runtime work: `~0.391s` (`~25.5%`)

Notes:
- Cumulative values are practical for optimization direction but can include nested overlap in call graphs.
- At this stage, SQL/ORM dominates.

### Exclusive-time (tottime) view (non-overlapping function self-time)

This is useful for low-level CPU attribution.

- Jinja-related exclusive time: `~0.094s` (`~6.2%`)
- SQL stack exclusive time: `~0.629s` (`~41.0%`)
- Other Python exclusive time: `~0.809s` (`~52.8%`)

Interpretation:
- Jinja is material but secondary.
- SQL remains the largest single subsystem bottleneck.
- The remaining non-SQL Python time is broad framework/runtime overhead distributed across ORM query construction, object access, and helper logic.

---

## 7) Safe/Fast split introduced (post-checkpoint)

Goal:
- Keep correctness/normal semantics on default path.
- Isolate aggressive performance optimizations behind explicit fast mode.

### Implementation summary

Updated files:
- `nautobot_dns_models/jobs.py`
- `nautobot_dns_models/rules/engine.py`
- `nautobot_dns_models/rules/engine_safe.py`
- `nautobot_dns_models/rules/engine_fast.py`
- `nautobot_dns_models/rules/engine_selector.py`
- `nautobot_dns_models/signals.py`
- `nautobot_dns_models/template_content.py`

Key changes:

1. Job-level mode switch:
   - Added `performance_mode` choice var (`safe` | `fast`, default `safe`) in shared reconcile job base class.
   - Threaded mode through both bulk and object reconciliation jobs into `rule_engine.process_object(...)`.
   - Added normalization for invalid mode values -> `safe`.
   - Included `performance_mode` in result payload under `mode`.

2. Engine mode plumbing:
   - `process_object(..., performance_mode="safe")` and downstream create/update/reconcile internals now accept mode.

3. Behavior by mode:
   - `safe`:
     - Identity matching retained.
     - In-place updates use `validated_save()` path (normal model semantics).
     - Fast-only cache/shortcut behavior disabled.
   - `fast`:
     - Identity matching retained.
     - In-place rename updates use direct SQL `UPDATE` path.
     - Fast-only shortcuts enabled:
       - rule/template IP-context shortcut
       - default view cache usage
       - zone lookup cache usage

4. Separate entry points:
   - Added explicit engine entry classes:
     - `SafeDNSRuleEngine`
     - `FastDNSRuleEngine`
   - Added selector helper:
     - `get_rule_engine(performance_mode)`
   - Jobs now pick engine instance once per run and call that instance in the target loop.
   - Signals and template extensions now explicitly use the safe engine instance.

### Counter correctness fix (applies to both modes)

Issue found after split:
- Update-only reconciles could report `changed_record_count=0` and `objects_changed=0` even when updates occurred.
- Root cause: update count returned by `_reconcile_records_for_rule()` was not aggregated in `_update_dns_records_for_object()`.

Fix:
- Added `update_count` accumulation and included it in `changed_record_count`:
  - `changed_record_count = create_count + delete_count + update_count`

Impact:
- Reporting now reflects update-in-place operations correctly in both safe and fast modes.
- No material expected performance penalty (in-memory integer aggregation only).

---

## 8) Latest profiled runtime snapshot after split

Current profiled measurements reported by user:

- Fast mode (`performance_mode=fast`): `~1.2s / 100`
- Safe mode (`performance_mode=safe`): `~3.2s / 100`

Derived throughput:

- Fast: `~83 records/sec`
- Safe: `~31 records/sec`
- Fast vs safe speedup: `~2.7x`

Notes:
- These values are profiling-on numbers and include profiler overhead.
- Next checkpoint should include non-profiled measurements for production-adjacent performance tracking.

---

## 9) Next measurement checkpoint (pending)

Provided (user):
- Fast (no profiling): `~0.7s / 100`
- Safe (no profiling): `~1.9s / 100`

Derived throughput:
- Fast: `~143 records/sec`
- Safe: `~53 records/sec`
- Fast vs safe speedup: `~2.7x`

Comparison to profiled values:
- Profiled fast: `~1.2s` -> non-profiled fast: `~0.7s` (faster without profiler, as expected)
- Profiled safe: `~3.2s` -> non-profiled safe: `~1.9s` (faster without profiler, as expected)

Implication:
- Current best observed throughput is on fast mode at roughly `~143 records/sec` for this benchmark shape.
- Remaining gap to `5000/sec` target is still very large and will require additional architectural/batch optimizations beyond current per-object pipeline.

---

## 10) Post-entrypoint-split runtime checkpoint

User-reported non-profiled runtimes after explicit safe/fast engine entrypoint split:

- Fast mode: `~0.73s / 100`
- Safe mode: `~1.75s / 100`

Derived throughput:

- Fast: `~137 records/sec`
- Safe: `~57 records/sec`
- Fast vs safe speedup: `~2.4x`

Comparison to previous non-profiled checkpoint:

- Fast: `0.70s` -> `0.73s` (small variance-level change)
- Safe: `1.90s` -> `1.75s` (small improvement)

Interpretation:
- The safe/fast entrypoint refactor did not introduce a major regression.
- Performance remains in the same range as pre-split measurements, with normal run-to-run noise.

---

## 11) Experimental engine (greenfield fast-path re-implementation track)

Purpose:
- Keep a clean, stepwise optimization track separate from mature `fast`.
- Start from safe semantics, add one tuning at a time, benchmark each change, and back out negligible wins.

Implementation scaffold:
- Added mode: `performance_mode=experimental`.
- Added engine: `ExperimentalDNSRuleEngine`.
- Selector routes `experimental` to that engine.
- Benchmark harness now accepts `--performance-mode experimental`.

### Experimental baseline (safe-equivalent, no experimental-only tunings)

Benchmark shape:
- External benchmark script (`httpx`), 5 runs.
- `source_model=dcim.interface`, `limit=1000`, `batch_size=1000`.
- Non-NOOP enforced by unique suffix per run.

Measured runtime:
- `runs=5 avg_s=18.9194 median_s=19.1178 min_s=17.9081 max_s=20.3116`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~52.9 records/sec` (`1000 / 18.9194`)

Interpretation:
- Baseline confirms experimental path initially matches slow-path characteristics.

### Experimental tuning #1: direct DB rename update

Change:
- In `ExperimentalDNSRuleEngine`, override in-place rename update method to use direct SQL:
  - `type(dns_record).objects.filter(pk=dns_record.pk).update(name=desired_name)`
- All other behavior remains safe-equivalent (identity matching, reconcile flow, no fast caches).

Measured runtime after tuning #1:
- `runs=5 avg_s=7.9509 median_s=7.7780 min_s=7.3195 max_s=8.5038`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~125.8 records/sec` (`1000 / 7.9509`)

Delta vs experimental baseline:
- `18.9194s -> 7.9509s` (`~58.0%` faster, `~10.97s` absolute improvement).

### Experimental tuning #2: Jinja compiled-template cache

Change:
- In `ExperimentalDNSRuleEngine`, override template rendering to cache compiled Jinja templates:
  - Compile once per template string (`Environment.from_string(...)`).
  - Reuse compiled template for subsequent renders.
  - Keep existing empty-render/error-string guardrails.
- This was added on top of tuning #1 only.

Measured runtime after tuning #2:
- `runs=5 avg_s=6.5081 median_s=6.6758 min_s=6.0997 max_s=6.9297`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~153.7 records/sec` (`1000 / 6.5081`)

Delta vs tuning #1:
- `7.9509s -> 6.5081s` (`~18.1%` faster, `~1.44s` absolute improvement).

Delta vs experimental baseline:
- `18.9194s -> 6.5081s` (`~65.6%` faster, `~12.41s` absolute improvement).

### Experimental runtime parity adjustment: force Django sandboxed Jinja env

Reason:
- User-supplied templates must execute in Nautobot/Django sandboxed Jinja environment.
- Experimental engine was changed to always use `django.template.engines["jinja"].env` and remove non-sandbox fallback.

Measured runtime after sandboxed-env enforcement:
- `runs=5 avg_s=7.2150 median_s=7.3152 min_s=6.6853 max_s=7.8915`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~138.6 records/sec` (`1000 / 7.2150`)

Delta vs prior experimental run (tuning #2 with fallback present):
- `6.5081s -> 7.2150s` (`~10.9%` slower, `~0.71s` absolute regression).
- Throughput: `153.7 -> 138.6 records/sec` (`-15.1 records/sec`).

Delta vs experimental baseline:
- `18.9194s -> 7.2150s` (`~61.9%` faster, `~11.70s` absolute improvement).

### Experimental tuning #3: rule-scope applicable-rules cache

Change:
- In `ExperimentalDNSRuleEngine`, added `_applicable_rules_cache` keyed by:
  - `(content_type_id, location_id, tenant_id)`
- Added `_get_applicable_rules()` override to reuse resolved rule lists per scope key.
- Added `reset_runtime_caches()` override to clear scope cache at job start, preventing stale rule/template reuse across runs.

Measured runtime after tuning #3:
- `runs=5 avg_s=5.2425 median_s=5.6133 min_s=4.5548 max_s=5.7756`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~190.7 records/sec` (`1000 / 5.2425`)

Delta vs sandboxed-env parity checkpoint:
- `7.2150s -> 5.2425s` (`~27.3%` faster, `~1.97s` absolute improvement).
- Throughput: `138.6 -> 190.7 records/sec` (`+52.1 records/sec`).

Delta vs experimental baseline:
- `18.9194s -> 5.2425s` (`~72.3%` faster, `~13.68s` absolute improvement).

### Experimental tuning #4: default DNS view cache

Change:
- In `ExperimentalDNSRuleEngine`, added `_default_view_cache`.
- Overrode `_get_dns_views_for_rule()`:
  - For no-`view_template` path, cache and reuse default `DNSView` instance.
  - Keep existing behavior for explicit `view_template` rendering/validation.
- Reset `_default_view_cache` in `reset_runtime_caches()` per run.

Measured runtime after tuning #4:
- `runs=5 avg_s=5.1704 median_s=5.2605 min_s=4.5949 max_s=5.7719`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~193.4 records/sec` (`1000 / 5.1704`)
- Benchmark caveat: tested with `view_template` unset (empty/static default-view path).

Delta vs tuning #3:
- `5.2425s -> 5.1704s` (`~1.4%` faster, `~0.07s` absolute improvement).
- Throughput: `190.7 -> 193.4 records/sec` (`+2.7 records/sec`).

Delta vs experimental baseline:
- `18.9194s -> 5.1704s` (`~72.7%` faster, `~13.75s` absolute improvement).

### Experimental tuning #5: zone lookup cache

Change:
- In `ExperimentalDNSRuleEngine`, added `_zone_lookup_cache` keyed by:
  - `(zone_name, sorted(view_ids))`
- Overrode `_get_zones_for_rule()`:
  - Reuse cached zone-query results for repeated zone/view combinations.
  - Keep existing missing-zone validation semantics.
- Reset `_zone_lookup_cache` in `reset_runtime_caches()` per run.

Measured runtime after tuning #5:
- `runs=5 avg_s=4.8201 median_s=5.0902 min_s=4.0588 max_s=5.2314`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~207.5 records/sec` (`1000 / 4.8201`)

Delta vs tuning #4:
- `5.1704s -> 4.8201s` (`~6.8%` faster, `~0.35s` absolute improvement).
- Throughput: `193.4 -> 207.5 records/sec` (`+14.1 records/sec`).

Delta vs experimental baseline:
- `18.9194s -> 4.8201s` (`~74.5%` faster, `~14.10s` absolute improvement).

### Experimental tuning #6: IP prefetch context shortcut

Change:
- In `ExperimentalDNSRuleEngine`, added an IP-context shortcut in `_build_record_context()`:
  - Reuse `source_obj.ip_addresses` relation data when available to resolve `record["address_id"]`.
  - Fallback to the base lookup path when a prefetched match is unavailable.
- Threaded current source object through desired-record calculation for this context-only shortcut.

Measured runtime after tuning #6:
- `runs=5 avg_s=4.4265 median_s=4.5370 min_s=3.6295 max_s=5.1290`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~225.9 records/sec` (`1000 / 4.4265`)

Delta vs tuning #5:
- `4.8201s -> 4.4265s` (`~8.2%` faster, `~0.39s` absolute improvement).
- Throughput: `207.5 -> 225.9 records/sec` (`+18.4 records/sec`).

Decision:
- Kept. This experiment did not regress.

### Experimental tuning #7: chunk-level processing path

Change:
- Added `process_objects_batch()` in `ExperimentalDNSRuleEngine`.
- Updated bulk job target-batch processing to execute an experimental chunk-level batch call path when mode is `experimental`.

Measured runtime after tuning #7:
- `runs=5 avg_s=4.1762 median_s=4.5263 min_s=3.5178 max_s=4.6696`
- Each run reported `objects_changed=1000`, `changed_record_count=1000`.
- Throughput (avg): `~239.5 records/sec` (`1000 / 4.1762`)

Delta vs tuning #6:
- `4.4265s -> 4.1762s` (`~5.7%` faster, `~0.25s` absolute improvement).
- Throughput: `225.9 -> 239.5 records/sec` (`+13.6 records/sec`).

Decision:
- Kept. This experiment did not regress.

Delta vs experimental baseline:
- `18.9194s -> 4.1762s` (`~77.9%` faster, `~14.74s` absolute improvement).

Current experimental tuning ledger:
- Applied:
  - Identity in-place reconcile (inherited from safe baseline)
  - Direct DB rename update (experimental tuning #1)
  - Jinja compiled-template cache (experimental tuning #2)
  - Sandboxed-env parity with Django backend (required security constraint)
  - Rule-scope applicable-rules cache with per-run reset (experimental tuning #3)
  - Default DNS view cache with per-run reset (experimental tuning #4)
  - Zone lookup cache with per-run reset (experimental tuning #5)
  - IP prefetch context shortcut (experimental tuning #6)
  - Chunk-level processing path (experimental tuning #7)
- Not yet applied:
  - Batched SQL CASE rename updates

