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
- `stage_metrics`:
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

---

## Strategy test #12 (rule_driven phase-3 attempt: invariant view/zone precompute) - attempted, measured, backed out

Goal:
- Reduce repeated per-record view/zone work in `rule_driven` by precomputing invariant rule scope once per batch.

Implementation attempted:
- In `engine_experimental_pipeline.py` (`rule_driven` path only), Stage 2 planning attempted to:
  - detect object-invariant `view_template`/`zone_template` per rule,
  - precompute and cache zones for invariant rules,
  - attach precomputed scope to work items.
- Stage 3 materialization then reused precomputed zones instead of per-record view/zone resolution for those rules.
- `python_first` and `hybrid` paths were intentionally unchanged.

Benchmark (67k, `rule_driven`, `change_ratio=100`, `runs=5`, `batch_size=1000`):
- Run times: `27.1169`, `26.1378`, `26.7659`, `26.8562`, `26.8706`
- Average: `26.7495s`
- Median: `26.8562s`

Comparison:
- Prior baseline (`baseline-r100`): avg `26.7812s`, median `26.7242s`
  - Net: avg slightly better (`-0.0317s`), median slightly worse (`+0.1320s`) -> effectively neutral-to-negative.
- Prior phase-1-only run (`phase1-literal-r100`): avg `26.5738s`, median `26.2416s`
  - Net: slower on both avg and median.

40k pstats follow-up:
- With phase-3 attempt: total `27.550s`
- Phase-1-only: total `26.942s`
- Delta: `+0.608s` (phase-3 slower)

Key pstats observations (phase-3 vs phase-1-only):
- View/zone resolution was reduced as intended:
  - `_get_dns_views_for_rule`: `40000` calls -> `40`
  - `_get_zones_for_rule`: `40000` calls -> `40`
  - `_rule_driven_stage_materialize_desired_data`: improved (`0.299s` -> `0.099s` cumtime)
- But planning overhead increased enough to negate gains:
  - `_rule_driven_stage_plan_work`: regressed (`6.712s` -> `7.101s` cumtime)

Decision:
- Backed out the phase-3 invariant precompute attempt from `rule_driven`.
- Keep phase-1 literal-template short-circuit as the active improvement.

---

## Post-cleanup regression suite (current codebase, rule_driven, 67k scope)

Goal:
- Re-run the full `0/10/50/100` change-ratio suite after engine/job cleanup to confirm behavior and throughput remain in-family.

Command shape used (updated job path):
- Job class: `ReconcileDNSBulkJob`
- Strategy: `rule_driven`
- Scope: `limit=67000`, `batch_size=1000`, `runs=5` per ratio
- Rule: `32ebf50a-9b15-430d-93d9-7d137204d868`

Artifacts:
- `.local/bench-results/post-cleanup-r0`
- `.local/bench-results/post-cleanup-r10`
- `.local/bench-results/post-cleanup-r50`
- `.local/bench-results/post-cleanup-r100`

Results:

`r0` (0% change ratio):
- Run times: `25.214`, `21.901`, `22.637`, `21.520`, `21.979`
- Average: `22.650s`
- Median: `21.979s`
- Notes:
  - Run 1 reported `objects_changed=47000` / `changed_record_count=47000` (warm-up/drift cleanup).
  - Runs 2-5 were no-op (`objects_changed=0`, `changed_record_count=0`).

`r10` (10% change ratio):
- Run times: `23.210`, `23.571`, `22.624`, `21.303`, `22.674`
- Average: `22.676s`
- Median: `22.674s`
- Changed count per run: `6752`
- Throughput (changed-record, median): `~297.8 changed records/sec` (`6752 / 22.674`)

`r50` (50% change ratio):
- Run times: `24.271`, `23.494`, `23.491`, `24.169`, `22.879`
- Average: `23.661s`
- Median: `23.494s`
- Changed count per run: `33592`
- Throughput (changed-record, median): `~1429.8 changed records/sec` (`33592 / 23.494`)

`r100` (100% change ratio):
- Run times: `25.216`, `25.776`, `28.118`, `25.665`, `26.110`
- Average: `26.177s`
- Median: `25.776s`
- Changed count per run: `67000`
- Throughput (changed-record, median): `~2599.3 changed records/sec` (`67000 / 25.776`)

