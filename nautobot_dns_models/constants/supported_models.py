"""Canonical supported source-model definitions for DNS rule processing."""

from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import Service
from nautobot.virtualization.models import VirtualMachine, VMInterface

# List of models that are supported for DNS rule processing.
SUPPORTED_SOURCE_MODELS = (
    Device,
    Interface,
    Service,
    VirtualMachine,
    VMInterface,
)

SUPPORTED_SOURCE_MODEL_MAP = {model._meta.label_lower: model for model in SUPPORTED_SOURCE_MODELS}
SUPPORTED_SOURCE_MODEL_CHOICES = tuple((label, label) for label in sorted(SUPPORTED_SOURCE_MODEL_MAP.keys()))

# Parent source-model labels that should optionally cascade reconciliation to child objects.
# Tuple values are: (child_model_label, related_manager_name)
SUPPORTED_PARENT_CHILD_MODEL_RELATIONS = {
    Device._meta.label_lower: (Interface._meta.label_lower, "interfaces"),
    VirtualMachine._meta.label_lower: (VMInterface._meta.label_lower, "interfaces"),
}


def get_app_model_pairs():
    """Build supported source-model `(app_label, model_name)` pairs.

    Returns:
        tuple[tuple[str, str], ...]: Immutable sequence of `(app_label, model_name)` pairs
            derived from `SUPPORTED_SOURCE_MODELS`.
    """
    return tuple((model._meta.app_label, model._meta.model_name) for model in SUPPORTED_SOURCE_MODELS)


def get_content_type_query_params():
    """Build query params that constrain ContentType options to supported models.

    Returns:
        dict[str, list[str]]: Query params containing sorted unique values for:
            - `app_label`
            - `model`
    """
    model_pairs = get_app_model_pairs()
    return {
        "app_label": sorted({app_label for app_label, _ in model_pairs}),
        "model": sorted({model_name for _, model_name in model_pairs}),
    }
