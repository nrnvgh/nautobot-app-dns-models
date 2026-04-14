"""Scope resolution helpers for DNS rule source objects."""

from nautobot.dcim import models as dcim_models
from nautobot.ipam import models as ipam_models
from nautobot.virtualization import models as virtualization_models

from nautobot_dns_models.rules.engine.constants import PHASE_UNKNOWN
from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER


class ScopeResolver:
    """Resolve location/tenant scope for supported source object types."""

    def __init__(self):
        """Store structured logger helper used for warning context."""
        self._engine_logger = DEFAULT_ENGINE_LOGGER

    def get_object_location(self, source_obj):  # pylint: disable=too-many-return-statements
        """Resolve location across supported source object types."""
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.location

            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.location

            self._engine_logger.log_interface_parent_fallback_failed(
                source_obj=source_obj,
                resolution_field="location",
                parent_type=type(parent).__name__,
                phase=PHASE_UNKNOWN,
            )
            return None

        if isinstance(source_obj, virtualization_models.VMInterface):
            if source_obj.virtual_machine:
                return source_obj.virtual_machine.location

            return None

        if isinstance(source_obj, dcim_models.Device):
            return source_obj.location

        if isinstance(source_obj, virtualization_models.VirtualMachine):
            return source_obj.location

        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.location

            if source_obj.virtual_machine:
                return source_obj.virtual_machine.location

            return None

        return None

    def get_object_tenant(self, source_obj):  # pylint: disable=too-many-return-statements
        """Resolve tenant across supported source object types."""
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.tenant

            module = source_obj.module
            if module and module.tenant:
                return module.tenant

            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.tenant

            self._engine_logger.log_interface_parent_fallback_failed(
                source_obj=source_obj,
                resolution_field="tenant",
                parent_type=type(parent).__name__,
                phase=PHASE_UNKNOWN,
            )
            return None

        if isinstance(source_obj, virtualization_models.VMInterface):
            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.tenant or vm.cluster.tenant

            return None

        if isinstance(source_obj, dcim_models.Device):
            return source_obj.tenant

        if isinstance(source_obj, virtualization_models.VirtualMachine):
            return source_obj.tenant or source_obj.cluster.tenant

        if isinstance(source_obj, ipam_models.Service):
            if source_obj.device:
                return source_obj.device.tenant

            if source_obj.virtual_machine:
                vm = source_obj.virtual_machine
                return vm.tenant or vm.cluster.tenant

            return None

        return None
