# Reconcile Greenfield Performance Tally

This document tracks performance measurements for the greenfield reconciliation architecture track.

Scope and constraints:
- Bulk and signal paths are intentionally diverged.
- Initial release scope is `A/AAAA` only.
- No schema changes in this phase.
- Baseline branch compatibility target is `ltm-2.4`; changes are constrained to post-`ltm-2.4` code.

---

## Environment baseline

- Nautobot instance: `http://localhost:19080`
- Seed script: `.local/seed_dns_benchmark.py`
- Seed size: `1000` interfaces
- Seed-created DNS objects:
  - DNS view: `Default`
  - DNS zone: `bench.local`
  - DNS rule: `dns-bench-interface-a-record`

---

## Greenfield architecture baseline (strategy modularization)

Implemented:
- Pipeline strategy interface and registry in `nautobot_dns_models/rules/pipeline_strategies.py`
- Experimental pipeline engine strategy switch:
  - `python_first` (active default)
  - `hybrid` (placeholder)
  - `sql_heavy` (placeholder)
- Job var `pipeline_strategy` added to `ReconcileDNSBulkPipelineExperimentalJob`
- Benchmark script support for `--pipeline-strategy`

Status:
- Behavior-compatible baseline wiring complete.

---

## Benchmark baseline #1 (python_first)

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy python_first \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `2.5383`, `2.0824`, `1.9923`, `2.7501`, `1.4279`
- Average: `2.1582s`
- Median: `2.0824s`
- Min/Max: `1.4279s` / `2.7501s`
- Throughput (wall-clock): `~463.3 records/sec` (1000 / 2.1582)

Important note:
- This run is currently a **NOOP baseline** (`objects_changed=0`, `changed_record_count=0` for all runs).
- Treat this as architecture/runtime overhead baseline only, not update-path throughput baseline.

---

## Next measurement gate

Before comparing strategy performance:
- Ensure benchmark rule produces non-NOOP reconciliation changes.
- Re-run 5-run baseline (`python_first`) and record:
  - `objects_changed`
  - `changed_record_count`
  - records/sec using changed-path runs.

---

## Benchmark baseline #2 (python_first, update path)

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy python_first \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `3.7402`, `2.5201`, `3.6085`, `2.5139`, `3.5811`
- Average: `3.1928s`
- Median: `3.5811s`
- Min/Max: `2.5139s` / `3.7402s`
- Throughput (changed-record baseline): `~313.2 changed records/sec` (1000 / 3.1928)

Run-level reconciliation outcome:
- `objects_changed=1000`
- `changed_record_count=1000`

Interpretation:
- This is the first valid greenfield update baseline for strategy comparisons.

---

## Strategy test #1 (hybrid v1, update path)

Change:
- Implemented a true `hybrid` strategy path in `engine_experimental_pipeline`:
  - precompute per-object rule applicability once in planning
  - avoid repeated `_object_needs_dns_records_for_rule()` calls during apply
  - use prefetch-aware `ip_addresses` checks for `A/AAAA` when prefetch cache is present
  - fallback to existing behavior when prefetch is not present

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy hybrid \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `2.5656`, `2.0604`, `1.4411`, `3.0318`, `1.9865`
- Average: `2.2171s`
- Median: `2.0604s`
- Min/Max: `1.4411s` / `3.0318s`
- Throughput (changed-record): `~451.0 changed records/sec` (1000 / 2.2171)

Comparison vs python_first update baseline:
- Baseline avg: `3.1928s` (`~313.2 changed/sec`)
- Hybrid avg: `2.2171s` (`~451.0 changed/sec`)
- Delta: `-0.9757s` average runtime (`~30.6%` faster)

Outcome:
- Keep this `hybrid` v1 change as the new active optimization candidate.

---

## Strategy test #2 (hybrid v2 static-template fast path, update path)

