# Reconcile Performance Exploration Backlog

Purpose: capture candidate experiments and eventual optimization paths before they are moved into the benchmark tally.

## How to use this document

- Add ideas here first, even if they are speculative.
- When an idea is tested, link the result in `docs/dev/reconcile_update_performance_tally.md`.
- Keep entries small: hypothesis, measurement plan, expected upside, and risks.

## Ideas to explore

### 1) Follow-up learning pass: EXPLAIN at larger scopes and reuse profiles

- **Status:** pending
- **Hypothesis:** the relative value of `DISTINCT ip_address_id` vs direct `interface -> rel -> ip` join changes with larger scope and with higher/lower IP reuse.
- **Why:** current 1000-interface sample has `rel_rows == distinct_ip_ids`, so dedupe offered no benefit.
- **Plan:**
  - Run both query shapes with `EXPLAIN (ANALYZE, BUFFERS)` at larger scope (for example 10k interfaces).
  - Repeat in at least one scope with high IP reuse and one with low IP reuse.
  - Capture `Execution Time`, `Buffers`, row counts, and join strategy.
  - Record whether dedupe (`DISTINCT`) helps or just adds aggregate overhead in each case.
- **Expected upside:** stronger confidence in which bulk-IP-fetch SQL shape should back future engine changes.
- **Risks/notes:** planner choices can vary by data distribution and cache warmth; compare warm/warm and cold/cold runs consistently.

### 2) Benchmark `view_template` and `zone_template` heavy paths (deferred)

- **Status:** pending (defer until current hotspot pass is complete)
- **Hypothesis:** throughput and query mix can differ materially when `view_template` and/or `zone_template` are dynamic, especially with `ip` references in templates.
- **Why:** current benchmark rule shape is narrow; recent wins were measured primarily on update-heavy A-record rename behavior.
- **Plan:**
  - Add benchmark rules that exercise:
    - static view + static zone
    - dynamic view (including `ip` usage) + static zone
    - static view + dynamic zone (including `ip` usage)
    - dynamic view + dynamic zone
  - For each shape, run 5-run benchmarks and capture SQL logs for at least one run.
  - Compare changed-record throughput and query counts against current hybrid baseline.
- **Expected upside:** validates whether current optimizations generalize to template-heavy rule shapes and identifies any template-specific regressions.
- **Risks/notes:** template complexity and data variability can dominate runtime; keep rule and scope controls consistent across comparisons.

### 3) Re-test indexes and critical query shapes at ~1MM `DNSRuleRecord` rows

- **Status:** in progress
- **Hypothesis:** query/index choices that are neutral at current scale may become material at 1MM-row scale, especially GFK-related lookups and reconcile join/filter paths.
- **Why:** recent EXPLAIN tests showed negligible difference for composite GFK index at current row counts; this may not hold at much larger cardinality.
- **Plan:**
  - Seed to ~1,000,000 rows in `nautobot_dns_models_dnsrulerecord` (and representative DNS record tables).
  - Benchmark key query families before/after candidate indexes:
    - `(dns_record_content_type_id, dns_record_object_id)` composite index tests.
    - current reconcile path filters/joins used by hybrid pipeline.
    - any high-frequency lookup/update statements observed in SQL logs.
  - Capture `EXPLAIN (ANALYZE, BUFFERS)` for each query shape with and without indexes.
  - Include write-path cost checks (insert/update/delete impact) for added indexes.
  - Re-run 5-run reconcile benchmark at 1MM scale and compare changed-record throughput.
- **Expected upside:** data-backed index strategy for large deployments; avoid premature indexes while preserving scale-readiness.
- **Risks/notes:** larger-scale tests require careful cache-control and repeatability; compare warm/warm and cold/cold runs and record dataset distribution assumptions.

Interim findings (2026-03-08):
- Seeded benchmark dataset to `100000` interfaces with one IPv4 and one IP assignment per interface for scale testing.
- Ran A/B `EXPLAIN (ANALYZE, BUFFERS)` on `(dns_record_content_type_id, dns_record_object_id)` index candidate.
- For tested query shapes, planner changes were minor and wall-clock differences stayed in sub-millisecond/noise territory at this scale.
- Practical projection: index may become more useful around 1MM-2MM rows for selective point/small-set lookups, but is unlikely to be a major reconcile-throughput lever by itself.
- Current default decision: keep the index dropped for now; revisit at higher cardinality with the same A/B method.

