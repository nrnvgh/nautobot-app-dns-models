# DNS Zone Model

The DNS zone model is used to represent a distinct DNS zone. It contains the zone name, TTL, and SOA record details.

Domain registration attributes are modeled separately in `DNSRegistration`.

- `name` (string): Unique FQDN of the Zone, w/ TLD. e.g `example.com`.
- `type` (choice, default `Primary`): `Primary` for an ordinary zone, or `Catalog` for an [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) catalog zone. Fixed at creation; a zone cannot be converted between types.
- `enabled` (boolean, default `True`): Indicates whether the zone is eligible for publication by external integrations. This app does not publish zones or enforce this setting. The same field exists on every [DNS record](dnsrecord.md) type; disabling a zone does not change the records it contains.
- `ttl` (integer): Time to live for the DNS zone.
- `filename` (string): Filename of the DNS zone file.
- `description`: (string): Description of the DNS zone.
- `soa_mname`: (string): FQDN of the authoritative name server for the DNS zone.
- `soa_rname`: (string): Mailbox or single-label placeholder for the person responsible for the DNS zone.
- `soa_refresh`: (integer): Time in seconds for secondary name servers to query the primary for the SOA record.
- `soa_retry`: (integer): Time in seconds for secondary name servers to retry to request the serial number from the primary.
- `soa_expire`: (integer): Time in seconds for secondary name servers to stop answering requests if the primary does not respond. This value must be bigger than the sum of refresh and retry.
- `soa_serial`: (integer): Serial number of the zone. This value must be incremented each time the zone is changed, and secondary DNS servers must be able to retrieve this value to check if the zone has been updated.
- `soa_minimum`: (integer): Minimum TTL for records in this zone.
- `tenant` (Tenant, optional): Reference to the Tenant model for multi-tenancy support.
- `auto_create_ptr` (boolean, default `False`): When enabled, creating an A or AAAA record in this zone automatically creates a matching PTR record in the most-specific reverse zone within the same DNS view. If no matching reverse zone exists, the A/AAAA creation fails with a validation error.

## SOA RNAME Formats

An SOA RNAME may be entered as an email address, a basic DNS-style mailbox, or a single-label placeholder. Email-style values must be valid email addresses. Basic DNS-style mailboxes are normalized to email form prior to being saved, and single-label placeholders are stored without a trailing dot.

DNS-style mailbox decoding follows [RFC 1035 §3.3.13](https://www.rfc-editor.org/rfc/rfc1035.html#section-3.3.13)
and [§8](https://www.rfc-editor.org/rfc/rfc1035.html#section-8). This app stores decoded mailbox values in
email form as follows:

| Input | Stored value | Result |
| --- | --- | --- |
| `admin@example.com` | `admin@example.com` | Accepted unchanged |
| `admin.example.com.` | `admin@example.com` | Normalized from DNS style |
| `john\.smith.example.com.` | `john.smith@example.com` | The `\.` escape becomes a dot in the mailbox name per [RFC 1035 §5.1](https://www.rfc-editor.org/rfc/rfc1035.html#section-5.1) |
| `invalid.` | `invalid` | Single-label placeholder normalized |
| `john@example` | — | Rejected because the email domain is not fully qualified |
| `admin\046example.com.` | — | Rejected because the DNS escape is unsupported |
| `admin..example.com` | — | Rejected because the DNS-style mailbox is malformed |

+++ 1.2.0 "DNS label length rules"

    When DNS validation is enabled (via the `DNS_VALIDATION_LEVEL` configuration), `DNSZone` enforces the following DNS label length rules, as specified by [RFC 1035 §3.1](https://datatracker.ietf.org/doc/html/rfc1035#section-3.1):

    - Each label (the parts of the name separated by dots) must be no more than 63 bytes in wire format
    - Empty labels (e.g., consecutive dots or leading/trailing dots) are not allowed

    See the [installation guide](../admin/install.md#app-configuration) for configuration options.

## Catalog Zones

+++ 2.4.0

A zone with a `type` of `Catalog` names a set of other zones instead of holding records of its own. [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) defines this as the way to tell a secondary name server which zones it should serve, so that the list is maintained in one place rather than in each server's configuration.

This app builds the contents of a catalog zone. It does not serve or consume one and it does not configure name servers, so what follows describes data in Nautobot; getting that data to a name server is the job of whatever integration reads it.

### What a catalog zone contains

Every record in a catalog zone is system-managed. No record type can be created, edited, or deleted there by hand, and the record panels on a catalog zone's detail page carry no add or edit controls. A catalog zone holds:

- one NS record at the zone apex, with `invalid` as its `server` — the single RR [RFC 9432 §4](https://datatracker.ietf.org/doc/html/rfc9432#section-4) recommends for the NS RRset that any valid zone must have
- a `version` TXT record holding `2`, the only schema version RFC 9432 defines
- one PTR record per member, at `<member_label>.zones`, naming the member zone

Saving a catalog zone writes the NS and TXT records, and restores them if they have been removed or altered. Each PTR record belongs to the membership that creates it, described under [Catalog Zone Membership](catalogzonemembership.md).

!!! note

    The apex NS record is named `@`, which denotes the zone origin per [RFC 1035 §5.1](https://datatracker.ietf.org/doc/html/rfc1035#section-5.1), and its `server` omits the trailing dot the RFC writes, since that dot is zone file syntax rather than part of the name. Every record in a catalog zone carries a TTL of 0, because [RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1) gives the TTL field no meaning here.

### Members

A zone joins a catalog through a [Catalog Zone Membership](catalogzonemembership.md) rather than by adding a PTR record, and you can create one from either end. A zone's own form offers a Catalog Zone field; once the zone is enrolled, that field is disabled and the form offers Remove from Catalog instead. A catalog zone's Member Zones panel offers Add and a per-row Delete, and links to the catalog's PTR records in its footer. The zone list offers per-row Add to Catalog and Remove from Catalog actions, and an Edit Catalog Memberships menu for a selection of zones.

All of these write a Catalog Zone Membership and are governed by [that model's permissions](catalogzonemembership.md#permissions); `change_dnszone` alone does not authorize them. A membership cannot be edited in place, so putting a zone in a different catalog is a removal and then an addition.

A zone editor also needs `view` permission on the catalog zones they are expected to enroll into; see [Permissions](catalogzonemembership.md#permissions) on that page for why.

A catalog and its members always share a DNS view. Neither an enrolled zone nor a catalog that has members can be moved to another view: the zone's form disables the View field, and the REST API and bulk edit refuse the change. Remove the zone from its catalog, or remove the catalog's members, and the view can be changed again.

### What a catalog zone cannot do

- A catalog zone cannot be a member of another catalog zone.
- `auto_create_ptr` cannot be enabled, since no A or AAAA record can exist in a catalog zone. The form disables the control, as does bulk edit whenever the selection includes a catalog zone.
- A catalog zone is not a registered name, so it cannot be the zone on a [DNS Registration](dnsregistration.md).

### Finding and querying members

The zone list carries a Catalog Zone column and a filter of the same name, so a catalog's members can be found from the zone list as well as from the catalog's own page.

A zone's REST API representation carries a read-only `catalog` field naming the catalog it belongs to, or `null` when it belongs to none. The read-only many-to-many fields `catalogs` and `members`, the latter listing a catalog zone's member zones, are returned only when the request sets `exclude_m2m=False`, like other many-to-many fields in Nautobot; they are also what a zone's change log records, so an enrollment or removal shows which zones it involved on both sides. GraphQL reports the same field, and returns `null` there for a catalog the requesting user may not view. Memberships themselves are created and deleted through the Catalog Zone Membership endpoint.
