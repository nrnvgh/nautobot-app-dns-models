# Catalog Zone Membership Model

The model behind a zone's membership in an [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) catalog zone: it has add, edit, and delete forms, but no list or detail page of its own. The PTR record that publishes the membership to consumers is derived from it rather than managed directly.

- `catalog_zone` (DNSZone): The catalog zone publishing this membership. Must have a `type` of `Catalog`.
- `member_zone` (DNSZone): The zone published by the catalog. Must be in the same DNS view as the catalog zone, and cannot itself be a catalog zone.
- `member_label` (string): Opaque DNS label identifying this member within the catalog zone. Generated automatically when omitted.

A zone belongs to at most one catalog, and each label is unique within a catalog.

In the UI, memberships are created, moved, and removed from the zone and from the catalog:

- a zone's add or edit form offers a Catalog Zone field
- the zone list offers an Edit Catalog Memberships menu for a selection of zones (Add to Catalog and Remove from Catalog), and per-row actions: Add to Catalog for zones not in a catalog, and Remove from Catalog on member zones
- a catalog zone's Member Zones panel offers Add, which opens the membership form with that catalog pre-selected. Each row in that panel has Edit and Delete actions for the membership. The panel footer links to the PTR records the catalog publishes for those members.

All of them write the rows described here, and all of them are recorded in the change log of the two zones the membership relates, since the membership is not change-logged itself. The model also has a REST API endpoint of its own, which writes the same rows directly.

Both bulk actions confirm the selection before writing anything, and write it in one transaction, so a zone the batch cannot write takes the rest back with it.

Add to Catalog adds each selected zone to the chosen catalog. A zone already in another catalog is moved rather than refused. Since a catalog only holds zones from its own view, the picker offers just the catalogs in the view the selection shares. A selection that includes a catalog zone, or spans several views, is refused on the confirmation before a catalog is asked for.

Remove from Catalog removes each selected zone from whichever catalog holds it, so a selection may span several catalogs and several views. Selected zones that are in no catalog are counted out and left alone rather than refused; a selection holding none at all is offered nothing to confirm.

## Member label

[RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1) defines an opaque label for each catalog member. It has no meaning beyond tagging the member, and it must be unique within the catalog.

Nautobot generates a random 26-character label automatically when one is not supplied. No form offers the field. The REST API and CSV import may supply a label explicitly; it must not contain a dot and must be no more than 63 octets in wire format.

Once assigned, the label cannot be edited through Nautobot. Catalog consumers use it as the member's identity: a label they have not seen before is the addition of a member zone, and a label that stops appearing is the removal of one. Changing it therefore discards the zone data, DNSSEC keys, and timers the consumer held, and has it configure the zone again from scratch, per [RFC 9432 §5.4](https://datatracker.ietf.org/doc/html/rfc9432#section-5.4) and [§5.6](https://datatracker.ietf.org/doc/html/rfc9432#section-5.6).

Nautobot issues a new label itself where that reset is the right outcome: when the member zone is renamed, and when a membership is pointed at a different zone. In both cases the zone the label named is gone, and what a consumer holds against it belongs to nothing. A rename removes the membership and adds the zone again, so the new label belongs to a new row. Retargeting regenerates the label on the existing row. The alternative, keeping the label and republishing it against the new zone name, is a transition RFC 9432 does not define, and consumers do not agree on one. The catalog stops publishing the old label in the same transaction, so it never advertises the zone twice.

Deleting a membership and creating another produces a new label for the same reason, which is how to force that reset by hand.

## Published record

Saving a membership publishes its member PTR record, and deleting one withdraws it, leaving the other members of the catalog zone untouched. That record sits at `<member_label>.zones` within the catalog zone, points at the member zone name, and has a TTL of 0.

Those PTR records are system-managed. They cannot be created, edited, or deleted through ordinary PTR record CRUD; change the membership instead. See [DNS Zone](dnszone.md) for the rest of a catalog zone's contents.

Renaming a member zone removes its entry from the catalog and creates a new one: the membership row is deleted and another is created, which issues a new label. The change log of the catalog zone reads that way too: the member PTR at the old label is recorded as a deletion, and the one at the new label as a creation. The membership row itself carries no change record, so those two records are where the history of a rename is legible.

Renaming a catalog zone publishes nothing new, because a member's owner name is stored relative to the catalog zone's apex rather than as a fully qualified name.

## Permissions

Adding a zone to a catalog requires `add_catalogzonemembership`, moving it to another catalog requires `change_catalogzonemembership`, and removing it requires `delete_catalogzonemembership`.

When membership is changed from a zone's add or edit form, or from either of the zone list's bulk actions, those permissions are required in addition to the permission needed to create or change the zone itself. `change_dnszone` alone does not authorize a membership change. The membership add, edit, and delete forms, the members panel Add control, and the zone list's per-row actions are governed by the membership permissions alone.

Add to Catalog is offered to anyone holding `add_catalogzonemembership`. A selection that also moves zones out of another catalog needs `change_catalogzonemembership` as well, and is refused in full without it. Remove from Catalog is offered on `delete_catalogzonemembership` alone.

Object-level constraints are honored by both. A permission narrowed to one catalog reaches only the memberships of that catalog, and a batch reaching past it is refused in full rather than in part.
