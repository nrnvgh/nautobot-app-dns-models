"""Logging collaborator for DNS rule engine."""

import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from jinja2 import TemplateError

from nautobot_dns_models.exceptions import DNSRuleRenderedValueLookupError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.rules.engine.enums import EngineReason

logger = logging.getLogger(__name__)


class EngineLogger:
    """Structured logging helper for engine workflows."""

    def log_candidate_invalid_address_uuid(self, rule, invalid_address_id, phase):
        """Emit warning for invalid UUID tokens produced by candidate expansion."""
        logger.warning(
            "dnsrule_candidate_skipped reason=%s rule=%s invalid_address_id=%s",
            EngineReason.INVALID_ADDRESS_UUID,
            rule.name,
            invalid_address_id,
            extra={
                "event": "dnsrule_engine",
                "reason_code": str(EngineReason.INVALID_ADDRESS_UUID),
                "phase": phase,
                "rule_id": str(rule.pk),
                "rule_name": rule.name,
                "record_type": rule.record_type,
                "invalid_address_id": invalid_address_id,
            },
        )

    def log_interface_parent_fallback_failed(self, source_obj, *, resolution_field, parent_type, phase):
        """Emit warning when interface parent fallback cannot resolve scope fields."""
        logger.warning(
            "dnsrule_interface_parent_fallback_failed field=%s source=%s:%s parent_type=%s",
            resolution_field,
            self._safe_model_label(source_obj),
            source_obj.pk,
            parent_type,
            extra={
                "event": "dnsrule_engine",
                "reason_code": str(EngineReason.INTERFACE_PARENT_FALLBACK_FAILED),
                "phase": phase,
                "source_ct": self._safe_model_label(source_obj),
                "source_id": str(source_obj.pk),
                "source_repr": str(source_obj),
                "resolution_field": resolution_field,
                "parent_type": parent_type,
            },
        )

    def log_rule_processing_error(self, rule, source_obj, exc, phase, cleanup=False):
        """Emit hybrid warning for top-level rule processing failures."""
        reason_code = self._infer_reason_code(exc, EngineReason.RULE_PROCESSING_ERROR)
        logger.warning(
            "dnsrule_rule_failed reason=%s rule=%s source=%s:%s cleanup=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            cleanup,
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                cleanup=cleanup,
            ),
        )

    def log_candidate_skip(self, rule, source_obj, record_data, exc, phase):
        """Emit hybrid warning for per-candidate skip decisions."""
        reason_code = self._infer_reason_code(exc, EngineReason.CANDIDATE_ERROR)
        logger.warning(
            "dnsrule_candidate_skipped reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    def log_record_create_failure(self, rule, source_obj, record_data, exc, phase):
        """Emit hybrid warning for record creation failures."""
        reason_code = (
            EngineReason.RECORD_INTEGRITY_ERROR
            if isinstance(exc, IntegrityError)
            else EngineReason.RECORD_VALIDATION_ERROR
        )
        logger.warning(
            "dnsrule_record_create_failed reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    def log_record_update_failure(self, rule, source_obj, record_data, exc, phase):
        """Emit hybrid warning for record update failures."""
        reason_code = (
            EngineReason.RECORD_INTEGRITY_ERROR
            if isinstance(exc, IntegrityError)
            else EngineReason.RECORD_VALIDATION_ERROR
        )
        logger.warning(
            "dnsrule_record_update_failed reason=%s rule=%s source=%s:%s addr=%s error=%s",
            reason_code,
            rule.name,
            self._safe_model_label(source_obj),
            source_obj.pk,
            record_data.get("address_id"),
            exc,
            extra=self._build_log_extra(
                rule=rule,
                source_obj=source_obj,
                reason_code=reason_code,
                phase=phase,
                exc=exc,
                record_data=record_data,
            ),
        )

    @staticmethod
    def _safe_model_label(obj):
        """Return model label if available, else object type name."""
        meta = getattr(obj, "_meta", None)
        return getattr(meta, "label_lower", obj.__class__.__name__)

    @staticmethod
    def _infer_reason_code(exc, default_reason):  # pylint: disable=too-many-return-statements
        """Infer stable reason code from known exception shapes."""
        if isinstance(exc, DNSRuleRenderedValueLookupError):
            if exc.reason_code:
                return exc.reason_code

            return default_reason

        if isinstance(exc, DNSRuleTemplateRenderedEmptyError):
            message = str(exc)
            if "view_template" in message:
                return EngineReason.VIEW_TEMPLATE_EMPTY

            return EngineReason.CANDIDATE_TEMPLATE_ERROR

        if isinstance(exc, TemplateError):
            return EngineReason.CANDIDATE_TEMPLATE_ERROR

        if isinstance(exc, ValidationError):
            message_dict = getattr(exc, "message_dict", {})
            view_errors = " ".join(message_dict.get("view_template", []))
            if "rendered no DNS view names" in view_errors:
                return EngineReason.VIEW_TEMPLATE_EMPTY

            if "not found from view_template" in view_errors:
                return EngineReason.VIEW_NOT_FOUND

            zone_errors = " ".join(message_dict.get("zone_template", []))
            if "does not exist in selected DNS view" in zone_errors:
                return EngineReason.ZONE_NOT_FOUND

        return default_reason

    def _build_log_extra(
        self,
        rule,
        source_obj,
        reason_code,
        phase,
        exc=None,
        record_data=None,
        cleanup=None,
    ):
        """Build structured logging context for hybrid log output."""
        extra = {
            "event": "dnsrule_engine",
            "reason_code": str(reason_code),
            "phase": phase,
            "rule_id": str(rule.pk),
            "rule_name": rule.name,
            "record_type": rule.record_type,
            "source_ct": self._safe_model_label(source_obj),
            "source_id": str(source_obj.pk),
            "source_repr": str(source_obj),
        }
        if exc is not None:
            extra["exception_type"] = type(exc).__name__
            extra["error"] = str(exc)

        if cleanup is not None:
            extra["cleanup"] = cleanup

        if record_data is not None:
            extra["candidate_address_id"] = str(record_data.get("address_id", ""))
            extra["candidate_name"] = record_data.get("name")
            zone = record_data.get("zone")
            extra["candidate_zone_id"] = str(zone.id) if zone is not None else ""

        return extra


DEFAULT_ENGINE_LOGGER = EngineLogger()
