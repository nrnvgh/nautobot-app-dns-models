"""Filtering for nautobot_dns_models."""

import uuid

import django_filters
from django.db.models import CharField, F, Q, Value
from django.db.models.functions import Coalesce, Concat
from nautobot.apps.filters import NautobotFilterSet, SearchFilter, TenancyModelFilterSetMixin
from nautobot.core.filters import MultiValueCharFilter, NaturalKeyOrPKMultipleChoiceFilter
from netaddr import IPAddress as NetIPAddress

from nautobot_dns_models import models
from nautobot_dns_models.choices import DNSZoneTypeChoices

EXPIRATION_DATE_INPUT_FORMATS = ("%Y-%m-%d",)


class DNSViewFilterSet(NautobotFilterSet):
    """Filter for DNSView."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSView
        fields = "__all__"


class DNSViewPrefixAssignmentFilterSet(NautobotFilterSet):
    """Filter for DNSViewPrefixAssignment."""

    q = SearchFilter(
        filter_predicates={
            "dns_view__name": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSViewPrefixAssignment
        fields = "__all__"


class DNSRegistrarFilterSet(NautobotFilterSet):
    """Filter for DNSRegistrar."""

    url = MultiValueCharFilter(lookup_expr="icontains")
    account_number = MultiValueCharFilter(lookup_expr="icontains")

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "url": "icontains",
            "account_number": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSRegistrar
        fields = "__all__"


class DNSRegistrationFilterSet(NautobotFilterSet):
    """Filter for DNSRegistration."""

    expiration_date__lte = django_filters.DateFilter(
        field_name="expiration_date",
        lookup_expr="lte",
        input_formats=EXPIRATION_DATE_INPUT_FORMATS,
    )
    expiration_date__gte = django_filters.DateFilter(
        field_name="expiration_date",
        lookup_expr="gte",
        input_formats=EXPIRATION_DATE_INPUT_FORMATS,
    )

    q = SearchFilter(
        filter_predicates={
            "dns_registrar__name": "icontains",
            "dns_zone__name": "icontains",
            "status__name": "icontains",
        }
    )

    dns_zone = NaturalKeyOrPKMultipleChoiceFilter(
        queryset=models.DNSZone.objects.all(),
        query_params={"zone_type__n": DNSZoneTypeChoices.TYPE_CATALOG},
        to_field_name="name",
        label="Zone (name or ID)",
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSRegistration
        fields = "__all__"


class DNSZoneFilterSet(TenancyModelFilterSetMixin, NautobotFilterSet):
    """Filter for DNSZone."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "filename": "icontains",
            "soa_mname": "icontains",
            "soa_rname": "icontains",
        }
    )
    # `catalog` is a property rather than a field, so the filter spans the membership itself. A zone
    # holds at most one membership, so the join cannot repeat a zone. `query_params` is what keeps
    # non-catalog zones out of the picker, including the filter form's Advanced tab, since the
    # widget lists whatever the REST endpoint returns rather than the queryset.
    catalog = NaturalKeyOrPKMultipleChoiceFilter(
        field_name="catalog_memberships__catalog_zone",
        queryset=models.DNSZone.objects.all(),
        query_params={"zone_type": DNSZoneTypeChoices.TYPE_CATALOG},
        to_field_name="name",
        label="Catalog zone (name or ID)",
    )
    # Used by CatalogZoneMembershipForm so the member-zone picker can follow `$catalog_zone` even though
    # DynamicModelChoiceField only substitutes that field's PK, not its dns_view.
    same_dns_view_as = django_filters.ModelChoiceFilter(
        queryset=models.DNSZone.objects.all(),
        method="filter_same_dns_view_as",
        label="Same DNS view as",
    )
    # Pass "true" when creating a membership, or a CatalogZoneMembership PK when editing so that
    # membership's current member_zone remains selectable while other enrolled zones stay hidden.
    available_for_catalog_membership = django_filters.CharFilter(
        method="filter_available_for_catalog_membership",
        label="Available for catalog membership",
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSZone
        fields = "__all__"

    def filter_same_dns_view_as(self, queryset, name, value):  # pylint: disable=unused-argument
        """Restrict to zones that share `value`'s DNS view."""
        return queryset.filter(dns_view_id=value.dns_view_id)

    def filter_available_for_catalog_membership(self, queryset, name, value):  # pylint: disable=unused-argument
        """Return zones not enrolled in a catalog, optionally keeping one membership's member eligible.

        Without `coo` (RFC 9432 §4.3.1), a zone may belong to only one catalog. Offering already-
        enrolled zones in the create picker can only fail the unique constraint on `member_zone`.
        """
        unassigned = Q(catalog_memberships__isnull=True)
        if value and value != "true":
            member_zone_id = (
                models.CatalogZoneMembership.objects.filter(pk=value).values_list("member_zone_id", flat=True).first()
            )
            if member_zone_id is not None:
                return queryset.filter(unassigned | Q(pk=member_zone_id)).distinct()

        return queryset.filter(unassigned)


class CatalogZoneMembershipFilterSet(NautobotFilterSet):
    """Filter for CatalogZoneMembership."""

    q = SearchFilter(
        filter_predicates={
            "catalog_zone__name": "icontains",
            "member_zone__name": "icontains",
            "member_label": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.CatalogZoneMembership
        fields = "__all__"


# pylint: disable=nb-no-model-found, nb-warn-dunder-filter-field
class DNSRecordFilterSet(NautobotFilterSet):
    """Base filter for all DNSRecord models, with support for effective TTL."""

    zone = NaturalKeyOrPKMultipleChoiceFilter(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        label="Zone (name or ID)",
    )

    ttl = django_filters.NumberFilter(method="filter_ttl", label="TTL")
    ttl__ne = django_filters.NumberFilter(method="filter_ttl_ne")
    ttl__gte = django_filters.NumberFilter(method="filter_ttl", lookup_expr="gte")
    ttl__lte = django_filters.NumberFilter(method="filter_ttl", lookup_expr="lte")
    ttl__gt = django_filters.NumberFilter(method="filter_ttl", lookup_expr="gt")
    ttl__lt = django_filters.NumberFilter(method="filter_ttl", lookup_expr="lt")

    def filter_ttl(self, queryset, name, value):
        """Filter by effective TTL (use record's TTL if set, otherwise zone's TTL)."""
        queryset = queryset.annotate(effective_ttl=Coalesce(F("_ttl"), F("zone__ttl")))
        lookup = name.split("__")[-1] if "__" in name else "exact"
        return queryset.filter(**{f"effective_ttl__{lookup}": value})

    def filter_ttl_ne(self, queryset, name, value):  # pylint: disable=unused-argument
        """Exclude effective TTL equal to value."""
        queryset = queryset.annotate(effective_ttl=Coalesce(F("_ttl"), F("zone__ttl")))
        return queryset.exclude(effective_ttl=value)


class NSRecordFilterSet(DNSRecordFilterSet):
    """Filter for NSRecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "server": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.NSRecord
        fields = "__all__"


def ip_address_preprocessor(value):
    """Validate IP address input."""
    try:
        NetIPAddress(value)
    except Exception as error:
        raise ValueError("Invalid IP address") from error
    return value


def search_address_record(queryset, name, value):  # pylint: disable=unused-argument
    """Search A/AAAA records by name, zone, full FQDN, or IP address."""
    queryset = queryset.annotate(
        fqdn=Concat("name", Value("."), "zone__name", output_field=CharField()),
    )
    query = Q(name__icontains=value) | Q(zone__name__icontains=value) | Q(fqdn__icontains=value)

    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        pass
    else:
        query |= Q(id=value)

    try:
        ip_value = ip_address_preprocessor(value)
    except ValueError:
        pass
    else:
        query |= Q(ip_address__host__net_host=ip_value)

    return queryset.filter(query).distinct()


class ARecordFilterSet(DNSRecordFilterSet):
    """Filter for ARecord."""

    q = django_filters.CharFilter(method=search_address_record, label="Search")

    class Meta:
        """Meta attributes for filter."""

        model = models.ARecord
        fields = "__all__"


class AAAARecordFilterSet(DNSRecordFilterSet):
    """Filter for AAAARecord."""

    q = django_filters.CharFilter(method=search_address_record, label="Search")

    class Meta:
        """Meta attributes for filter."""

        model = models.AAAARecord
        fields = "__all__"


class CNAMERecordFilterSet(DNSRecordFilterSet):
    """Filter for CNAMERecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "alias": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.CNAMERecord
        fields = "__all__"


class MXRecordFilterSet(DNSRecordFilterSet):
    """Filter for MXRecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "mail_server": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.MXRecord
        fields = "__all__"


class TXTRecordFilterSet(DNSRecordFilterSet):
    """Filter for TXTRecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "text": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.TXTRecord
        fields = "__all__"


class PTRRecordFilterSet(DNSRecordFilterSet):
    """Filter for PTRRecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "ptrdname": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.PTRRecord
        fields = "__all__"


class SRVRecordFilterSet(DNSRecordFilterSet):
    """Filter for SRVRecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "target": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.SRVRecord
        fields = "__all__"