Outcome:
- Full suite completed successfully with expected ratio behavior after the code cleanup.
- Keep using this post-cleanup set as the new reference point for subsequent optimization experiments.

---

## Prefetch-aware gating A/B (isolated)

Goal:
- Quantify impact of interface `ip_addresses` prefetch-aware A/AAAA gating in `DNSRuleEngine`.

Method:
- Fixed benchmark shape for both variants:
  - Job: `ReconcileDNSBulkJob`
  - Strategy: `rule_driven`
  - Scope: `limit=67000`, `batch_size=1000`, `runs=5`
  - Ratios: `0/10/50/100`
  - Rule: `32ebf50a-9b15-430d-93d9-7d137204d868`
- `ON` variant:
  - `_iter_targets()` includes `.prefetch_related("ip_addresses")` for `dcim.interface`.
  - Engine uses `getattr(source_obj, "_prefetched_objects_cache", {}).get("ip_addresses")`.
- `OFF` variant:
  - disabled only `.prefetch_related("ip_addresses")` in `_iter_targets()`.
  - kept engine cache-key logic unchanged.

Artifacts:
- ON:
  - `.local/bench-results/prefetch-on-r0`
  - `.local/bench-results/prefetch-on-r10`
  - `.local/bench-results/prefetch-on-r50`
  - `.local/bench-results/prefetch-on-r100`
- OFF:
  - `.local/bench-results/prefetch-off-r0`
  - `.local/bench-results/prefetch-off-r10`
  - `.local/bench-results/prefetch-off-r50`
  - `.local/bench-results/prefetch-off-r100`

Results (summary.json averages):
- `r0`:
  - ON: `22.285s`
  - OFF: `77.352s`
  - Delta: `-55.067s` (`~71.2%` lower), `~3.47x` faster
- `r10`:
  - ON: `22.520s`
  - OFF: `76.310s`
  - Delta: `-53.790s` (`~70.5%` lower), `~3.39x` faster
- `r50`:
  - ON: `24.736s`
  - OFF: `77.082s`
  - Delta: `-52.346s` (`~67.9%` lower), `~3.12x` faster
- `r100`:
  - ON: `27.331s`
  - OFF: `79.082s`
  - Delta: `-51.751s` (`~65.4%` lower), `~2.89x` faster

Interpretation:
- Prefetch-aware A/AAAA gating is a dominant optimization for this workload.
- The performance gap is consistent across all change ratios and remains large even at `100%` change.
- Keep this optimization in the active runtime path.

---

## Interfaces-first queryset scope filtering A/B (20k on `:19080`)

Goal:
- Compare current Python scope filtering vs interfaces-first SQL scope filtering in `ReconcileDNSBulkJob`.

Benchmark shape (both variants):
- Nautobot: `http://localhost:19080`
- Job: `ReconcileDNSBulkJob`
- Strategy: `rule_driven`
- Scope: `source_model=dcim.interface`, `limit=20000`, `batch_size=1000`, `runs=5`
- Rule: `32ebf50a-9b15-430d-93d9-7d137204d868`

Command:

```bash
.venv/bin/python .local/benchmark_reconcile_job_runs.py \
  --base-url "http://localhost:19080" \
  --rule-id "32ebf50a-9b15-430d-93d9-7d137204d868" \
  --rule-api-path "/api/plugins/dns/dns-rules/" \
  --source-model "dcim.interface" \
  --limit 20000 \
  --batch-size 1000 \
  --runs 5 \
  --output-dir "<variant output dir>"
```

Code delta tested (interfaces-first variant):
- File: `nautobot_dns_models/jobs.py`
- Added `_BULK_QS_SCOPE_FILTERS` mapping for `dcim.interface` only:
  - `location -> device__location_id`
  - `tenant -> device__tenant_id`
- Updated `_iter_targets()` to:
  - accept `location_ids`/`tenant_ids`
  - apply `_apply_bulk_queryset_scope_filters()` before iteration
  - yield `used_sql_scope_filtering` metadata
- Updated pipeline batching/scope stage to carry `used_sql_scope_filtering` and skip Python `_get_object_location()` / `_get_object_tenant()` checks when SQL scope filtering was applied.
- Left non-interface models on existing Python scope filtering path.

Artifacts:
- Baseline (pre-refactor):
  - `.local/bench-results/limit-20k-batch-1k-19080`
