# Catalog Zone Membership Model

+++ 2.4.0

## Overview

A catalog zone membership records that one of your zones is a member of a
[catalog zone](dnszone.md#catalog-zones). Catalog zones are the mechanism
[RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) defines for naming the set of zones a
secondary name server should serve.

This app models the contents of a catalog zone. It does not serve or consume one, so adding or
removing a member changes the data in Nautobot and nothing else — no name server is contacted
and no DNS configuration changes. Getting these zones onto a secondary is the job of whatever
integration reads this data.

Memberships have no page of their own to browse. You add and remove members from either the
member zone or the catalog zone, and Nautobot records the membership for you. It also maintains
the PTR record that represents the membership within the catalog zone; that record is managed
for you and cannot be edited by hand.

| Field | Type | Required | Description |
|---|---|---|---|
| `catalog_zone` | ForeignKey to DNSZone | Yes | The catalog zone containing this member. Its `type` must be `Catalog`. |
| `member_zone` | ForeignKey to DNSZone | Yes | The zone contained in the catalog zone. Must be in the same DNS view as the catalog zone, and must not itself be a catalog zone. |
| `member_label` | string | No | The label identifying this member within the catalog. Generated for you when left blank; see [Member labels](#member-labels). Supplied values must be a single DNS label — no dots, and no more than 63 bytes in wire format. |

A zone can belong to at most one catalog, and each label is used only once within a catalog.
Labels are compared the way DNS compares them, without regard to case
([RFC 4343 §3](https://datatracker.ietf.org/doc/html/rfc4343#section-3)), so `Foo` and `foo` cannot
both name members of the same catalog.

## Adding and removing members

Both zones offer the controls. A zone's own form has a Catalog Zone field, and an enrolled
zone's form offers Remove from Catalog. A catalog zone's Member Zones panel offers Add and a
per-row Delete. The zone list adds a Catalog Zone column and filter, per-row Add to Catalog and
Remove from Catalog actions, and an Edit Catalog Memberships menu for a selection of zones.
[DNS Zone](dnszone.md#catalog-zones) describes each of these in place.

The bulk actions confirm the selection first, and either the whole batch succeeds or none of it
does. Add to Catalog refuses a selection that includes a zone already in a catalog, a catalog
zone, or zones from more than one view; because a catalog only holds zones from its own view,
the catalog picker offers only the catalogs in the view the selection shares. Remove from
Catalog takes each zone out of whichever catalog holds it, so the selection may span several
catalogs and views, and any selected zone that is in no catalog is simply skipped.

A membership cannot be edited once created. Moving a zone to a different catalog is a removal
followed by an addition. Memberships have a REST API endpoint of their own for creating and
deleting them; because no field can change, it offers no `PATCH` or `PUT` at all.

## Member labels

Each member is identified within its catalog by an opaque label, defined in
[RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1). The label carries no
meaning beyond tagging the member. Nautobot generates one automatically — no form offers the
field — so in normal use you never choose one, though it appears in the catalog's PTR record
names. The REST API and CSV import may supply one explicitly.

The label cannot be changed afterward. Under RFC 9432 the label is the member's identity to
anything consuming the catalog: a label that has not been seen before means a zone was added,
and one that stops appearing means a zone was removed. Reusing a label for a different zone, or
giving an existing member a new one, would therefore misrepresent the catalog, which is why
Nautobot treats all three fields as fixed and issues a new label whenever a membership is
recreated — including when a member zone is renamed. The old label's record is removed in the
same operation, so the catalog never lists the same zone twice.

!!! note

    Consumers are specified to discard the zone data, DNSSEC keys, and timers held under a label
    that disappears, and to configure a newly seen label from scratch, per
    [RFC 9432 §5.4](https://datatracker.ietf.org/doc/html/rfc9432#section-5.4) and
    [§5.6](https://datatracker.ietf.org/doc/html/rfc9432#section-5.6). That is a consequence of
    exporting this data to a name server, not something this app does.

### Resetting a member's state

RFC 9432 §5.6 lets a catalog tell its consumers to discard what they hold for a member and start
again, by giving that member a new label. Nautobot does not offer this as a single operation.

To get a new label for a member, remove the zone from its catalog and then add it to the same
catalog again. The new membership receives a new label. Do both steps before the catalog zone is
next published to your name servers. Nautobot does not change a zone's SOA serial, so when a new
version of the catalog reaches consumers is up to whatever integration exports it. If the removal
and the addition arrive in the same version, consumers see a changed label and reset the member.
If a consumer receives a version made between the two steps, it sees the zone removed and stops
serving it until the addition arrives.

Resetting a member discards its DNSSEC keys on any consumer that generates its own. Validation of
the zone can fail until resolvers' cached DNSKEY and RRSIG records expire.

## The member PTR record

Each membership is represented by one PTR record inside the catalog zone, at
`<member_label>.zones`, pointing at the member zone's name, with a TTL of 0. Adding a membership
creates that record and removing one deletes it, leaving the catalog's other members alone. Like
everything else in a catalog zone, these records are system-managed: create or delete the
membership rather than the record. See [DNS Zone](dnszone.md#catalog-zones) for the rest of a
catalog zone's contents.

!!! note

    Memberships are not change-logged themselves. Enrollments and removals appear in the change
    log of the two zones involved. A rename replaces the membership, which shows as the old member
    PTR record being deleted and a new one created; those entries belong to the records rather than
    to either zone, so they appear in the global change log and not on the catalog zone's own log.

## Deleting zones

Deleting a member zone removes its membership and its record from the catalog. A catalog zone
that still has members cannot be deleted — remove its members first.

## Permissions

`change_dnszone` on its own does not authorize a membership change. Enrolling a zone from any of
the controls above also requires `add_catalogzonemembership`, and removing one requires
`delete_catalogzonemembership`.

Object-level constraints apply. A permission narrowed to one catalog reaches only that catalog's
members, and a bulk action that would reach past it is refused in full.

!!! note "Grant zone editors `view` permission on catalog zones"

    As the [permissions guide](https://docs.nautobot.com/projects/core/en/stable/user-guide/administration/guides/permissions/#related-objects-on-forms)
    notes for related objects generally, a catalog the user cannot view does not appear in the
    Catalog Zone field, so they cannot enroll a zone in it.