Change attempted:
- Added a hybrid-only static-template fast path to resolve view/zone once per rule when both templates are literals.
- Goal was to reduce per-record render/context and zone/view resolution overhead in planning/apply.

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy hybrid \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `3.2663`, `1.9641`, `2.0856`, `2.4503`, `1.9761`
- Average: `2.3485s`
- Median: `2.0856s`
- Min/Max: `1.9641s` / `3.2663s`
- Throughput (changed-record): `~425.8 changed records/sec` (1000 / 2.3485)

Comparison vs hybrid v1:
- Hybrid v1 avg: `2.2171s` (`~451.0 changed/sec`)
- Hybrid v2 static-template avg: `2.3485s` (`~425.8 changed/sec`)
- Delta: `+0.1314s` average runtime (`~5.9%` slower)

Outcome:
- Rejected and backed out.
- Active candidate remains `hybrid` v1.

---

## Strategy test #3 (hybrid v3 bulk_update rename path, update path)

Change attempted:
- Replaced per-record rename update loop in hybrid reconcile apply with Django `bulk_update()` by DNS record model.
- Included fallback to existing per-record update path if batch update failed.

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy hybrid \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `3.7455`, `2.7263`, `3.6078`, `2.5336`, `4.2570`
- Average: `3.3741s`
- Median: `3.6078s`
- Min/Max: `2.5336s` / `4.2570s`
- Throughput (changed-record): `~296.4 changed records/sec` (1000 / 3.3741)

Comparison vs hybrid v1:
- Hybrid v1 avg: `2.2171s` (`~451.0 changed/sec`)
- Hybrid v3 bulk_update avg: `3.3741s` (`~296.4 changed/sec`)
- Delta: `+1.1570s` average runtime (`~52.2%` slower)

Outcome:
- Rejected and backed out.
- Active candidate remains `hybrid` v1.

---

## Strategy test #4 (hybrid v4 strict batch rename flush, update path)

Change implemented:
- Reworked rename updates to queue all changed DNS records during reconcile and execute one model-level `bulk_update()` flush at pipeline end.
- Removed silent per-record fallback in the batch flush path for this benchmark variant.
- Wired this flush behavior into both `python_first` and `hybrid` pipeline methods.

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy hybrid \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `3.1338`, `1.4757`, `1.4226`, `2.4709`, `1.4140`
- Average: `1.9834s`
- Median: `1.4757s`
- Min/Max: `1.4140s` / `3.1338s`
- Throughput (changed-record, average): `~504.2 changed records/sec` (1000 / 1.9834)
- Throughput (changed-record, median): `~677.6 changed records/sec` (1000 / 1.4757)

SQL validation (20-node run, docker log scoped by run timestamp):
- Confirmed single consolidated `UPDATE ... SET "name" = CASE WHEN ...` statement for all changed A records in batch.
- Confirmed no per-record `UPDATE ... WHERE id = ...` during rename apply for this path.
- Remaining SQL hotspots still visible:
  - per-record `SELECT ... FROM nautobot_dns_models_arecord WHERE id = ...` from `tracking_record.dns_record` GenericFK resolution.
  - repeated `SELECT ... FROM nautobot_dns_models_dnsview WHERE name IN ('Default')`.

Comparison vs hybrid v1:
- Hybrid v1 avg: `2.2171s` (`~451.0 changed/sec`)
- Hybrid v4 strict batch flush avg: `1.9834s` (`~504.2 changed/sec`)
- Delta: `-0.2337s` average runtime (`~10.5%` faster)

Outcome:
- Keep as active candidate.
- Next hotspot: batch-resolve `DNSRuleRecord -> dns_record` to remove GenericFK N+1 selects.

---

## Strategy test #5 (hybrid v5 GenericFK batch preloading, update path)