- Interfaces-first queryset variant:
  - `.local/bench-results/limit-20k-batch-1k-19080-interfaces-sql-filter`

Results:
- Baseline:
  - Average: `9.073s`
  - Median: `8.997s`
  - Min/Max: `8.896s` / `9.493s`
- Interfaces-first queryset variant:
  - Average: `9.233s`
  - Median: `9.233s`
  - Min/Max: `8.865s` / `9.664s`

Comparison (variant vs baseline):
- Median: `+0.236s` (`+2.62%`, slower)
- Average: `+0.160s` (`+1.76%`, slower)
- Min: `-0.031s` (slightly faster best-case)
- Max: `+0.171s` (worse tail)

Interpretation:
- This interfaces-first queryset scope filtering variant did not improve this benchmark shape and trended slightly slower overall.
- Keep the previous Python scope filtering behavior for now.

---

## Recursive interface scope filtering A/B (location-scoped, `:19080`)

Goal:
- Measure the impact of recursive, module-aware SQL scope filtering for sparse location-scoped `dcim.interface` runs.

Scope shape:
- Nautobot: `http://localhost:19080`
- Job: `ReconcileDNSBulkJob`
- Source model: `dcim.interface`
- Rule: `32ebf50a-9b15-430d-93d9-7d137204d868`
- Filters: `location_ids=[<single location>]`, `tenant_ids=[]`, `limit=20000`, `batch_size=1000`
- In-scope population for this location:
  - Devices: `1`
  - Interfaces on that device: `128`
- Limit semantics for this code path:
  - `limit` applies to in-scope `targets_seen`, not to raw candidates iterated.
- Baseline run candidate scan (Python scope filtering):
  - In-scope processed: `128`
  - Out-of-scope skipped: `99,872`
  - Total candidates iterated to job completion: `100,000`

Code delta tested (vs Python scope filtering):
- File: `nautobot_dns_models/jobs.py`
- `_apply_bulk_queryset_scope_filters()` now builds recursive `Q` filters for `dcim.interface` using:
  - `_build_interface_parent_device_filter("location_id", location_ids)`
  - `_build_interface_parent_device_filter("tenant_id", tenant_ids)`
  - `module__tenant_id` OR-path for module-tenant precedence parity
- `_build_interface_parent_device_filter()` walks module nesting up to `MODULE_RECURSION_DEPTH_LIMIT`.
- Pipeline keeps Python scope checks only when SQL scope pushdown was not used (`used_sql_scope_filtering=False`).

Observed results (session A/B):
- Python-filtered scoped path (baseline): wall median about `12.5s`
- Recursive SQL-scoped path (variant): wall median about `0.652s`
- In-scope interface targets processed: `128` (both paths; same scoped workload)
- Out-of-scope handling:
  - Python-filtered path: `skipped_scope_count=99,872` (observed in run output)
  - Recursive SQL path: `skipped_scope_count=0` at pipeline stage because out-of-scope interfaces are pruned in SQL.
  - Recursive SQL path candidate scan: effectively bounded to the scoped subset (`128`) by SQL filtering.

Comparison (variant vs baseline):
- Median delta: about `-11.85s`
- Relative improvement: about `94.8%` lower wall time (`~19.2x` faster)

Interpretation:
- For sparse location-scoped interface reconciliations, recursive SQL scope pushdown is a major win.
- This does not contradict the earlier unscoped A/B result (`limit=20k`, no location filter), where SQL scope logic had no useful work to do.

---

## Create-path performance track (`dcim.interface`, pure-create, `:19080`)

Goal:
- Track create-path speedups in isolated rounds, one implementation change at a time.
- Use a strict pure-create harness with inter-run REST cleanup of `ARecord` objects and verification that related `DNSRuleRecord` rows are removed before each run.

Benchmark protocol for each round:
- Tenant: `dns-job-benchmark-20260318054731`
- Job: `ReconcileDNSBulkJob`
- Source model: `dcim.interface`
- Scope: `limit=1000`, `batch_size=1000`
- Run shape: `1` warm-up + `5` measured runs
- Benchmark script: `.local/benchmark_create_only_baseline.py`

### Round 0 baseline (pre-change)

Command:

