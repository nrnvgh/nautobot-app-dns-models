"""Record materialization collaborator."""

import logging
from functools import cached_property

from jinja2 import TemplateError

from nautobot_dns_models import models as dns_models
from nautobot_dns_models.exceptions import DNSRuleRenderedValueLookupError, DNSRuleTemplateRenderedEmptyError
from nautobot_dns_models.normalization import normalize_dns_name_if_enabled
from nautobot_dns_models.rules.engine.candidates import RecordCandidateBuilder
from nautobot_dns_models.rules.engine.logging import DEFAULT_ENGINE_LOGGER
from nautobot_dns_models.rules.engine.rendering import TemplateRenderer
from nautobot_dns_models.rules.engine.template_proxies import wrap_for_template

logger = logging.getLogger(__name__)


class RecordMaterializer:
    """Materialize rendered DNS candidate data from rules and objects."""

    def __init__(self, cache, context):
        """Store collaborator references and shared runtime context.

        Args:
            cache: Shared engine cache for template/view/zone lookups.
            context: Engine runtime context (Jinja env and execution settings).
        """
        self._cache = cache
        self._context = context
        self._engine_logger = DEFAULT_ENGINE_LOGGER
        self._record_type_field_hooks = self._build_record_type_field_hooks()
        self._renderer = TemplateRenderer(cache, context)
        self._candidate_builder = RecordCandidateBuilder(
            cache=cache,
            render_template=self._renderer.render_template,
            default_view_getter=self._get_default_view,
            apply_record_type_fields=self._apply_record_type_fields,
        )

    def render_template(self, template_str, context, field_name):
        """Render from cached compiled Jinja templates."""
        return self._renderer.render_template(template_str, context, field_name)

    def requires_ip_context(self, rule):
        """Return whether rule templates require `ip` in render context."""
        return TemplateRenderer.requires_ip_context(rule)

    def calculate_desired_record_data(self, rule, source_obj, phase):
        """Calculate desired DNS record data for one rule/object pair."""
        base_context = {"obj": wrap_for_template(source_obj)}
        rendered_name = self.render_template(rule.name_template, base_context, "name_template")
        shared_record_data = {"name": normalize_dns_name_if_enabled(rendered_name)}
        requires_ip_context = self.requires_ip_context(rule)
        record_variations = self.get_record_data_variations_for_rule(rule, base_context, shared_record_data)

        all_record_data = []
        for record_data in record_variations:
            try:
                if requires_ip_context:
                    record_context = self._build_record_context(base_context, record_data)
                else:
                    record_context = dict(base_context)
                    record_context["record"] = record_data.copy()

                selected_views = self.get_dns_views_for_rule(rule, record_context)
                zones = self.get_zones_for_rule(rule, record_context, selected_views)
                for zone in zones:
                    all_record_data.append({**record_data, "zone": zone})

            except (
                DNSRuleTemplateRenderedEmptyError,
                DNSRuleRenderedValueLookupError,
                TemplateError,
                ValueError,
            ) as exc:
                self._engine_logger.log_candidate_skip(rule, source_obj, record_data, exc, phase=phase)
                continue

        return all_record_data

    def get_record_data_variations_for_rule(self, rule, context, base_record_data):
        """Build list of record data dictionaries (1 for single, N for multiple records)."""
        return self._candidate_builder.get_record_data_variations_for_rule(
            rule=rule,
            context=context,
            base_record_data=base_record_data,
        )

    def get_dns_views_for_rule(self, rule, context):
        """Cache DNS view resolution for repeated templates."""
        return self._candidate_builder.get_dns_views_for_rule(rule, context)

    def get_zones_for_rule(self, rule, context, selected_views):
        """Cache zone lookups by zone-name and view-id tuple."""
        return self._candidate_builder.get_zones_for_rule(rule, context, selected_views)

    def _build_record_context(self, base_context, record_data):
        return self._candidate_builder.build_record_context(base_context, record_data)

    def build_record_context_with_preloaded_ips(self, base_context, record_data, preloaded_ip_by_id):
        """Build context using preloaded batch IP map, with fallback lookup for misses."""
        return self._candidate_builder.build_record_context_with_preloaded_ips(
            base_context, record_data, preloaded_ip_by_id
        )

    @cached_property
    def _default_view(self):
        """Return the default DNS view, cached per engine instance."""
        logger.debug("[default_view] Getting default DNS view")
        return dns_models.DNSView.objects.get(pk=dns_models.get_default_view_pk())

    def _get_default_view(self):
        """Return cached default view via callable for candidate builder."""
        return self._default_view

    def _build_record_type_field_hooks(self):
        """Build record-type hook mapping from local materializer methods."""
        hooks = {}
        for field_name in dir(self):
            if not field_name.startswith("_add_record_type_fields_"):
                continue

            record_type = field_name.removeprefix("_add_record_type_fields_")
            if not record_type:
                continue

            method = getattr(self, field_name, None)
            if method is None:
                continue

            hooks[record_type] = method

        return hooks

    def _apply_record_type_fields(self, rule, context, record_data):
        """Apply per-record-type field hooks when a local hook exists."""
        if record_type_method := self._record_type_field_hooks.get(rule.record_type):
            record_type_method(rule, context, record_data)
