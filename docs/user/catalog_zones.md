# Catalog Zones

A [DNS zone](../models/dnszone.md) with a `type` of `Catalog` lists other zones, called "member zones", instead of holding ordinary records. [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) defines this as the way to tell a secondary name server which zones it should serve, so that the list is maintained in one place rather than in each server's configuration.

This app builds the contents of a catalog zone. It does not serve or consume one and it does not configure name servers, so what follows describes data in Nautobot; getting that data to a name server is the job of whatever integration reads it.

## Records

Every record in a catalog zone is system-managed: none can be created, edited, or deleted by hand. Each carries a TTL of 0, because [RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1) gives the TTL field no meaning here. A catalog zone holds:

- one NS record at the zone apex, with `invalid` as its `server` — the single RR [RFC 9432 §4](https://datatracker.ietf.org/doc/html/rfc9432#section-4) recommends for the NS RRset that any valid zone must have
- a `version` TXT record holding `2`, the only schema version RFC 9432 defines
- one PTR record per member, at `<member_label>.zones`, naming the member zone

Saving a catalog zone writes the NS and TXT records. If code that bypasses validation, or a direct database change, has altered or removed them, the next save of the catalog zone restores them. Each PTR record is written when a zone joins the catalog and deleted when it leaves.

!!! note

    The apex NS record is named `@`, which denotes the zone origin per [RFC 1035 §5.1](https://datatracker.ietf.org/doc/html/rfc1035#section-5.1), and its `server` omits the trailing dot the RFC writes, since that dot is zone file syntax rather than part of the name.

## Rules

A zone joins a catalog by setting its `catalog_zone`, and leaves it by clearing that field. These rules apply to a member zone:

- A zone moving to another DNS view must leave its catalog, or join one in the new view, in the same edit.
- When a member zone is deleted, its PTR record is removed from the catalog.

These rules apply to a catalog zone:

- A catalog zone cannot be a member of another catalog zone.
- `auto_create_ptr` cannot be enabled on a catalog zone, since no A or AAAA record can exist in one.
- A catalog zone is not a registered name, so it cannot be the zone on a [DNS Registration](../models/dnsregistration.md).
- A catalog zone that has members cannot be moved to another DNS view.
- A catalog zone that still has members cannot be deleted. Remove its members first.

In the web UI:

- Adding a member from the catalog zone offers only zones that are in no catalog.
- Bulk edit refuses the whole selection if any zone cannot take the change.

!!! note

    A change of catalog is recorded in the member zone's change log. The PTR records it writes and deletes are recorded under their own entries, in the same request. The catalog zone's own change log records neither.

## Member Labels

Each member is identified within its catalog by an opaque label, defined in [RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1). Nautobot generates the label, and no form or API accepts one.

Under RFC 9432, a consumer of the catalog treats a label it has not seen before as a zone added, and one that stops appearing as a zone removed. Nautobot therefore keeps a member's label while the zone remains in the catalog, and issues a new label whenever a zone joins a catalog. A zone that is renamed, or that leaves a catalog and joins it again, gets a new label.

To give a member a new label, which [RFC 9432 §5.6](https://datatracker.ietf.org/doc/html/rfc9432#section-5.6) uses to tell consumers to reset that member, take the zone out of its catalog and add it again. Do both steps before the catalog zone is next published to your name servers: a consumer that receives a version made between the two steps sees the zone removed.

## Permissions

Changing a zone's catalog requires two permissions:

- on the zone itself: either `change_dnszone` to edit it or `add_dnszone` to create it already in a catalog
- on any catalog zone it leaves or joins: `change_dnszone`

## Finding and Querying Members

The REST API filters zones by `catalog_zone` (name or ID), `is_catalog_member`, and `has_members`. GraphQL reports `members` on a catalog zone.

## Limitations

The app writes only the schema version and the member list. It does not support the following properties defined by RFC 9432:

- change of ownership ([`coo`, §4.3.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.3.1))
- groups ([`group`, §4.3.2](https://datatracker.ietf.org/doc/html/rfc9432#section-4.3.2))
- custom properties ([`*.ext`, §4.4](https://datatracker.ietf.org/doc/html/rfc9432#section-4.4))

Without `coo`, moving a zone to another catalog gives it a new label, so consumers treat the move as the zone's removal and a new addition, as described under [Member Labels](#member-labels).
