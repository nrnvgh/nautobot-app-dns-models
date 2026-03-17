# Extending the App

Extending the application is welcome, however it is best to open an issue first, to ensure that a PR would be accepted and makes sense in terms of features and design.


# Entity Relationship Diagrams

## DNS Record Models

```mermaid
---
Title: DNS Record Models Entity Relation Diagram
---
erDiagram
    DNSModel {
    }

    DNSZone {
        charfield name UK
        integer ttl
        charfied filename
        textfield description
        string soa_mname
        email soa_rname
        integer soa_refresh
        integer soa_retry
        integer soa_export
        integer soa_serial
        integer soa_minimum
    }

    DNSRecord {
        charfield name UK
        DNSZone DNSZone
        integer ttl
        textfield description
        charfied comment
    }

    ipam_IPaddressModel {}

    ARecord {
        ipam_IPaddressModel IPAddress
    }

    AAAARecord {
        ipam_IPaddressModel IPAddress
    }

    CNAMERecord {
        charfied alias
    }

    MXRecord {
        integer preference
        charfied server
    }

    TXTRecord {
        textfield text
    }

    PTRRecord {
        charfied ptrdname
    }

    NSRecord {
        charfied server
    }

    SRVRecord {
        integer priority
        integer weight
        integer port
        charfied target
    }

    DNSModel ||--o{ DNSZone : implements
    DNSModel ||--o{ DNSRecord : implements
    DNSRecord ||--o{ ARecord: implements
    DNSRecord ||--o{ AAAARecord: implements
    DNSRecord ||--o{ CNAMERecord: implements
    DNSRecord ||--o{ MXRecord: implements
    DNSRecord ||--o{ TXTRecord: implements
    DNSRecord ||--o{ PTRRecord: implements
    DNSRecord ||--o{ NSRecord: implements
    DNSRecord ||--o{ SRVRecord: implements

    DNSRecord ||--o{ DNSZone: "is inside of a"

    ARecord ||--|| ipam_IPaddressModel: "references"
    AAAARecord ||--|| ipam_IPaddressModel: "references"
```

## DNS Rule Models

```mermaid
---
Title: DNS Rule Models Entity Relation Diagram
---
erDiagram
    DNSRule {
        string name UK
        boolean enabled
        string record_type
        uuid location FK
        uuid tenant FK
        text view_template
        text zone_template
        text name_template
        text value_template
    }

    DNSRuleRecord {
        uuid object_id
        uuid dns_record_object_id
    }

    django_ContentType {
    }

    dcim_Location {
    }

    tenancy_Tenant {
    }

    SourceObject {
        uuid id PK
    }

    ARecord {
        uuid id PK
    }

    AAAARecord {
        uuid id PK
    }

    DNSRule ||--o{ DNSRuleRecord : creates
    DNSRule }o--|| django_ContentType : triggered_by
    DNSRule }o--o| dcim_Location : scoped_to
    DNSRule }o--o| tenancy_Tenant : scoped_to

    DNSRuleRecord }o--|| django_ContentType : source_type
    DNSRuleRecord }o--|| django_ContentType : dns_record_type
    DNSRuleRecord }o--|| SourceObject : source_object
    DNSRuleRecord }o--|| ARecord : dns_record
    DNSRuleRecord }o--|| AAAARecord : dns_record
```
