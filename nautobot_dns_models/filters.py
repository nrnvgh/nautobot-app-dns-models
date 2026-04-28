"""Filtering for nautobot_dns_models."""

import django_filters
from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, F, OuterRef, Q
from django.db.models.functions import Coalesce
from nautobot.apps.filters import (
    BaseFilterSet,
    ContentTypeFilter,
    NautobotFilterSet,
    SearchFilter,
)
from nautobot.core.forms import DynamicModelMultipleChoiceField
from nautobot.dcim.filters import LocatableModelFilterSetMixin
from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import Service
from nautobot.tenancy.filters import TenancyModelFilterSetMixin
from nautobot.virtualization.models import VirtualMachine, VMInterface
from netaddr import IPAddress as NetIPAddress

from nautobot_dns_models import models
from nautobot_dns_models.choices import DNSRuleRecordTypeChoices
from nautobot_dns_models.queries import DNSRuleContentTypeQuery
from nautobot_dns_models.source_model_support import get_supported_source_content_type_query_params


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

    dns_rule = django_filters.ModelMultipleChoiceFilter(
        field_name="rule_record__rule",
        queryset=models.DNSRule.objects.all(),
        label="DNS Rule",
    )
    has_dns_rule = django_filters.BooleanFilter(method="filter_has_dns_rule", label="Has DNS Rule")

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "address__host": {"lookup_expr": "net_host", "preprocessor": ip_address_preprocessor},
        }
    )

    @staticmethod
    def filter_has_dns_rule(queryset, name, value):  # pylint: disable=unused-argument
        """Filter records by whether they are linked to a DNS rule."""
        if value is None:
            return queryset
        if value:
            return queryset.filter(rule_record__isnull=False)
        return queryset.filter(rule_record__isnull=True)

    class Meta:
        """Meta attributes for filter."""

        model = models.ARecord
        fields = "__all__"


class AAAARecordFilterSet(DNSRecordFilterSet):
    """Filter for AAAARecord."""

    dns_rule = django_filters.ModelMultipleChoiceFilter(
        field_name="rule_record__rule",
        queryset=models.DNSRule.objects.all(),
        label="DNS Rule",
    )
    has_dns_rule = django_filters.BooleanFilter(method="filter_has_dns_rule", label="Has DNS Rule")

    q = SearchFilter(
        filter_predicates={
            "name": "icontains",
            "zone__name": "icontains",
            "address__host": {"lookup_expr": "net_host", "preprocessor": ip_address_preprocessor},
        }
    )

    @staticmethod
    def filter_has_dns_rule(queryset, name, value):  # pylint: disable=unused-argument
        """Filter records by whether they are linked to a DNS rule."""
        if value is None:
            return queryset
        if value:
            return queryset.filter(rule_record__isnull=False)
        return queryset.filter(rule_record__isnull=True)

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
        kwargs.setdefault("query_params", get_supported_source_content_type_query_params())
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
    has_failures = django_filters.BooleanFilter(method="filter_has_failures", label="Has Failures")

    def filter_has_failures(self, queryset, name, value):  # pylint: disable=unused-argument
        """Filter rules by whether they have any failure states."""
        if value is None:
            return queryset

        failure_exists = models.DNSRuleFailureState.objects.filter(rule_id=OuterRef("pk"))
        exists_expr = Exists(failure_exists)
        queryset = queryset.filter(exists_expr) if value else queryset.exclude(exists_expr)

        return queryset

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSRule
        exclude = (
            "view_template",
            "zone_template",
            "name_template",
            "value_template",
        )


class DNSRuleRecordFilterSet(BaseFilterSet):
    """Filter for DNSRuleRecord."""

    content_type = ContentTypeFilter()

    rule_name = django_filters.CharFilter(field_name="rule__name", lookup_expr="icontains")
    rule_enabled = django_filters.BooleanFilter(field_name="rule__enabled")

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSRuleRecord
        fields = "__all__"


