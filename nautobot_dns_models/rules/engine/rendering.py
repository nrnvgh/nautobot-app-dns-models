"""Template rendering helpers for DNS rule materialization."""

from __future__ import annotations

import re

from nautobot_dns_models.exceptions import DNSRuleTemplateRenderedEmptyError


class TemplateRenderer:
    """Render templates and determine context requirements."""

    def __init__(self, cache, context):
        """Store template cache and Jinja environment context.

        Args:
            cache: Shared engine cache for compiled template reuse.
            context: Engine runtime context providing the Jinja environment.
        """
        self._cache = cache
        self._context = context

    def render_template(self, template_str, context, field_name):
        """Render from cached compiled Jinja templates."""
        if "{{" not in template_str and "{%" not in template_str and "{#" not in template_str:
            result = template_str.strip()
            if not result:
                raise DNSRuleTemplateRenderedEmptyError(field_name, template_str, list(context.keys()))
            return result

        compiled_template = self._cache.compiled_template_cache.get(template_str)
        if compiled_template is None:
            if len(self._cache.compiled_template_cache) >= 1024:
                self._cache.compiled_template_cache.clear()

            compiled_template = self._context.jinja_env.from_string(template_str)
            self._cache.compiled_template_cache[template_str] = compiled_template

        raw_result = compiled_template.render(context)
        result = raw_result.strip()
        if not result:
            raise DNSRuleTemplateRenderedEmptyError(field_name, template_str, list(context.keys()))

        if "{{ no such element:" in raw_result:
            raise DNSRuleTemplateRenderedEmptyError(field_name, f"{template_str} → {result}", list(context.keys()))

        return result

    @staticmethod
    def requires_ip_context(rule):
        """Return whether rule templates reference `ip` context."""
        template_text = " ".join([rule.view_template or "", rule.zone_template or ""])
        return bool(re.search(r"\bip\b", template_text))
