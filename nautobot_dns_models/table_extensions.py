"""Table extensions for nautobot_dns_models."""

import django_tables2 as tables
from django.db.models import Count, IntegerField, Subquery, Value
from django.db.models.functions import Coalesce
from nautobot.apps.tables import TableExtension

from nautobot_dns_models import failure_state_queries


class DNSFailureCountTableExtensionBase(TableExtension):
    """Base table extension for DNS failure counts."""

    model = None
    failure_count_annotation = "nautobot_dns_models_dns_failure_count"
    failure_column_name = "nautobot_dns_models_dns_failures"
    failure_column_label = "DNS Generation Failures"
    failure_filter_param = None

    def __init_subclass__(cls, **kwargs):
        """Build a default count-link column for subclasses."""
        super().__init_subclass__(**kwargs)
        if cls.failure_filter_param is None:
            return

        cls.table_columns = {
            cls.failure_column_name: tables.TemplateColumn(
                verbose_name=cls.failure_column_label,
                template_code=(
                    f"{{% if record.{cls.failure_count_annotation} %}}"
                    "<a href=\"{% url 'plugins:nautobot_dns_models:dnsrulefailurestate_list' %}"
                    f'?{cls.failure_filter_param}={{{{ record.pk }}}}" class="label label-danger">'
                    f"{{{{ record.{cls.failure_count_annotation} }}}}"
                    "</a>"
                    "{% else %}"
                    '<span class="text-muted">&mdash;</span>'
                    "{% endif %}"
                ),
                orderable=False,
            ),
        }
        cls.add_to_default_columns = (cls.failure_column_name,)

    @staticmethod
    def _count_values_queryset(base_queryset):
        """Return scalar values queryset with count(*) for a failure scope."""
        return (
            base_queryset.order_by()
            .annotate(_group=Value(1))
            .values("_group")
            .annotate(total=Count("id"))
            .values("total")
        )

    @classmethod
    def get_failure_state_querysets(cls):  # pragma: no cover - subclass contract
        """Return failure-state querysets scoped to one outer table record."""
        raise NotImplementedError

    @classmethod
    def alter_queryset(cls, queryset):
        """Annotate queryset with aggregate DNS failure count."""
        total_expression = Value(0)
        for failure_count_values in cls.get_failure_state_querysets():
            total_expression = total_expression + Coalesce(
                Subquery(failure_count_values, output_field=IntegerField()),
                Value(0),
            )
        return queryset.annotate(**{cls.failure_count_annotation: total_expression})


class DeviceTableExtension(DNSFailureCountTableExtensionBase):
    """Table extension for Device model DNS failure state counts."""

    model = "dcim.device"
    failure_filter_param = "device_scope_id"

    @classmethod
    def get_failure_state_querysets(cls):
        """Return device and interface failure-state scopes for each device row."""
        device_failures = cls._count_values_queryset(failure_state_queries.get_device_direct_failures_qs())
        interface_failures = cls._count_values_queryset(failure_state_queries.get_device_interface_failures_qs())

        return [device_failures, interface_failures]


class InterfaceTableExtension(DNSFailureCountTableExtensionBase):
    """Table extension for Interface model DNS failure state counts."""

    model = "dcim.interface"
    failure_filter_param = "interface_id"

    @classmethod
    def get_failure_state_querysets(cls):
        """Return interface failure-state scope for each interface row."""
        interface_failures = cls._count_values_queryset(failure_state_queries.get_interface_direct_failures_qs())
        return [interface_failures]


class VirtualMachineTableExtension(DNSFailureCountTableExtensionBase):
    """Table extension for VirtualMachine model DNS failure state counts."""

    model = "virtualization.virtualmachine"
    suffix = "DetailTable"
    failure_filter_param = "virtual_machine_scope_id"

    @classmethod
    def get_failure_state_querysets(cls):
        """Return virtual machine and VM interface failure-state scopes for each VM row."""
        virtual_machine_failures = cls._count_values_queryset(
            failure_state_queries.get_virtual_machine_direct_failures_qs()
        )
        vm_interface_failures = cls._count_values_queryset(
            failure_state_queries.get_virtual_machine_interface_failures_qs()
        )
        return [virtual_machine_failures, vm_interface_failures]


class VMInterfaceTableExtension(DNSFailureCountTableExtensionBase):
    """Table extension for VMInterface model DNS failure state counts."""

    model = "virtualization.vminterface"
    failure_filter_param = "vminterface_id"

    @classmethod
    def get_failure_state_querysets(cls):
        """Return VM interface failure-state scope for each VM interface row."""
        vm_interface_failures = cls._count_values_queryset(failure_state_queries.get_vminterface_direct_failures_qs())
        return [vm_interface_failures]


class ServiceTableExtension(DNSFailureCountTableExtensionBase):
    """Table extension for Service model DNS failure state counts."""

    model = "ipam.service"
    failure_filter_param = "service_id"

    @classmethod
    def get_failure_state_querysets(cls):
        """Return service failure-state scope for each service row."""
        service_failures = cls._count_values_queryset(failure_state_queries.get_service_direct_failures_qs())
        return [service_failures]


table_extensions = [
    DeviceTableExtension,
    InterfaceTableExtension,
    VirtualMachineTableExtension,
    VMInterfaceTableExtension,
    ServiceTableExtension,
]