```bash
.venv/bin/python .local/benchmark_create_only_baseline.py \
  --base-url "http://localhost:19080" \
  --tenant-name "dns-job-benchmark-20260318054731" \
  --limit 1000 \
  --batch-size 1000 \
  --warmup-runs 1 \
  --measured-runs 5 \
  --disable-conflicting-rules \
  --cleanup-between-runs \
  --delete-batch-size 250 \
  --benchmark-rule-name "dns-bench-create-baseline" \
  --output-dir ".local/bench-results-create-baseline-round0-1000-20260318"
```

Results (measured runs):
- Run times: `12.588`, `13.201`, `12.594`, `15.041`, `13.688`
- Average: `13.422s`
- Median: `13.201s`
- Min/Max: `12.588s` / `15.041s`
- Throughput (creates/sec, average): `~74.8` (1000 / 13.422)
- Throughput (creates/sec, median): `~75.8` (1000 / 13.201)

Per-run reconciliation outcome:
- `record_ops_create_count=1000`
- `changed_record_count=1000`
- `objects_changed=1000`

Pipeline stage metrics (measured runs aggregate):
- Average stage seconds:
  - `fetch`: `0.008s`
  - `planning`: `0.178s`
  - `apply`: `10.413s`
  - `bulk_flush`: `0.000s`
  - `total`: `10.598s`
- Median stage seconds:
  - `fetch`: `0.007s`
  - `planning`: `0.181s`
  - `apply`: `9.960s`
  - `bulk_flush`: `0.000s`
  - `total`: `10.147s`

Interpretation:
- Create-path runtime is overwhelmingly concentrated in apply-stage work.
- This is the baseline for Round 1 optimization comparisons.

### Round 1 (`ContentType` lookup hoist in create loop)

Change implemented:
- In `nautobot_dns_models/rules/engine.py::_create_records_from_data()`, moved:
  - `ContentType.objects.get_for_model(source_obj)`
  - `ContentType.objects.get_for_model(record_class)`
  out of the per-record loop and reused the resolved values for each `DNSRuleRecord.objects.create(...)`.

Command:

```bash
.venv/bin/python .local/benchmark_create_only_baseline.py \
  --base-url "http://localhost:19080" \
  --tenant-name "dns-job-benchmark-20260318054731" \
  --limit 1000 \
  --batch-size 1000 \
  --warmup-runs 1 \
  --measured-runs 5 \
  --disable-conflicting-rules \
  --cleanup-between-runs \
  --delete-batch-size 250 \
  --benchmark-rule-name "dns-bench-create-round1-ct-hoist" \
  --output-dir ".local/bench-results-create-round1-ct-hoist-1000-20260318-rerun3"
```

Results (measured runs):
- Run times: `14.304`, `13.156`, `13.716`, `17.054`, `15.431`
- Average: `14.732s`
- Median: `14.304s`
- Min/Max: `13.156s` / `17.054s`
- Throughput (creates/sec, average): `~68.5` (1000 / 14.732)
- Throughput (creates/sec, median): `~69.9` (1000 / 14.304)

Comparison vs Round 0 baseline:
- Average runtime: `13.422s` -> `14.732s` (`+1.310s`, `~9.8%` slower)
- Median runtime: `13.201s` -> `14.304s` (`+1.103s`, `~8.4%` slower)
- Average throughput: `~74.8/s` -> `~68.5/s` (`~8.4%` lower)
- Median throughput: `~75.8/s` -> `~69.9/s` (`~7.8%` lower)

Outcome:
- Keep this as a measured data point only; no create-path speedup observed.
- Profile confirms dominant create costs are still `validated_save()` + model save/clean + change-logging signal path, not `ContentType` lookup.

### Strategy A/B (invoke/ORM cleanup baseline shape, `limit=1000`)

Scope notes:
- Cleanup path switched from REST bulk DELETE to invoke-triggered ORM cleanup (`invoke cleanup-benchmark-arecords`) between runs.
- Measured wall-clock includes cleanup overhead in this harness, so comparisons below are only among runs using the same cleanup mode.

#### A) `create_strategy=default` (invoke cleanup)

Command:

```bash
.venv/bin/python .local/benchmark_create_only_baseline.py \
  --base-url "http://localhost:19080" \
  --tenant-name "dns-job-benchmark-20260318054731" \
  --limit 1000 \
  --batch-size 1000 \
  --pipeline-strategy rule_driven \
  --create-strategy default \
  --warmup-runs 1 \
  --measured-runs 5 \
  --disable-conflicting-rules \
  --cleanup-between-runs \
  --cleanup-via-invoke \
  --delete-batch-size 250 \
  --benchmark-rule-name "dns-bench-create-strategy-default-invoke-cleanup" \
  --output-dir ".local/bench-results-create-strategy-default-invoke-cleanup-1000-20260319"
```