Change implemented:
- Added batch preloading of `DNSRuleRecord.dns_record` targets grouped by `dns_record_content_type`.
- Reconcile now uses preloaded DNS record objects when computing identity/update decisions.
- Goal: eliminate per-record GenericFK lookups (`SELECT ... arecord WHERE id = ...`) in update path.

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy hybrid \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `2.5243`, `1.4571`, `1.4358`, `1.6026`, `2.6001`
- Average: `1.9240s`
- Median: `1.6026s`
- Min/Max: `1.4358s` / `2.6001s`
- Throughput (changed-record, average): `~519.8 changed records/sec` (1000 / 1.9240)
- Throughput (changed-record, median): `~624.0 changed records/sec` (1000 / 1.6026)

SQL validation (20-node run, docker log scoped by run timestamp):
- `SELECT "nautobot_dns_models_arecord"...` count: `1` (down from per-record N+1 pattern).
- `UPDATE "nautobot_dns_models_arecord"...` count: `1` (single batched CASE update).
- `SELECT "nautobot_dns_models_dnsview"...` count: `20` (still repeated and now dominant among obvious query repeats).

Comparison vs hybrid v4 strict batch flush:
- Hybrid v4 avg: `1.9834s` (`~504.2 changed/sec`)
- Hybrid v5 GFK preload avg: `1.9240s` (`~519.8 changed/sec`)
- Delta: `-0.0594s` average runtime (`~3.0%` faster)

Outcome:
- Keep as active candidate.
- Next hotspot: DNS view lookup caching in hybrid pipeline path.
- Backout note: improvement is modest; if downstream changes interact poorly, consider reverting this in favor of simpler code.

---

## Strategy test #6 (hybrid v6 DNS view lookup cache, update path)

Change implemented:
- Added rendered-view lookup cache in `ExperimentalDNSRuleEngine._get_dns_views_for_rule()`.
- Cache key is ordered deduplicated rendered view-name tuple.
- Reuses cached view objects for repeated template outputs during a run.

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy hybrid \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `1.9789`, `0.8994`, `0.8933`, `0.9030`, `1.0034`
- Average: `1.1356s`
- Median: `0.9030s`
- Min/Max: `0.8933s` / `1.9789s`
- Throughput (changed-record, average): `~880.6 changed records/sec` (1000 / 1.1356)
- Throughput (changed-record, median): `~1107.4 changed records/sec` (1000 / 0.9030)

SQL validation (20-node run, docker log scoped by run timestamp):
- `SELECT "nautobot_dns_models_dnsview"...` count: `1` (down from `20`).
- `SELECT "nautobot_dns_models_arecord"...` count: `1`.
- `UPDATE "nautobot_dns_models_arecord"...` count: `1`.

Comparison vs hybrid v5 GenericFK preload:
- Hybrid v5 avg: `1.9240s` (`~519.8 changed/sec`)
- Hybrid v6 view cache avg: `1.1356s` (`~880.6 changed/sec`)
- Delta: `-0.7884s` average runtime (`~41.0%` faster)

Outcome:
- Keep as active candidate.
- Next likely hotspot: planning/apply stage split instrumentation to isolate remaining non-SQL overhead.

---

## Strategy test #7 (hybrid v7 stage timing instrumentation)

Change implemented:
- Added per-batch stage metrics in `ExperimentalPipelineDNSRuleEngine`:
  - `fetch`, `planning`, `apply`, `bulk_flush`, `total`.
- Added counters:
  - objects, tracking rows, pending rule calculations, pending bulk updates.
- Exposed cumulative metrics in job result payload at:
  - `result.mode.pipeline_stage_metrics`.

Single-run validation snapshot (`limit=1000`):
- `stage_seconds`:
  - fetch: `0.0230s`
  - planning: `0.1005s`
  - apply: `0.0348s`
  - bulk_flush: `0.1739s`
  - total: `0.3323s`
- Throughput (changed-record): `~511.1 changed records/sec` (1000 / 1.9566)

5-run benchmark (instrumented build):
- Run times: `1.9352`, `0.8798`, `0.8632`, `0.8974`, `0.8659`
- Average: `1.0883s`
- Median: `0.8798s`
- Throughput (changed-record, average): `~918.9 changed records/sec` (1000 / 1.0883)
- Throughput (changed-record, median): `~1136.6 changed records/sec` (1000 / 0.8798)

