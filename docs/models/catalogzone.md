# Catalog Zone Model

The catalog zone model is used to represent a DNS catalog zone.

- `name` (string): FQDN of the catalog zone, with TLD.
- `schema_version` (string): Catalog schema version. RFC 9432 uses `2`.
- `dns_view` (DNS View): DNS view associated with this catalog zone.
- `ttl` (integer): Time to live for the catalog zone.
- `filename` (string): Filename of the catalog zone file.
- `description` (string): Optional description of the catalog zone.
- `soa_mname` (string): FQDN of the authoritative name server.
- `soa_rname` (string): Administrator email address.
- `soa_refresh` (integer): Refresh interval.
- `soa_retry` (integer): Retry interval.
- `soa_expire` (integer): Expire interval.
- `soa_serial` (integer): SOA serial value.
- `soa_minimum` (integer): Minimum TTL.