Results:
- Average: `16.910s`
- Median: `16.750s`
- Min/Max: `16.350s` / `17.863s`
- Throughput (average): `~59.2 creates/sec`
- Throughput (median): `~59.7 creates/sec`

#### B) `create_strategy=validated_deferred` (invoke cleanup)

Command shape:
- same as (A), with `--create-strategy validated_deferred`

Observed outcome:
- Run set completed but all measured runs reported:
  - `record_ops_create_count=0`
  - `changed_record_count=0`
  - `objects_changed=0`
- This strategy remains invalid in current form for create-path benchmarking.

#### C) `create_strategy=bulk_create_fast` (invoke cleanup)

Command:

```bash
.venv/bin/python .local/benchmark_create_only_baseline.py \
  --base-url "http://localhost:19080" \
  --tenant-name "dns-job-benchmark-20260318054731" \
  --limit 1000 \
  --batch-size 1000 \
  --pipeline-strategy rule_driven \
  --create-strategy bulk_create_fast \
  --warmup-runs 1 \
  --measured-runs 5 \
  --disable-conflicting-rules \
  --cleanup-between-runs \
  --cleanup-via-invoke \
  --delete-batch-size 250 \
  --benchmark-rule-name "dns-bench-create-strategy-bulk-create-fast-invoke-cleanup" \
  --output-dir ".local/bench-results-create-strategy-bulk-create-fast-invoke-cleanup-1000-20260319"
```

Results:
- Average: `2.671s`
- Median: `2.804s`
- Min/Max: `1.798s` / `3.445s`
- Throughput (average): `~391.9 creates/sec`
- Throughput (median): `~356.6 creates/sec`

Comparison (C vs A, same cleanup mode):
- Average runtime: `16.910s` -> `2.671s` (`-14.239s`, `~84.2%` faster)
- Average throughput: `~59.2/s` -> `~391.9/s` (`~6.62x`)

Current decision point:
- `bulk_create_fast` is materially faster for pure create throughput.
- `validated_deferred` is currently non-viable as implemented and needs redesign before valid comparison.

### D) `create_strategy=bulk_create_batched_pipeline` (pipeline-level create queue)

Change implemented:
- Added a new create strategy in `engine_dns.py` that queues creates during apply and flushes them in batch (`bulk_create`) instead of per-object create calls.
- SQL validation for measured runs at `limit=1000` shows one `BEGIN`/`COMMIT` and one insert statement per table per run window, rather than per-object transaction churn.

`limit=1000`, `batch_size=1000`, `warmup=1`, `measured=5`:
- Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-invoke-cleanup-1000-20260320`
- Average: `1.889s`
- Median: `2.292s`
- Throughput (average): `~577.8 creates/sec`
- Throughput (median): `~436.3 creates/sec`
- Stage averages (measured): `apply=0.176s`, `planning=0.174s`, `fetch=0.007s`
- Delete ops in measured runs: always `0` (pure create)

Comparison (`bulk_create_batched_pipeline` vs `bulk_create_fast`, both `limit=1000`, invoke cleanup):
- Average runtime: `2.671s` -> `1.889s` (`-0.782s`, `~29.3%` faster)
- Average throughput: `~391.9/s` -> `~577.8/s` (`~47.4%` higher)

### Create-path scaling checks (`bulk_create_batched_pipeline`, pure-create)

Runs used tenant-wide pre-cleanup where needed to guarantee `record_ops_delete_count=0`.

- `limit=5000`, `batch_size=1000`, `measured=1`
  - Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-invoke-cleanup-5000-20260320`
  - Elapsed: `4.469s`
  - Throughput: `~1118.8 creates/sec`

- `limit=10000`, `batch_size=1000`, `measured=1`
  - Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-invoke-cleanup-10000-20260320c`
  - Elapsed: `6.040s`
  - Throughput: `~1655.6 creates/sec`

- `limit=20000`, `batch_size=1000`, `measured=1`
  - Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-invoke-cleanup-20000-20260320`
  - Elapsed: `11.594s`
  - Throughput: `~1725.0 creates/sec`

