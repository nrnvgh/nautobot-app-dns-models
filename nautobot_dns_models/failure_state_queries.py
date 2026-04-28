"""Shared failure-state queryset helpers."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import OuterRef
from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import Service
from nautobot.virtualization.models import VirtualMachine, VMInterface

from nautobot_dns_models.models import DNSRuleFailureState


def get_device_direct_failures_qs():
    """Return failure states directly attached to the outer device row."""
    device_content_type = ContentType.objects.get_for_model(Device)
    return DNSRuleFailureState.objects.filter(
        source_content_type_id=device_content_type.pk,
        source_object_id=OuterRef("pk"),
    )


def get_device_interface_failures_qs():
    """Return failure states attached to interfaces of the outer device row."""
    interface_content_type = ContentType.objects.get_for_model(Interface)
    interface_ids = Interface.objects.filter(device_id=OuterRef(OuterRef("pk"))).values("pk")
    return DNSRuleFailureState.objects.filter(
        source_content_type_id=interface_content_type.pk,
        source_object_id__in=interface_ids,
    )


def get_interface_direct_failures_qs():
    """Return failure states directly attached to the outer interface row."""
    interface_content_type = ContentType.objects.get_for_model(Interface)
    return DNSRuleFailureState.objects.filter(
        source_content_type_id=interface_content_type.pk,
        source_object_id=OuterRef("pk"),
    )


def get_virtual_machine_direct_failures_qs():
    """Return failure states directly attached to the outer virtual machine row."""
    virtual_machine_content_type = ContentType.objects.get_for_model(VirtualMachine)
    return DNSRuleFailureState.objects.filter(
        source_content_type_id=virtual_machine_content_type.pk,
        source_object_id=OuterRef("pk"),
    )


def get_virtual_machine_interface_failures_qs():
    """Return failure states attached to VM interfaces of the outer virtual machine row."""
    vm_interface_content_type = ContentType.objects.get_for_model(VMInterface)
    vm_interface_ids = VMInterface.objects.filter(virtual_machine_id=OuterRef(OuterRef("pk"))).values("pk")
    return DNSRuleFailureState.objects.filter(
        source_content_type_id=vm_interface_content_type.pk,
        source_object_id__in=vm_interface_ids,
    )


def get_vminterface_direct_failures_qs():
    """Return failure states directly attached to the outer VM interface row."""
    vm_interface_content_type = ContentType.objects.get_for_model(VMInterface)
    return DNSRuleFailureState.objects.filter(
        source_content_type_id=vm_interface_content_type.pk,
        source_object_id=OuterRef("pk"),
    )


def get_service_direct_failures_qs():
    """Return failure states directly attached to the outer service row."""
    service_content_type = ContentType.objects.get_for_model(Service)
    return DNSRuleFailureState.objects.filter(
        source_content_type_id=service_content_type.pk,
        source_object_id=OuterRef("pk"),
    )
