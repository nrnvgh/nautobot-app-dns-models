"""Canonical supported source-model definitions for DNS rule processing."""

from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import Service
from nautobot.virtualization.models import VirtualMachine, VMInterface

SUPPORTED_SOURCE_MODELS = (
    Device,
    Interface,
    Service,
    VirtualMachine,
    VMInterface,
)

SUPPORTED_SOURCE_MODEL_LABELS = tuple(model._meta.label_lower for model in SUPPORTED_SOURCE_MODELS)

SUPPORTED_SOURCE_MODEL_MAP = {model._meta.label_lower: model for model in SUPPORTED_SOURCE_MODELS}

SUPPORTED_SOURCE_MODEL_CHOICES = tuple((label, label) for label in sorted(SUPPORTED_SOURCE_MODEL_LABELS))

# Parent source-model labels that should optionally cascade reconciliation to child objects.
# Tuple values are: (child_model_label, related_manager_name)
SUPPORTED_PARENT_CHILD_MODEL_RELATIONS = {
    Device._meta.label_lower: (Interface._meta.label_lower, "interfaces"),
    VirtualMachine._meta.label_lower: (VMInterface._meta.label_lower, "interfaces"),
}
