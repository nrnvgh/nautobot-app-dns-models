# DNS Zone Model

The DNS zone model is used to represent a distinct DNS zone. It contains the zone name, TTL, and SOA record details.

Domain registration attributes are modeled separately in `DNSRegistration`.

- `name` (string): Unique FQDN of the Zone, w/ TLD. e.g `example.com`.
- `zone_type` (choice, default `Primary`): `Primary` for an ordinary zone, or `Catalog` for an [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) catalog zone. Fixed at creation; a zone cannot be converted between types.
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

+++ 2.3.0 "Catalog zones"

    A zone with a `zone_type` of `Catalog` publishes the membership of other zones to secondary servers, as described in [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432). Nautobot acts as a catalog producer only; it does not consume catalogs.

    Every record in a catalog zone is system-managed, so no record type can be created, edited, or deleted there by hand. Saving a catalog zone writes the records the RFC requires, and repairs them if they have drifted:

    - one NS at the zone apex, naming `invalid`, the single RR [RFC 9432 §4](https://datatracker.ietf.org/doc/html/rfc9432#section-4) recommends for the NS RRset a zone must have to be valid
    - `version` TXT, holding `2`, the only schema version RFC 9432 defines
    - one PTR per member, at `<member_label>.zones`, pointing at the member zone name

    Because `DNSRecord.name` does not accept a blank value, the apex NS is named `@`, which denotes the zone origin per [RFC 1035 §5.1](https://datatracker.ietf.org/doc/html/rfc1035#section-5.1). Its `server` omits the trailing dot the RFC writes, leaving zone file syntax to whoever renders the zone.

    The TTL on all of these records is set to 0. Per [RFC 9432 §4.1](https://datatracker.ietf.org/doc/html/rfc9432#section-4.1), the TTL field has no meaning for records in a catalog zone and should be ignored.

    Zones are enrolled through [Catalog Zone Member](catalogzonemember.md) rather than by creating PTR records. `auto_create_ptr` cannot be enabled on a catalog zone, since no A or AAAA record can exist in one.

    The zone list carries a Catalog Zone column and a filter of the same name, so a catalog's members can be found from the zone list rather than only from the catalog's own page.

    A zone's REST API representation carries a read-only `catalog` field naming the catalog it is enrolled in, or `null` when it is not enrolled. Enrollments themselves are created, moved, and removed through the Catalog Zone Member endpoint.

+++ 1.2.0 "DNS label length rules"

    When DNS validation is enabled (via the `DNS_VALIDATION_LEVEL` configuration), `DNSZone` enforces the following DNS label length rules, as specified by [RFC 1035 §3.1](https://datatracker.ietf.org/doc/html/rfc1035#section-3.1):

    - Each label (the parts of the name separated by dots) must be no more than 63 bytes in wire format
    - Empty labels (e.g., consecutive dots or leading/trailing dots) are not allowed

    See the [installation guide](../admin/install.md#app-configuration) for configuration options.
