# Patch TODO

- [x] `fix-aaaa-reconcile-key`
  - Issue: AAAA reconciliation key uses `ARecord`.
  - Done when: existing `AAAARecord` entries are preserved during reconciliation.

- [x] `fix-vm-tenant-fallback`
  - Issue: VM tenant fallback to cluster tenant is bypassed.
  - Done when: a VM with no tenant resolves tenant from its cluster.

- [ ] `fix-zone-fixed-reference`
  - Issue: engine references undefined `rule.zone_fixed`.
  - Done when: zone resolution no longer references nonexistent model fields.

- [x] `fix-service-content-type-api`
  - Issue: serializers use `extras.service` instead of `ipam.service`.
  - Done when: Service content type is selectable and valid via API.

- [x] `update-stale-vm-location-test`
  - Issue: VM location test expectation conflicts with current engine behavior.
  - Done when: tests reflect intended current behavior.

- [ ] `zone-template-vs-fixed-zone-selector`
  - Question: should zone template be replaced by fixed zone selector?
  - Done when: design decision is documented and corresponding implementation approach is chosen.

- [ ] `proxy-all-filter-by-rule-record-type`
  - Question: should the `all()` proxy only return IPs appropriate to the DNS record type associated with the rule?
  - Investigation note: evaluate whether context-aware v4/v6 filtering in template proxies is worth the complexity; this may be more effort than needed versus simpler template guidance or rule-level value templates.
  - Done when: behavior is defined and documented, and proxy implementation is updated if required.

- [ ] `handle-module-backed-interface-parent-fallback`
  - Issue: module-backed `Interface` objects may have `device=None`; location/tenant extraction should fall back via `interface.parent`.
  - Done when: location/tenant resolution correctly handles module and nested-module interfaces, with targeted tests.

- [ ] `add-interface-redundancy-group-support`
  - Issue: `InterfaceRedundancyGroup` objects are not currently supported in `_get_object_location()`, `_get_object_tenant()`, and rule processing.
  - Done when: intended behavior for IRG is defined and implemented with targeted tests.
