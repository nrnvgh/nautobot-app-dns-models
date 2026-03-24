"""Filtering for nautobot_dns_models."""

import django_filters
from django.db.models import F
from django.db.models.functions import Coalesce
from nautobot.apps.filters import (
    BaseFilterSet,
    ContentTypeFilter,
    NautobotFilterSet,
    SearchFilter,
)
from nautobot.core.forms import DynamicModelMultipleChoiceField
from nautobot.dcim.filters import LocatableModelFilterSetMixin
from nautobot.tenancy.filters import TenancyModelFilterSetMixin
from netaddr import IPAddress as NetIPAddress

from nautobot_dns_models import models
from nautobot_dns_models.constants.supported_models import get_content_type_query_params
from nautobot_dns_models.queries import DNSRuleContentTypeQuery


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


class DNSZoneFilterSet(NautobotFilterSet):
    """Filter for DNSZone."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "filename": "icontains",
            "soa_mname": "icontains",
            "soa_rname": "icontains",
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSZone
        fields = "__all__"


# pylint: disable=nb-no-model-found, nb-warn-dunder-filter-field
class DNSRecordFilterSet(NautobotFilterSet):
    """Base filter for all DNSRecord models, with support for effective TTL."""

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


class ARecordFilterSet(NautobotFilterSet):
    """Filter for ARecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "address__host": {"lookup_expr": "net_host", "preprocessor": ip_address_preprocessor},
        }
    )

    class Meta:
        """Meta attributes for filter."""

        model = models.ARecord
        fields = "__all__"


class AAAARecordFilterSet(DNSRecordFilterSet):
    """Filter for AAAARecord."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "address__host": {"lookup_expr": "net_host", "preprocessor": ip_address_preprocessor},
        }
    )

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


class DNSRuleContentTypeModelMultipleChoiceFilter(django_filters.ModelMultipleChoiceFilter):
    """ModelMultipleChoiceFilter variant that accepts query_params on its field."""

    field_class = DynamicModelMultipleChoiceField

    def __init__(self, *args, **kwargs):
        """Default to DNSRule-supported content types for both validation and API option loading."""
        kwargs.setdefault("queryset", DNSRuleContentTypeQuery.as_queryset())
        kwargs.setdefault("query_params", get_content_type_query_params())
        super().__init__(*args, **kwargs)


class DNSRuleFilterSet(NautobotFilterSet, LocatableModelFilterSetMixin, TenancyModelFilterSetMixin):
    """Filter for DNSRule."""

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "description": "icontains",
        }
    )

    content_type = DNSRuleContentTypeModelMultipleChoiceFilter()

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSRule
        fields = "__all__"


class DNSRuleRecordFilterSet(BaseFilterSet):
    """Filter for DNSRuleRecord."""

    content_type = ContentTypeFilter()

    rule_name = django_filters.CharFilter(field_name="rule__name", lookup_expr="icontains")
    rule_enabled = django_filters.BooleanFilter(field_name="rule__enabled")

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSRuleRecord
        fields = "__all__"