Outcome:
- Keep instrumentation enabled for now; it is useful for next-pass hotspot selection.
- Identified `bulk_flush` as dominant within measured pipeline stage time prior to next test.

---

## Strategy test #8 (hybrid v8 custom SQL rename flush, update path)

Change implemented:
- Replaced Django `bulk_update()` rename flush with PostgreSQL
  `UPDATE ... FROM (VALUES ...)` in `_flush_bulk_rename_updates()`.
- Kept chunking (`batch_size=500`) and one-statement-per-chunk behavior.

SQL validation (20-node run):
- `SELECT "nautobot_dns_models_arecord"...` count: `1`
- `UPDATE "nautobot_dns_models_arecord"...` count: `1`
- `SELECT "nautobot_dns_models_dnsview"...` count: `1`
- Update statement shape confirmed as:
  - `UPDATE ... SET "name" = v.new_name FROM (VALUES (...)) AS v(id, new_name) ...`

5-run benchmark:
- Run times: `1.9805`, `0.8720`, `0.8785`, `0.8737`, `0.8587`
- Average: `1.0927s`
- Median: `0.8737s`
- Throughput (changed-record, average): `~915.2 changed records/sec` (1000 / 1.0927)
- Throughput (changed-record, median): `~1144.6 changed records/sec` (1000 / 0.8737)

Stage-metric comparison vs v7 (5-run averages):
- `bulk_flush`: `0.1283s` -> `0.0121s` (substantially reduced)
- `pipeline stage total`: `0.2718s` -> `0.2040s`
- Wall-clock benchmark average: `1.0883s` -> `1.0927s` (no material gain)

Outcome:
- Keep under observation; SQL/update-phase internals improved, but end-to-end benchmark gain is negligible.
- Next likely hotspot: planning/render path and/or target iteration overhead (`jobs._iter_targets`).
- Final decision for current branch: backed out due PostgreSQL-specific SQL path; portability across supported backends takes priority.

---

## Strategy test #9 (global limit-aware `_iter_targets`, both bulk jobs)

Change implemented:
- Updated `_iter_targets()` to accept `limit` and stop yielding once the global limit is satisfied.
- Wired this into both bulk job entrypoints.
- Added queryset slicing by remaining target budget per model.

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --tenant-id "9f24ab3e-0662-4b17-835f-4e596f16a20d" \
  --job-class "ReconcileDNSBulkPipelineExperimentalJob" \
  --runs 5 \
  --performance-mode experimental \
  --pipeline-strategy hybrid \
  --source-model dcim.interface \
  --limit 1000 \
  --batch-size 1000 \
  --output-dir ".local/bench-results-greenfield"
