# Catalog Zone Member Model

The Catalog Zone Member model enrolls a DNS zone in an [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) catalog zone. It is the operator-facing object for membership; the PTR record that publishes the membership to consumers is derived from it rather than managed directly.

- `catalog_zone` (DNSZone): The catalog zone publishing this membership. Must have a `zone_type` of `Catalog`.
- `member_zone` (DNSZone): The zone published by the catalog. Must be in the same DNS view as the catalog zone, and cannot itself be a catalog zone.
- `member_label` (string): Opaque DNS label identifying this member within the catalog zone. Generated automatically if left blank.

A zone belongs to at most one catalog, and each label is unique within a catalog.

This model is where enrollments are created, moved, and removed, in the UI and through its REST API endpoint alike. A zone reports its own catalog read-only, since a membership carries a `member_label` that a field on the zone could not express.

## Member label

RFC 9432 §4.1 lets the producer choose any unique label and treats it as the member's identity for consumer state. The generated label is a random UUID encoded as unpadded lowercase base32, which is 26 DNS-safe characters.

The label is fixed once assigned: changing it would look to a consumer like the member zone was removed and re-added, discarding whatever state it held for that member. Deleting a membership and creating a new one mints a new identity on purpose.

## Published record

Saving or deleting a membership reconciles the catalog zone's member PTR records. Each membership publishes one PTR at `<member_label>.zones` within the catalog zone, pointing at the member zone name, with a TTL of 0.

Those PTR records are system-managed. They cannot be created, edited, or deleted through ordinary PTR record CRUD; change the membership instead. See [DNS Zone](dnszone.md) for the rest of a catalog zone's contents.
