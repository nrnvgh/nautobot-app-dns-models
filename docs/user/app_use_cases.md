# Using the App

This document describes common use-cases and scenarios for this App.

## General Usage

Generally, this App is to used to keep track of DNS Zones and their related data and records. The idea is to have a set of models that can either be used to directly model DNS configurations or as a place to aggregate data about DNS related configuration from other tools. While A, AAAA, and PTR records are already partially supported within Nautobot core models, this App is meant to expand the type of DNS records and formalize DNS models within Nautobot.

## Use-cases and common workflows

Use the API or GUI to add DNS Zones and Record objects to Nautobot.

### Keeping one list of the zones a server should serve

+++ 2.4.0

A secondary name server has to be told which zones to serve, and that list is usually kept in each server's own configuration. A zone whose Zone Type is `Catalog` names those zones instead of holding records of its own, so the list lives in Nautobot and the servers read it from one place. [RFC 9432](https://datatracker.ietf.org/doc/html/rfc9432) defines the format.

Create the catalog like any other zone, then add members to the catalog zone from whichever end you are working in: a zone's own form offers a Catalog Zone field, the catalog's Member Zones panel offers Add, and the zone list offers both per-row actions and an Edit Catalog Memberships menu for a selection of zones. Every record in the resulting catalog zone is maintained for you, including one PTR record per member.

Bear in mind that this app models the catalog rather than serving it, so adding a zone to a catalog changes data in Nautobot and nothing else; carrying that data to a name server is the job of whatever integration reads it. See [DNS Zone](../models/dnszone.md#catalog-zones) and [Catalog Zone Membership](../models/catalogzonemembership.md) for what a catalog contains and how memberships behave.

## Screenshots

![Adding a Primary DNS Zone](../images/getting_started-add-zone-3-light.png#only-light){ .on-glb }
![Adding a Primary DNS Zone](../images/getting_started-add-zone-3-dark.png#only-dark){ .on-glb }
[//]: # "`https://next.demo.nautobot.com/plugins/dns/dns-zones/add/`"

/// caption
Adding a Primary DNS Zone
///

![Adding a Catalog Zone](../images/use_cases-add-catalog-zone-1-light.png#only-light){ .on-glb }
![Adding a Catalog Zone](../images/use_cases-add-catalog-zone-1-dark.png#only-dark){ .on-glb }

/// caption
Adding a Catalog Zone
///

![DNS Zone View](../images/getting_started-add-record-3-light.png#only-light){ .on-glb }
![DNS Zone View](../images/getting_started-add-record-3-dark.png#only-dark){ .on-glb }

/// caption
The Primary DNS Zone View
///

![Catalog Zone View](../images/use_cases-catalog-member-zones-light.png#only-light){ .on-glb }
![Catalog Zone View](../images/use_cases-catalog-member-zones-dark.png#only-dark){ .on-glb }

/// caption
The Catalog Zone View
///