```

Results:
- Run times: `1.9753`, `0.8803`, `0.8610`, `0.8597`, `0.9092`
- Average: `1.0971s`
- Median: `0.8803s`
- Throughput (changed-record, average): `~911.5 changed records/sec` (1000 / 1.0971)
- Throughput (changed-record, median): `~1136.0 changed records/sec` (1000 / 0.8803)

Comparison vs v8:
- v8 avg: `1.0927s` (`~915.2 changed/sec`)
- v9 avg: `1.0971s` (`~911.5 changed/sec`)
- Delta: `+0.0044s` average runtime (`~0.4%` slower, effectively neutral)

Outcome:
- Keep for correctness and reduced over-fetch at sub-scope limits.
- No meaningful throughput gain in the `limit=1000` benchmark profile.
- Next hotspot remains planning/render CPU path.

---

## Strategy test #10 (batch-scoped pre-wrap of source objects, planning path)

Change attempted:
- Added a batch-scoped cache to pre-wrap each source object once (`wrap_for_template(source_obj)`), then reused that proxy across rule planning for the object.
- Goal: reduce proxy construction overhead and enable proxy-level cached property reuse during template rendering.

Benchmark results (5 runs):
- Run times: `1.9518`, `0.8892`, `0.8846`, `0.8745`, `0.8879`
- Average: `1.0976s`
- Median: `0.8879s`
- Throughput (changed-record, average): `~911.1 changed records/sec` (1000 / 1.0976)
- Throughput (changed-record, median): `~1126.3 changed records/sec` (1000 / 0.8879)

Comparison vs prior baseline (v9):
- v9 avg: `1.0971s` (`~911.5 changed/sec`)
- pre-wrap avg: `1.0976s` (`~911.1 changed/sec`)
- Delta: `+0.0005s` average runtime (`~0.05%` slower, negligible)

Profile follow-up:
- Manual profiled run (`nautobot-jobresult-407c83c2-db0a-4460-993f-ada4d5d1a8ec.pstats`) showed no material hotspot shift in planning/render paths for this workload.

Outcome:
- Rejected and backed out.
- Rationale: no meaningful end-to-end gain under current benchmark shape; keep code simpler.

---

## Scale check (new instance, partial materialization + update stability pass)

Goal:
- Validate large-scope update throughput after seeding on the new `:19080` instance, while acknowledging current Celery time-limit constraints on one-shot 100k runs.

Attempted one-shot 100k materialization run:
- Command shape: `--runs 1 --limit 100000 --batch-size 1000 --performance-mode experimental --pipeline-strategy hybrid`
- Result: `FAILURE` after `601.8879s`
- Failure mode: `TimeLimitExceeded` (worker hard limit at ~600s)
- Outcome: cannot currently complete one-shot 100k create/materialization without raising worker limits or splitting work.

Materialization fallback used to proceed:
- Command shape: `--runs 1 --limit 20000 --batch-size 1000`
- Result: `SUCCESS`, `objects_changed=20000`, `changed_record_count=20000`
- Elapsed: `9.6042s`
- Throughput (changed-record): `~2082.4 changed records/sec` (`20000 / 9.6042`)

Observed in-system state after partial runs:
- User-reported live count: `~67k A records` available for update-path benchmarking.

67k update-path calibration (`runs=1`, `limit=67000`):
- Elapsed: `33.1799s`
- `changed_record_count=67000`
- Throughput (changed-record): `~2019.3 changed records/sec` (`67000 / 33.1799`)

67k update-path benchmark (`runs=5`, `limit=67000`):
- Run times: `28.3430`, `27.9408`, `28.2576`, `29.3451`, `28.2436`
- Average: `28.4260s`
- Median: `28.2576s`
- Throughput (changed-record, average): `~2356.2 changed records/sec` (`67000 / 28.4260`)
- Throughput (changed-record, median): `~2370.2 changed records/sec` (`67000 / 28.2576`)

20k update-path stability benchmark (`runs=5`, `limit=20000`):
- Run times: `10.2012`, `9.5658`, `9.6018`, `9.5306`, `9.5378`
- Average: `9.6874s`
- Median: `9.5658s`
- Throughput (changed-record, average): `~2064.5 changed records/sec` (`20000 / 9.6874`)
- Throughput (changed-record, median): `~2090.8 changed records/sec` (`20000 / 9.5658`)

Cross-scope note:
- 20k avg throughput (`~2064.5/sec`) is ~`12.4%` lower than 67k avg throughput (`~2356.2/sec`) in this environment.
- Throughput is therefore not flat across these tested scope sizes, so future comparisons should keep scope size fixed.

---

## Batch-size sensitivity check (67k updates, hybrid strategy)

Goal:
- Check whether increasing batch size from `1000` to `2000` changes update-path throughput at fixed scope.

Control run (`limit=67000`, `batch_size=1000`, `runs=5`):
- Run times: `27.8325`, `27.4955`, `27.5809`, `28.4186`, `27.4808`
- Average: `27.7617s`
- Median: `27.5809s`
- Throughput (changed-record, average): `~2413.4 changed records/sec` (`67000 / 27.7617`)
- Throughput (changed-record, median): `~2429.2 changed records/sec` (`67000 / 27.5809`)

Variant run (`limit=67000`, `batch_size=2000`, `runs=5`):
- Run times: `27.4557`, `27.6178`, `27.4087`, `27.5664`, `28.6406`
- Average: `27.7378s`
- Median: `27.5664s`
- Throughput (changed-record, average): `~2415.5 changed records/sec` (`67000 / 27.7378`)
- Throughput (changed-record, median): `~2430.5 changed records/sec` (`67000 / 27.5664`)

Comparison:
- Average throughput delta (`2000` vs `1000`): `+~0.09%`
- Median throughput delta (`2000` vs `1000`): `+~0.05%`
- Interpretation: effectively neutral within run-to-run noise for this environment.

Additional variant (`limit=67000`, `batch_size=4000`, `runs=5`):
- Run times: `29.6590`, `28.7235`, `29.0643`, `29.4112`, `29.0859`
- Average: `29.1888s`
- Median: `29.0859s`
- Throughput (changed-record, average): `~2295.4 changed records/sec` (`67000 / 29.1888`)
- Throughput (changed-record, median): `~2303.5 changed records/sec` (`67000 / 29.0859`)

Updated comparison:
- Average throughput delta (`4000` vs `2000`): `-~4.97%`
- Average throughput delta (`4000` vs `1000`): `-~4.89%`
- Conclusion from tested points (`1000`, `2000`, `4000`): best observed throughput remains `1000-2000`, with `4000` clearly slower in this environment.

---

## Bulk rename `bulk_update()` batch-size tuning (engine-level)

Change implemented:
- Added `ExperimentalPipelineDNSRuleEngine.BULK_RENAME_UPDATE_BATCH_SIZE` and wired `_flush_bulk_rename_updates()` to use it.
- Benchmarked `250`, `500`, and `1000` while keeping job scope fixed (`limit=67000`, job `batch_size=1000`, strategy `hybrid`, `runs=5`).

`bulk_update` batch size = `250`:
- Run times: `26.3640`, `25.8071`, `25.6174`, `26.3344`, `26.1229`
- Average: `26.0492s`
- Median: `26.1229s`
- Throughput (changed-record, average): `~2572.1 changed records/sec` (`67000 / 26.0492`)
- Throughput (changed-record, median): `~2564.8 changed records/sec` (`67000 / 26.1229`)

`bulk_update` batch size = `500`:
- Run times: `26.9641`, `27.2847`, `27.4154`, `27.1870`, `27.3912`
- Average: `27.2485s`
- Median: `27.2847s`
- Throughput (changed-record, average): `~2458.9 changed records/sec` (`67000 / 27.2485`)
- Throughput (changed-record, median): `~2455.6 changed records/sec` (`67000 / 27.2847`)

`bulk_update` batch size = `1000`:
- First launch returned transient `503` from job-run API; immediate retry succeeded.
- Run times: `27.3760`, `26.8442`, `27.4039`, `26.7001`, `27.3960`
- Average: `27.1440s`
- Median: `27.3760s`
- Throughput (changed-record, average): `~2468.3 changed records/sec` (`67000 / 27.1440`)
- Throughput (changed-record, median): `~2447.0 changed records/sec` (`67000 / 27.3760`)

Outcome:
- `250` is best of tested engine-level `bulk_update` batch sizes on this dataset.
- Average throughput delta vs `500`: `+~4.60%`.
- Average throughput delta vs `1000`: `+~4.21%`.

---

## Phase 2 trial (fingerprints on `DNSRuleRecord`) - attempted, measured, backed out

Goal:
- Evaluate additive schema + reconcile-path fingerprints to short-circuit unchanged updates.
- Keep benchmark shape fixed and use the `--change-ratio` matrix (`0/10/50/100`) for signal quality.

Implementation attempted:
- Schema:
  - Added `DNSRuleRecord.identity_fingerprint` (`BinaryField`, nullable).
  - Added `DNSRuleRecord.desired_fingerprint` (`BinaryField`, nullable).
  - Generated migration `0010_dnsrulerecord_desired_fingerprint_and_more.py`.
- Runtime:
  - Computed fingerprints with `blake2s` (16-byte digest) from identity/content keys.
  - Wrote both fingerprints during create path.
  - In pipeline reconcile, matched by identity fingerprint and skipped rename updates when desired fingerprint matched.
  - Batched tracking-row fingerprint writes via `bulk_update`.
  - Added `memoryview -> bytes` normalization for `BinaryField` comparisons after first validation runs exposed false mismatches.

Archive of this trial:
- Full patch snapshot saved at:
  - `docs/dev/archive/phase2_fingerprint_attempt_2026-03-08.patch`

Benchmark method (same as baseline matrix):
- Job: `ReconcileDNSBulkPipelineExperimentalJob`
- Mode/strategy: `experimental` + `hybrid`
- Scope: `limit=67000`, `batch_size=1000`
- Runs: `5` per ratio
- Ratio selector: deterministic `obj.id.int % 100 < N`

Pre-trial baseline medians (`.local/benchmarks/change-ratio-baseline/*-modulo`):
- `0%`: `22.5246s`
- `10%`: `23.4949s` (`~287.38 changed/sec`)
- `50%`: `25.7842s` (`~1302.81 changed/sec`)
- `100%`: `26.7954s` (`~2500.43 changed/sec`)

Fingerprint trial medians (`.local/benchmarks/change-ratio-fingerprints/*-fixed`):
- `0%`: `22.0568s`
- `10%`: `24.1374s` (`~279.73 changed/sec`)
- `50%`: `28.9134s` (`~1161.81 changed/sec`)
- `100%`: `34.9521s` (`~1916.91 changed/sec`)

Delta vs baseline (median):
- `0%`: `-0.4678s` (`-2.08%`, slight improvement).
- `10%`: `+0.6426s` (`+2.73%`, regression).
- `50%`: `+3.1292s` (`+12.14%`, regression).
- `100%`: `+8.1567s` (`+30.44%`, major regression).

Interpretation:
- Desired-fingerprint logic reduced little/no-op cost slightly, but added substantial overhead on changed paths.
- Tracking fingerprint persistence (`DNSRuleRecord` writes) dominates at higher change ratios and outweighs any reconcile short-circuit benefit.
- Current implementation does not meet the gate for keeping the change.

Decision:
- Backed out the fingerprint implementation from runtime and model.
- Deleted migration `0010_dnsrulerecord_desired_fingerprint_and_more.py`.
- Restored `DNSRuleRecord` filter behavior to pre-trial `fields="__all__"`.

Follow-up direction:
- If revisiting fingerprints, move skip boundary earlier (pre-planning/object+rule cache) rather than reconcile-only optimization.
- Keep this trial archived for reference and avoid re-running the same reconcile-stage-only approach without design changes.

---

## Rule-driven pipeline prototype (investigation track)

Goal:
- Prototype `rule -> objects` orchestration and compare with existing `object -> rules` pipeline.

Implementation:
- Added `rule_driven` strategy selector and implementation in:
  - `nautobot_dns_models/rules/pipeline_strategies.py`
  - `nautobot_dns_models/rules/engine_experimental_pipeline.py`
  - `nautobot_dns_models/jobs.py`
  - `.local/benchmark_reconcile_job_runs.py`
- Prototype safety hardening:
  - Removed mutable per-object state references from `rule_work_items`; switched to object-key lookup back into object-owned entry state.

Instrumentation/logging cleanup before final suite:
- Removed post-`ltm-2.4` pipeline stage timing/metrics accumulation from experimental pipeline job/engine.
- Reduced high-volume per-rule reconcile summary from INFO to DEBUG in `engine.py`.
- Disabled Postgres SQL statement logging (`log_statement=none`) on the benchmark DB instance.

Full benchmark suite (`rule_driven`, fixed shape):
- Scope: `limit=67000`, `batch_size=1000`, `runs=5`
- Ratios: `0/10/50/100`
- Artifacts: `.local/benchmarks/rule-driven-prototype/full-suite/*`

Results (median):
- `0%`: `19.7435s` (`0 changed/sec`)
- `10%`: `20.9382s` (`~322.47 changed/sec`)
- `50%`: `22.4785s` (`~1494.41 changed/sec`)
- `100%`: `24.5261s` (`~2731.79 changed/sec`)

Comparison vs earlier `rule_driven` runs with profiling-stage metrics/log-heavy behavior still enabled:
- Comparable slices available: `10%` and `100%`.
- `10%` median:
  - before: `23.0274s` (`~293.22 changed/sec`)
  - after:  `20.9382s` (`~322.47 changed/sec`)
  - delta: `-2.0892s` (`~+9.98%` changed/sec)
- `100%` median:
  - before: `26.8531s` (`~2495.06 changed/sec`)
  - after:  `24.5261s` (`~2731.79 changed/sec`)
  - delta: `-2.3271s` (`~+9.49%` changed/sec)

Notes on interpretation:
- The improvement combines multiple changes (less runtime logging, removed pipeline stage-metrics/timing overhead, and DB `log_statement=none`), not rule-driven orchestration alone.
- Prior hybrid baselines were gathered under different logging conditions; re-running hybrid under the same low-logging setup is required for an apples-to-apples strategy decision.

---

## Strategy test #11 (rule_driven, PostgreSQL `UPDATE ... FROM (VALUES ...)` A/B, 67k scope)

Goal:
- Measure isolated impact of PostgreSQL rename flush fast path against ORM-only `bulk_update` at fixed large scope.
- Keep architecture, strategy, and benchmark shape identical; vary only rename flush implementation.

Implementation under test:
- Fast-path variant (`A`): Postgres-only `UPDATE ... FROM (VALUES ...)` in `_flush_bulk_rename_updates()`.
- Control variant (`B`): forced ORM `bulk_update(..., ["name"])` only (fast path disabled temporarily).
- After measurement, runtime code was restored to ORM-only path (backed out) per decision.

Benchmark method:
- Nautobot: `http://localhost:19080`
- Job: `ReconcileDNSBulkPipelineExperimentalJob`
- Mode/strategy: `experimental` + `rule_driven`
- Scope: `limit=67000`, `batch_size=1000`
- Runs: `5` per ratio
- Ratios tested: `10%` and `100%`
- Rule: `32ebf50a-9b15-430d-93d9-7d137204d868`

SQL confirmation for fast-path variant:
- With DB SQL logging enabled, run window logs showed:
  - `UPDATE "nautobot_dns_models_arecord" AS target SET "name" = vals.desired_name FROM (VALUES ...) ...`
- No fallback warning observed in worker logs during that confirmed run window.

Results (median, clean sets):
- `A_r10` (fast path): `24.8865s`, `~271.31 changed/sec` (`6752` changed)
- `B_r10` (ORM-only): `24.8147s`, `~272.10 changed/sec` (`6752` changed)
- Delta (`A` vs `B`, `10%`): `-0.29%` changed/sec (effectively neutral/slightly worse)

- `A_r100` (fast path): `25.8685s`, `~2590.02 changed/sec` (`67000` changed)
- `B_r100` (ORM-only): `29.6772s`, `~2257.62 changed/sec` (`67000` changed)
- Delta (`A` vs `B`, `100%`): `+14.72%` changed/sec (`-3.8087s` median elapsed)

Interpretation:
- Under high-change workloads, set-based SQL rename flush materially improves update throughput.
- Under low-change workloads (`10%`), rename flush is not dominant; signal is neutral.
- Benefit profile is therefore workload-dependent and strongest when rename volume is large.

Decision:
- Documented improvement is real for heavy-change runs, but PostgreSQL-specific SQL path was backed out.
- Active runtime path remains backend-agnostic ORM `bulk_update` for portability and maintenance simplicity.
- This section remains as archived evidence for potential future opt-in/PostgreSQL-only fast path work.