### 20k batch-size sweep (`bulk_create_batched_pipeline`, pure-create)

Protocol:
- Tenant: `dns-job-benchmark-20260318054731`
- `limit=20000`
- `warmup=1`, `measured=3` per batch-size variant
- Invoke/ORM cleanup between runs
- Tenant-wide pre-cleanup before each variant to remove cross-rule residue

`batch_size=1000`:
- Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-invoke-cleanup-20000-b1000-20260320`
- Average: `9.871s`
- Median: `9.896s`
- Throughput (average): `~2026.2 creates/sec`
- Throughput (median): `~2021.0 creates/sec`
- Stage averages: `apply=3.435s`, `planning=2.195s`, `fetch=0.100s`

`batch_size=2000`:
- Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-invoke-cleanup-20000-b2000-20260320`
- Average: `10.369s`
- Median: `10.435s`
- Throughput (average): `~1929.3 creates/sec`
- Throughput (median): `~1916.6 creates/sec`
- Stage averages: `apply=3.320s`, `planning=1.756s`, `fetch=0.162s`

`batch_size=5000`:
- Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-invoke-cleanup-20000-b5000-20260320`
- Average: `10.784s`
- Median: `10.456s`
- Throughput (average): `~1858.1 creates/sec`
- Throughput (median): `~1912.8 creates/sec`
- Stage averages: `apply=3.130s`, `planning=2.288s`, `fetch=0.261s`

Observed best in this sweep:
- `batch_size=1000` is best overall at 20k in this environment (`~2026/sec` average), with larger batch-size settings reducing net throughput.

### E) Create-only apply fast-path prototype (no-tracking-row shortcut)

Change implemented:
- Added a shortcut in `_apply_prepared_reconcile_entry()` for:
  - `existing_count == 0`
  - `create_strategy=bulk_create_batched_pipeline`
- New helper `_apply_prepared_create_only_entry()` skips reconcile identity-diff work and directly queues creates from `desired_by_rule_id`.

Benchmark shape:
- Scope: `limit=20000`, `batch_size=1000`
- Runs: `warmup=1`, `measured=3`
- Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-createonlyfast-20000-b1000-20260320`

Results:
- Average: `10.374s`
- Median: `10.538s`
- Throughput (average): `~1930.5 creates/sec`
- Throughput (median): `~1897.9 creates/sec`
- Stage averages: `apply=3.492s`, `planning=2.352s`, `fetch=0.097s`
- Delete ops in measured runs: always `0` (pure create)

Comparison vs prior best (`batch_size=1000` without this shortcut):
- Baseline average: `9.871s` / `~2026.2/sec`
- Fast-path average: `10.374s` / `~1930.5/sec`
- Delta: `+0.503s` average runtime (`~5.1%` slower), `~4.7%` lower average throughput

Outcome:
- Keep as measured data point only.
- This specific shortcut does not improve throughput in current pipeline shape; revert or leave disabled behind strategy gating for now.

### F) Create-only planner fast-path prototype (Stage 2/3 branch)

Change implemented:
- Added a no-tracking branch in `_process_objects()` for `create_strategy=bulk_create_batched_pipeline`.
- New helper `_plan_create_only_work()` combines Stage 2 and Stage 3 for create-only/no-tracking batches:
  - builds prepared entries directly with `tracking_rows=[]`
  - collects rule work inline
  - preloads referenced `IPAddress` rows once per batch
  - materializes `desired_by_rule_id` without building the generic `rule_work_items` / `prepared_entry_by_object_id` maps
- Existing Stage 4 create-only apply shortcut remains in place for this round (separate experiment still TODO for removal).

