# Catalog Zone Member Model

The Catalog Zone Member model enrolls a DNS zone in an [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) catalog zone. It is the operator-facing object for membership; the PTR record that publishes the membership to consumers is derived from it rather than managed directly.

- `catalog_zone` (DNSZone): The catalog zone publishing this membership. Must have a `zone_type` of `Catalog`.
- `member_zone` (DNSZone): The zone published by the catalog. Must be in the same DNS view as the catalog zone, and cannot itself be a catalog zone.
- `member_label` (string): Opaque DNS label identifying this member within the catalog zone. Generated automatically when omitted.

A zone belongs to at most one catalog, and each label is unique within a catalog.

This model is where enrollments are created, moved, and removed, in the UI and through its REST API endpoint alike. Two shortcuts write the same rows: a zone's edit form offers a Catalog Zone field, and the zone list offers an Add to Catalog action for a selection of zones.

The Add to Catalog action confirms the selection before writing anything. Zones with no catalog are enrolled and zones already in another catalog are moved, all in one transaction, so a zone the batch cannot write takes the rest back with it. Since a catalog only holds zones from its own view, the picker offers just the catalogs in the view the selection shares. A selection no catalog could take, because it holds a catalog zone or spans several views, is refused on the confirmation before a catalog is asked for.

## Member label

[RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1) defines an opaque label for each catalog member. It has no meaning beyond tagging the member, and it must be unique within the catalog.

Nautobot generates a random 26-character label automatically when one is not supplied. The UI never offers the field. The REST API and CSV import may supply a label explicitly; it must not contain a dot and must be no more than 63 octets in wire format.

Once assigned, the label cannot be changed through Nautobot. Catalog consumers use it as the member's identity: if the label changes, they discard the member's existing state and configure the zone again, per [RFC 9432 §5.4](https://datatracker.ietf.org/doc/html/rfc9432#section-5.4) and [§5.6](https://datatracker.ietf.org/doc/html/rfc9432#section-5.6).

Removing a membership and creating a new one also produces a new label. That is the supported way to reset consumer state when the label itself cannot be edited.

## Published record

Saving or deleting a membership reconciles the catalog zone's member PTR records. Each membership publishes one PTR record at `<member_label>.zones` within the catalog zone, pointing at the member zone name, with a TTL of 0.

Those PTR records are system-managed. They cannot be created, edited, or deleted through ordinary PTR record CRUD; change the membership instead. See [DNS Zone](dnszone.md) for the rest of a catalog zone's contents.

## Permissions

Adding a zone to a catalog requires `add_catalogzonemember`, moving it to another catalog requires `change_catalogzonemember`, and removing it requires `delete_catalogzonemember`.

When enrollment is changed from a zone's add or edit form, or from the zone list's Add to Catalog action, those permissions are required in addition to the permission needed to create or change the zone itself. `change_dnszone` alone does not authorize enrollment.

The Add to Catalog action is offered to anyone holding `add_catalogzonemember`, since enrolling is what it is for. A selection that also moves zones out of another catalog needs `change_catalogzonemember` as well, and is refused in full without it.
