# Catalog Zone Member Model

The Catalog Zone Member model enrolls a DNS zone in an [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) catalog zone. It is the operator-facing object for membership; the PTR record that publishes the membership to consumers is derived from it rather than managed directly.

- `catalog_zone` (DNSZone): The catalog zone publishing this membership. Must have a `zone_type` of `Catalog`.
- `member_zone` (DNSZone): The zone published by the catalog. Must be in the same DNS view as the catalog zone, and cannot itself be a catalog zone.
- `member_label` (string): Opaque DNS label identifying this member within the catalog zone. Generated automatically when omitted.

A zone belongs to at most one catalog, and each label is unique within a catalog.

This model is where enrollments are created, moved, and removed, in the UI and through its REST API endpoint alike; a zone's edit form offers a Catalog Zone field that writes the same rows as a shortcut.

## Member label

[RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1) lets the producer choose any unique label and treats it as the member's identity for consumer state. The generated label is a random UUID encoded as unpadded lowercase base32, which is 26 DNS-safe characters.

The create form does not offer the label; a membership created there always gets a generated one. A label supplied through CSV import, the REST API, or the ORM is kept as given, and must be a single DNS label of no more than 63 octets in wire format.

The label is fixed once assigned. A consumer that sees a new one discards the member's state and treats the zone as newly added, per [RFC 9432 §5.4](https://datatracker.ietf.org/doc/html/rfc9432#section-5.4). Deleting a membership and creating a new one does that deliberately.

## Published record

Saving or deleting a membership reconciles the catalog zone's member PTR records. Each membership publishes one PTR record at `<member_label>.zones` within the catalog zone, pointing at the member zone name, with a TTL of 0.

Those PTR records are system-managed. They cannot be created, edited, or deleted through ordinary PTR record CRUD; change the membership instead. See [DNS Zone](dnszone.md) for the rest of a catalog zone's contents.

## Permissions

Enrollment is governed by this model's permissions rather than the zone's, including when it is changed from a zone's edit form: adding a zone to a catalog requires `add_catalogzonemember`, moving it to another catalog requires `change_catalogzonemember`, and removing it requires `delete_catalogzonemember`.
