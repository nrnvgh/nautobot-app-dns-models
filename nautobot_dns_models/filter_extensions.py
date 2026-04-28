"""Filter extensions for nautobot_dns_models."""

import django_filters
from django import forms
from django.db.models import Exists
from nautobot.apps.filters import FilterExtension, NaturalKeyOrPKMultipleChoiceFilter
from nautobot.apps.forms import DynamicModelMultipleChoiceField, StaticSelect2
from nautobot.core.forms.constants import BOOLEAN_WITH_BLANK_CHOICES

from nautobot_dns_models import failure_state_queries
from nautobot_dns_models.models import DNSView


def _filter_has_failures(queryset, value, exists_expr):
    """Apply a boolean has-failures filter against an Exists expression."""
    if value is None:
        return queryset
    return queryset.filter(exists_expr) if value else queryset.exclude(exists_expr)


def filter_device_has_failures(queryset, name, value):  # pylint: disable=unused-argument
    """Filter devices by whether they have any DNS failure states."""
    exists_expr = Exists(failure_state_queries.get_device_direct_failures_qs()) | Exists(
        failure_state_queries.get_device_interface_failures_qs()
    )
    return _filter_has_failures(queryset, value, exists_expr)


def filter_interface_has_failures(queryset, name, value):  # pylint: disable=unused-argument
    """Filter interfaces by whether they have any DNS failure states."""
    exists_expr = Exists(failure_state_queries.get_interface_direct_failures_qs())
    return _filter_has_failures(queryset, value, exists_expr)


def filter_virtual_machine_has_failures(queryset, name, value):  # pylint: disable=unused-argument
    """Filter virtual machines by whether they have any DNS failure states."""
    exists_expr = Exists(failure_state_queries.get_virtual_machine_direct_failures_qs()) | Exists(
        failure_state_queries.get_virtual_machine_interface_failures_qs()
    )
    return _filter_has_failures(queryset, value, exists_expr)


def filter_vminterface_has_failures(queryset, name, value):  # pylint: disable=unused-argument
    """Filter VM interfaces by whether they have any DNS failure states."""
    exists_expr = Exists(failure_state_queries.get_vminterface_direct_failures_qs())
    return _filter_has_failures(queryset, value, exists_expr)


def filter_service_has_failures(queryset, name, value):  # pylint: disable=unused-argument
    """Filter services by whether they have any DNS failure states."""
    exists_expr = Exists(failure_state_queries.get_service_direct_failures_qs())
    return _filter_has_failures(queryset, value, exists_expr)


class PrefixFilterExtension(FilterExtension):
    """Filter extensions for ipam.Prefix."""

    model = "ipam.prefix"

    filterset_fields = {
        "nautobot_dns_models_dns_views": NaturalKeyOrPKMultipleChoiceFilter(
            queryset=DNSView.objects.all(), label="DNS Views (name or ID)", field_name="dns_views"
        )
    }

    filterform_fields = {
        "nautobot_dns_models_dns_views": DynamicModelMultipleChoiceField(
            queryset=DNSView.objects.all(),
            required=False,
            label="DNS Views",
        )
    }


class DNSFailureFilterExtensionBase(FilterExtension):
    """Base filter extension for DNS record generation failure boolean filter."""

    model = None
    has_failures_method = None
    has_failures_field_name = "nautobot_dns_models_has_failures"
    has_failures_label = "Has DNS Record Generation Failures"

    def __init_subclass__(cls, **kwargs):
        """Build standard has-failures filter/form fields for subclasses."""
        super().__init_subclass__(**kwargs)
        if cls.model is None or cls.has_failures_method is None:
            return

        cls.filterset_fields = {
            cls.has_failures_field_name: django_filters.BooleanFilter(
                method=cls.has_failures_method,
                label=cls.has_failures_label,
            ),
        }
        cls.filterform_fields = {
            cls.has_failures_field_name: forms.NullBooleanField(
                required=False,
                label=cls.has_failures_label,
                widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
            ),
        }


class DeviceFilterExtension(DNSFailureFilterExtensionBase):
    """Filter extensions for dcim.Device."""

    model = "dcim.device"
    has_failures_method = filter_device_has_failures


class InterfaceFilterExtension(DNSFailureFilterExtensionBase):
    """Filter extensions for dcim.Interface."""

    model = "dcim.interface"
    has_failures_method = filter_interface_has_failures


class VirtualMachineFilterExtension(DNSFailureFilterExtensionBase):
    """Filter extensions for virtualization.VirtualMachine."""

    model = "virtualization.virtualmachine"
    has_failures_method = filter_virtual_machine_has_failures


class VMInterfaceFilterExtension(DNSFailureFilterExtensionBase):
    """Filter extensions for virtualization.VMInterface."""

    model = "virtualization.vminterface"
    has_failures_method = filter_vminterface_has_failures


class ServiceFilterExtension(DNSFailureFilterExtensionBase):
    """Filter extensions for ipam.Service."""

    model = "ipam.service"
    has_failures_method = filter_service_has_failures


filter_extensions = [
    DeviceFilterExtension,
    InterfaceFilterExtension,
    VirtualMachineFilterExtension,
    VMInterfaceFilterExtension,
    ServiceFilterExtension,
    PrefixFilterExtension,
]
