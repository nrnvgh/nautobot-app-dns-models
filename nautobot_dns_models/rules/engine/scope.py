"""Scope resolution helpers for DNS rule source objects."""

import logging

from nautobot.dcim import models as dcim_models
from nautobot.ipam import models as ipam_models
from nautobot.virtualization import models as virtualization_models

from nautobot_dns_models.rules.engine.constants import PHASE_UNKNOWN, REASON_INTERFACE_PARENT_FALLBACK_FAILED

logger = logging.getLogger(__name__)


class ScopeResolver:
    """Resolve location/tenant scope for supported source object types."""

    def __init__(self, engine_logger):
        """Store structured logger helper used for warning context.

        Args:
            engine_logger: Structured logger helper for model labels/metadata.
        """
        self._engine_logger = engine_logger

    def get_object_location(self, source_obj):
        """Resolve location across supported source object types."""
        if isinstance(source_obj, dcim_models.Interface):
            if source_obj.device:
                return source_obj.device.location

            parent = source_obj.parent
            if isinstance(parent, dcim_models.Device):
                return parent.location

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "location",
                self._engine_logger._safe_model_label(source_obj),  # pylint: disable=protected-access
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._engine_logger._safe_model_label(source_obj),  # pylint: disable=protected-access
                    "source_id": str(source_obj.pk),
                    "source_repr": str(source_obj),
                    "resolution_field": "location",
                    "parent_type": type(parent).__name__,
                },
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

    def get_object_tenant(self, source_obj):
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

            logger.warning(
                "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
                "tenant",
                self._engine_logger._safe_model_label(source_obj),  # pylint: disable=protected-access
                source_obj.pk,
                type(parent).__name__,
                extra={
                    "event": "dnsrule_engine",
                    "reason_code": REASON_INTERFACE_PARENT_FALLBACK_FAILED,
                    "phase": PHASE_UNKNOWN,
                    "source_ct": self._engine_logger._safe_model_label(source_obj),  # pylint: disable=protected-access
                    "source_id": str(source_obj.pk),
                    "source_repr": str(source_obj),
                    "resolution_field": "tenant",
                    "parent_type": type(parent).__name__,
                },
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
