"""Banner for DNS rule failure states."""

from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.urls import reverse
from django.utils.html import format_html
from nautobot.apps.ui import Banner, BannerClassChoices
from nautobot.dcim.models import Device, Interface
from nautobot.virtualization.models import VirtualMachine, VMInterface

from nautobot_dns_models.constants import SUPPORTED_SOURCE_MODELS
from nautobot_dns_models.models import DNSRuleFailureState


def _get_failure_context(obj):
    """Build failure queryset and filtered list parameters for a supported source object."""
    if isinstance(obj, Device):
        return _get_device_failure_context(obj)

    if isinstance(obj, VirtualMachine):
        return _get_virtual_machine_failure_context(obj)

    return _get_direct_failure_context(obj)


def _get_device_failure_context(device):
    """Return device+interface failure-state queryset and list parameters."""
    device_content_type = ContentType.objects.get_for_model(Device)
    interface_content_type = ContentType.objects.get_for_model(Interface)
    interface_ids = Interface.objects.filter(device_id=device.pk).values("pk")

    queryset = DNSRuleFailureState.objects.filter(
        Q(source_content_type_id=device_content_type.pk, source_object_id=device.pk)
        | Q(source_content_type_id=interface_content_type.pk, source_object_id__in=interface_ids)
    )
    return queryset, {"device_scope_id": str(device.pk)}


def _get_virtual_machine_failure_context(virtual_machine):
    """Return virtual-machine+interface failure-state queryset and list parameters."""
    virtual_machine_content_type = ContentType.objects.get_for_model(VirtualMachine)
    vm_interface_content_type = ContentType.objects.get_for_model(VMInterface)
    vm_interface_ids = VMInterface.objects.filter(virtual_machine_id=virtual_machine.pk).values("pk")
    queryset = DNSRuleFailureState.objects.filter(
        Q(source_content_type_id=virtual_machine_content_type.pk, source_object_id=virtual_machine.pk)
        | Q(source_content_type_id=vm_interface_content_type.pk, source_object_id__in=vm_interface_ids)
    )
    return queryset, {"virtual_machine_scope_id": str(virtual_machine.pk)}


def _get_direct_failure_context(obj):
    """Return direct failure-state queryset and list parameters for one source object."""
    source_content_type = ContentType.objects.get_for_model(type(obj))
    queryset = DNSRuleFailureState.objects.filter(
        source_content_type_id=source_content_type.pk,
        source_object_id=obj.pk,
    )
    return queryset, {
        "source_content_type": f"{source_content_type.app_label}.{source_content_type.model}",
        "source_object_id": str(obj.pk),
    }


def banner(context, *args, **kwargs):
    """Render a banner."""
    if not context.request.user.is_authenticated:
        return None

    obj = context.get("object")
    if obj.__class__ not in SUPPORTED_SOURCE_MODELS:
        return None

    failure_queryset, failure_params = _get_failure_context(obj)
    failure_count = failure_queryset.count()
    if failure_count == 0:
        return None

    failure_list_url = reverse("plugins:nautobot_dns_models:dnsrulefailurestate_list")
    failure_link = f"{failure_list_url}?{urlencode(failure_params)}"
    object_label = obj._meta.verbose_name
    failure_noun = "failure" if failure_count == 1 else "failures"
    content = format_html(
        "<div>This {} has <strong>{}</strong> DNS record creation {}. "
        '<a href="{}">Review DNS reconciliation issues</a>.</div>',
        object_label,
        failure_count,
        failure_noun,
        failure_link,
    )

    return Banner(
        content=content,
        banner_class=BannerClassChoices.CLASS_WARNING,
    )
