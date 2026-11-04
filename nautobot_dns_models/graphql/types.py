"""GraphQL implementation for the DNS models."""

import graphene
import graphene_django_optimizer as gql_optimizer
from nautobot.apps.graphql import OptimizedNautobotObjectType, permission_safe_resolver

from nautobot_dns_models.filters import (
    AAAARecordFilterSet,
    ARecordFilterSet,
    CNAMERecordFilterSet,
    DNSZoneFilterSet,
    MXRecordFilterSet,
    NSRecordFilterSet,
    PTRRecordFilterSet,
    SRVRecordFilterSet,
    TXTRecordFilterSet,
)
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CNAMERecord,
    DNSRecord,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
)


class DNSZoneType(OptimizedNautobotObjectType):
    """Graphql Type Object for the DNSZone model."""

    class Meta:
        """Metadata for the DNSZone."""

        model = DNSZone
        filterset_class = DNSZoneFilterSet

    catalog = graphene.Field("nautobot_dns_models.graphql.types.DNSZoneType")

    # Without these hints, a zone list queries the membership, the catalog zone, and the deferred
    # `type` once per zone.
    @gql_optimizer.resolver_hints(prefetch_related="catalog_memberships__catalog_zone", only="type")
    @permission_safe_resolver
    def resolve_catalog(self, info):  # pylint: disable=unused-argument
        """Return the catalog zone this zone belongs to, or null if the user may not view it.

        `catalog` is a property, not a relation, so the resolvers Nautobot generates, which enforce
        view permissions, do not cover it.
        """
        return self.catalog


class DNSRecordType(OptimizedNautobotObjectType):
    """Graphql Type Object for the CNAMERecord model."""

    ttl = graphene.Int(description="Time to live for the DNS record, in seconds.")

    class Meta:
        """Metadata for the CNAMERecord."""

        model = DNSRecord


class NSRecordType(DNSRecordType):
    """Graphql Type Object for the NSRecord model."""

    class Meta:
        """Metadata for the NSRecord."""

        model = NSRecord
        filterset_class = NSRecordFilterSet


class ARecordType(DNSRecordType):
    """Graphql Type Object for the ARecord model."""

    class Meta:
        """Metadata for the ARecord."""

        model = ARecord
        filterset_class = ARecordFilterSet


class AAAARecordType(DNSRecordType):
    """Graphql Type Object for the AAAARecord model."""

    class Meta:
        """Metadata for the AAAARecord."""

        model = AAAARecord
        filterset_class = AAAARecordFilterSet


class CNAMERecordType(DNSRecordType):
    """Graphql Type Object for the CNAMERecord model."""

    class Meta:
        """Metadata for the CNAMERecord."""

        model = CNAMERecord
        filterset_class = CNAMERecordFilterSet


class MXRecordType(DNSRecordType):
    """Graphql Type Object for the MXRecord model."""

    class Meta:
        """Metadata for the MXRecord."""

        model = MXRecord
        filterset_class = MXRecordFilterSet


class TXTRecordType(DNSRecordType):
    """Graphql Type Object for the TXTRecord model."""

    class Meta:
        """Metadata for the TXTRecord."""

        model = TXTRecord
        filterset_class = TXTRecordFilterSet


class PTRRecordType(DNSRecordType):
    """Graphql Type Object for the PTRRecord model."""

    class Meta:
        """Metadata for the PTRRecord."""

        model = PTRRecord
        filterset_class = PTRRecordFilterSet


class SRVRecordType(DNSRecordType):
    """Graphql Type Object for the SRVRecord model."""

    class Meta:
        """Metadata for the SRVRecord."""

        model = SRVRecord
        filterset_class = SRVRecordFilterSet


graphql_types = [
    DNSZoneType,
    NSRecordType,
    ARecordType,
    AAAARecordType,
    CNAMERecordType,
    MXRecordType,
    TXTRecordType,
    PTRRecordType,
    SRVRecordType,
]
