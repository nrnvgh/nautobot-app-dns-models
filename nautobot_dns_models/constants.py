"""Constants for DNS model support."""

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
