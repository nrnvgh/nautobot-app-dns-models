# Patch TODO

- [x] `fix-aaaa-reconcile-key`
  - Issue: AAAA reconciliation key uses `ARecord`.
  - Done when: existing `AAAARecord` entries are preserved during reconciliation.

- [x] `fix-vm-tenant-fallback`
  - Issue: VM tenant fallback to cluster tenant is bypassed.
  - Done when: a VM with no tenant resolves tenant from its cluster.

- [x] `fix-zone-fixed-reference`
  - Issue: engine references undefined `rule.zone_fixed`.
  - Done when: zone resolution no longer references nonexistent model fields.

- [x] `fix-service-content-type-api`
  - Issue: serializers use `extras.service` instead of `ipam.service`.
  - Done when: Service content type is selectable and valid via API.

- [x] `update-stale-vm-location-test`
  - Issue: VM location test expectation conflicts with current engine behavior.
  - Done when: tests reflect intended current behavior.

- [x] `expand-zone-template-docs-with-custom-field-examples`
  - Issue: zone template documentation needs clearer examples, including custom field usage.
  - Done when: docs include practical zone template examples that reference custom fields.

- [x] `add-view-rule-template`
  - Issue: add a rule template for `view`.
  - Done when: a `view` rule template is defined and available where rule templates are documented/configured.

- [x] `api-pass-view-template`
  - Issue: API support for `DNSRule.view_template` needs a dedicated cleanup pass after UI/engine changes.
  - Done when: serializers, API tests, and payload examples no longer reference `dns_views` and pass with `view_template`.

- [x] `harden-view-template-best-effort-tests`
  - Issue: best-effort per-candidate behavior needs broader test coverage for empty renders, unknown views, and zone misses.
  - Done when: targeted tests cover success/failure mixes and update-path reconciliation behavior.

- [x] `optional-in-place-view-context-change-best-effort-test`
  - Issue: add an in-place context-change variant where the same candidate IP remains attached but its rendered view outcome changes and reconciliation updates records accordingly.
  - Notes: optional for the first release; current coverage already validates create/update best-effort behavior for empty, unknown-view, and zone-miss outcomes.
  - Done when: at least one targeted test validates in-place context mutation for an existing candidate without replacing the candidate IP set.

- [x] `document-best-effort-bullet-3-and-4b-behavior`
  - Issue: behavior for bullet point 3 (update-path reconciliation mixes) and bullet point 4b (previously valid then all candidates fail) is not explicitly documented.
  - Done when: user docs clearly explain expected record/tracking behavior for both scenarios.

- [x] `improve-view-template-observability`
  - Issue: warning/error logs for per-candidate skips should be more operator-friendly.
  - Done when: logs include enough context (rule, source object, candidate/rdata, reason) to troubleshoot quickly.

- [x] `revisit-dnsrule-multiview-conflict-guardrails` (cancelled)
  - Issue: multiview (`1..N`) DNSRule targeting introduces overlap/conflict complexity.
  - Notes:
    - More complex validation: overlap must be checked using effective view sets, including empty=>Default normalization.
    - Harder conflict reasoning: two rules can look distinct but still overlap on one or more selected views.
    - Update-time edge cases: edits to selected views can introduce collisions after initial create succeeds.
    - Less obvious UX: users need clear error messages that identify overlapping views and conflicting rules.
    - Larger test surface: create/update/form/API/bulk paths all need overlap and normalization coverage.
    - Concurrency limitations: M2M overlap checks are hard to enforce at DB constraint level; race windows remain possible.
    - Operational policy tension: strict rejection improves safety but can block migration workflows that temporarily need overlap.
    - Worth revisiting: coarse guardrails are simpler but too restrictive for realistic multiview DNS usage.
    - Cancelled for current policy: only one enabled rule per `(content_type, record_type, location, tenant)` scope is allowed.
    - Reopen if policy changes to allow multiple enabled rules within the same scope.
  - Done when: conflict policy is finalized (strict reject vs permissive), validation/UX behavior is documented, and implementation approach is selected for create/update/API flows.

- [x] `audit-new-tests-assert-raises-message-checks`
  - Issue: tests added in this patch should be reviewed against plugin and Nautobot LTM-2.4 conventions to ensure `assertRaises` text checks are added where meaningful.
  - Done when: newly added/modified tests are reviewed and updated to assert error text (field-level or string form) in cases where message content is part of expected behavior.

- [ ] `zone-template-vs-fixed-zone-selector`
  - Question: should zone template be replaced by fixed zone selector?
  - Done when: design decision is documented and corresponding implementation approach is chosen.

- [ ] `proxy-all-filter-by-rule-record-type`
  - Question: should the `all()` proxy only return IPs appropriate to the DNS record type associated with the rule?
  - Investigation note: evaluate whether context-aware v4/v6 filtering in template proxies is worth the complexity; this may be more effort than needed versus simpler template guidance or rule-level value templates.
  - Done when: behavior is defined and documented, and proxy implementation is updated if required.

- [x] `handle-module-backed-interface-parent-fallback`
  - Issue: module-backed `Interface` objects may have `device=None`; location/tenant extraction should fall back via `interface.parent`.
  - Done when: location/tenant resolution correctly handles module and nested-module interfaces, with targeted tests.

- [ ] `add-interface-redundancy-group-support`
  - Issue: `InterfaceRedundancyGroup` objects are not currently supported in `_get_object_location()`, `_get_object_tenant()`, and rule processing.
  - Done when: intended behavior for IRG is defined and implemented with targeted tests.

- [ ] `validate-view-template-migrations`
  - Issue: verify migration behavior for the `dns_views` -> `view_template` transition on both clean and upgraded databases.
  - Done when: migrations are validated end-to-end and any data/compatibility gaps are documented or resolved.

- [ ] `optional-first-release-record-reconciliation-jobs`
  - Issue: consider adding background reconciliation jobs to detect and repair DNS record/tracking drift.
  - Notes: optional for the first release; can be deferred if signal/update-path behavior is stable enough.
  - Notes: needed for changes that affect template context but do not emit rule-processing signals (for example, in-place Prefix custom-field updates used by `view_template`), since those can leave stale records until reconciliation runs.
  - Notes: `DNSRule` create/update/delete does not currently trigger object-wide reprocessing, so rule edits can leave pre-existing objects out of sync until touched.
  - Notes: `DNSZone`/`DNSView` changes (rename/delete/reassignment) can invalidate previously valid rendered targets without triggering per-object reconciliation.
  - Notes: Prefix/Namespace changes referenced by templates can alter rendered outputs without touching Interface/Device/Service objects that own tracked records.
  - Notes: `Cluster` change handling is explicitly TODO in signal coverage; VM/VMInterface-derived records can drift when cluster context changes.
  - Notes: relationship/computed-field driven template context can change via related-object updates that do not emit source-object DNS processing signals.
  - Done when: reconciliation job scope, trigger model, and operator workflow are defined and documented; implementation is added if approved.

- [ ] `enforce-template-permissions-for-record-creation`
  - Issue: check whether template-driven rule processing needs guardrails so users without DNS record create permissions cannot create records indirectly.
  - Done when: permission model is reviewed, required protections are documented, and enforcement is implemented if needed.