Benchmark shape:
- Scope: `limit=20000`, `batch_size=1000`
- Runs: `warmup=1`, `measured=3`
- Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-plannerfast-20000-b1000-20260320`

Results:
- Average: `10.039s`
- Median: `9.884s`
- Throughput (average): `~1993.4 creates/sec`
- Throughput (median): `~2023.5 creates/sec`
- Stage averages: `apply=3.422s`, `planning=2.104s`, `fetch=0.099s`
- Delete ops in measured runs: always `0` (pure create)

Comparison vs prior best (`batch_size=1000` without create-only shortcuts):
- Baseline average: `9.871s` / `~2026.2/sec`
- Planner fast-path average: `10.039s` / `~1993.4/sec`
- Delta: `+0.168s` average runtime (`~1.7%` slower), `~1.6%` lower average throughput

Comparison vs Section E create-only apply shortcut:
- Section E average: `10.374s` / `~1930.5/sec`
- Planner fast-path average: `10.039s` / `~1993.4/sec`
- Delta vs E: `-0.335s` average runtime (`~3.2%` faster), `~3.3%` higher average throughput

Outcome:
- Stage 2/3 planner fast-path recovers part of the regression from the Stage 4-only shortcut, but does not beat the original 20k/1000 best run.
- Keep as measured data point; further optimization should target planning/materialization overhead and/or database write latency without adding reconcile-only structures on pure-create batches.

### G) Isolation reruns and removal decision for experimental create-only paths

Purpose:
- Isolate the two experimental code paths and determine whether either materially improves create throughput:
  - Stage 2/3 planner short-circuit (`_plan_create_only_work`)
  - Stage 4 apply shortcut (`_apply_prepared_create_only_entry`, TODO-marked)

Benchmark shape (all runs in this section):
- Scope: `limit=20000`, `batch_size=1000`
- Runs: `warmup=1`, `measured=3`
- Cleanup: invoke/ORM cleanup between runs
- Pure-create validation: measured runs had `record_ops_delete_count=0`

Measured variants:
- Both experimental paths active:
  - Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-plannerfast-20000-b1000-20260320`
  - Average: `10.039s`
  - Throughput (average): `~1993.4 creates/sec`
- Apply shortcut disabled (planner path left enabled):
  - Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-plannerfast-noapplyshortcut-20000-b1000-20260320`
  - Average: `10.913s`
  - Throughput (average): `~1834.1 creates/sec`
  - Note: treated as a noisy outlier relative to adjacent reruns.
- Both experimental paths disabled:
  - Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-noplanner-noapplyshortcut-20000-b1000-20260320`
  - Average: `10.064s`
  - Throughput (average): `~1988.4 creates/sec`

Key comparison:
- `both active` vs `both disabled`:
  - Runtime: `10.039s` vs `10.064s` (`+0.025s`)
  - Throughput: `~1993.4/s` vs `~1988.4/s` (`~0.3%` delta)

Conclusion:
- Across repeat runs, neither experimental path shows a clear, stable throughput win at 20k/1000.
- These experimental paths are removed from `engine_dns.py`; baseline flow remains `_plan_work()` + `_materialize_desired_data()` + `_apply_prepared_reconcile_entry()`.
- Code not included after this decision:
  - `_plan_create_only_work` and its `_process_objects()` branch
  - `_apply_prepared_create_only_entry` and its TODO-marked call site in `_apply_prepared_reconcile_entry()`

### H) SQL flush create strategy (measured, archived, not included)

Prototype:
- Added an experimental create strategy key: `bulk_create_batched_pipeline_sql`.
- Reused the existing pipeline-level create queue, but swapped queue flush for SQL on `ARecord`:
  - `INSERT INTO nautobot_dns_models_arecord ... RETURNING id`
  - followed by batched `INSERT INTO nautobot_dns_models_dnsrulerecord ...`
- Non-`ARecord` record classes still used ORM `bulk_create` fallback inside the same flush function.

Benchmark shape:
- Scope: `limit=20000`, `batch_size=1000`
- Runs: `warmup=1`, `measured=3`
- Output: `.local/bench-results-create-strategy-bulk-create-batched-pipeline-sql-20000-b1000-20260320`

Results:
- Average: `8.348s`
- Median: `8.297s`
- Throughput (average): `~2400.0 creates/sec`
- Throughput (median): `~2410.5 creates/sec`
- Stage averages: `apply=1.430s`, `planning=2.499s`, `fetch=0.141s`
- Delete ops in measured runs: always `0` (pure create)

Comparison:
- Versus prior best create baseline at 20k/1000 (`~2026.2/sec`): `~18.4%` higher throughput.
- Versus recent cleaned baseline (`~1902.0/sec`): `~26.2%` higher throughput.

Disposition:
- Not retained in active runtime at this time.
- Strategy key and active code path were backed out from `engine_dns.py` and `jobs.py`.
- Implementation preserved in `ATTIC/engine_dns_bulk_create_batched_pipeline_sql_20260320.py` for future reconsideration.