class DNSRuleFailureStateFilterSet(BaseFilterSet):
    """Filter for DNSRuleFailureState."""

    q = SearchFilter(
        filter_predicates={
            "candidate_name": "icontains",
            "latest_error": "icontains",
            "latest_constraint": "icontains",
        }
    )
    source_content_type = ContentTypeFilter()
    candidate_record_type = django_filters.ChoiceFilter(
        field_name="candidate_record_type",
        choices=DNSRuleRecordTypeChoices.CHOICES,
    )
    source_object_id = django_filters.UUIDFilter(field_name="source_object_id")
    device_scope_id = django_filters.UUIDFilter(method="filter_device_scope_id", label="Device Scope ID")
    device_object_id = django_filters.UUIDFilter(method="filter_device_object_id", label="Device Object ID")
    interface_id = django_filters.UUIDFilter(method="filter_interface_id", label="Interface ID")
    virtual_machine_scope_id = django_filters.UUIDFilter(
        method="filter_virtual_machine_scope_id",
        label="Virtual Machine Scope ID",
    )
    virtual_machine_object_id = django_filters.UUIDFilter(
        method="filter_virtual_machine_object_id",
        label="Virtual Machine Object ID",
    )
    vminterface_id = django_filters.UUIDFilter(method="filter_vminterface_id", label="VM Interface ID")
    service_id = django_filters.UUIDFilter(method="filter_service_id", label="Service ID")

    #
    # TODO Should this get replaced by custom logic on source_object_id + source_content_type?
    @staticmethod
    def filter_device_scope_id(queryset, name, value):  # pylint: disable=unused-argument
        """Filter failure states to a device and interfaces belonging to that device."""
        device_content_type = ContentType.objects.get_for_model(Device)
        interface_content_type = ContentType.objects.get_for_model(Interface)
        interface_ids = Interface.objects.filter(device_id=value).values("pk")
        return queryset.filter(
            Q(
                source_content_type_id=device_content_type.pk,
                source_object_id=value,
            )
            | Q(
                source_content_type_id=interface_content_type.pk,
                source_object_id__in=interface_ids,
            )
        )

    @staticmethod
    def filter_virtual_machine_scope_id(queryset, name, value):  # pylint: disable=unused-argument
        """Filter failure states to a virtual machine and its interfaces."""
        virtual_machine_content_type = ContentType.objects.get_for_model(VirtualMachine)
        vm_interface_content_type = ContentType.objects.get_for_model(VMInterface)
        vm_interface_ids = VMInterface.objects.filter(virtual_machine_id=value).values("pk")
        return queryset.filter(
            Q(
                source_content_type_id=virtual_machine_content_type.pk,
                source_object_id=value,
            )
            | Q(
                source_content_type_id=vm_interface_content_type.pk,
                source_object_id__in=vm_interface_ids,
            )
        )

    @staticmethod
    def filter_device_object_id(queryset, name, value):  # pylint: disable=unused-argument
        """Filter failure states directly attached to a specific device."""
        device_content_type = ContentType.objects.get_for_model(Device)
        return queryset.filter(
            source_content_type_id=device_content_type.pk,
            source_object_id=value,
        )

    @staticmethod
    def filter_virtual_machine_object_id(queryset, name, value):  # pylint: disable=unused-argument
        """Filter failure states directly attached to a specific virtual machine."""
        virtual_machine_content_type = ContentType.objects.get_for_model(VirtualMachine)
        return queryset.filter(
            source_content_type_id=virtual_machine_content_type.pk,
            source_object_id=value,
        )

    @staticmethod
    def filter_interface_id(queryset, name, value):  # pylint: disable=unused-argument
        """Filter failure states to a specific interface."""
        interface_content_type = ContentType.objects.get_for_model(Interface)
        return queryset.filter(
            source_content_type_id=interface_content_type.pk,
            source_object_id=value,
        )

    @staticmethod
    def filter_vminterface_id(queryset, name, value):  # pylint: disable=unused-argument
        """Filter failure states to a specific VM interface."""
        vm_interface_content_type = ContentType.objects.get_for_model(VMInterface)
        return queryset.filter(
            source_content_type_id=vm_interface_content_type.pk,
            source_object_id=value,
        )

    @staticmethod
    def filter_service_id(queryset, name, value):  # pylint: disable=unused-argument
        """Filter failure states to a specific service."""
        service_content_type = ContentType.objects.get_for_model(Service)
        return queryset.filter(
            source_content_type_id=service_content_type.pk,
            source_object_id=value,
        )

    class Meta:
        """Meta attributes for filter."""

        model = models.DNSRuleFailureState
        fields = "__all__"
