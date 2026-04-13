"""Shared cache container for engine collaborators."""

from dataclasses import dataclass, field


@dataclass
class EngineCache:
    """Caches shared across engine collaborators."""

    applicable_rules_cache: dict = field(default_factory=dict)
    compiled_template_cache: dict = field(default_factory=dict)
    view_lookup_cache: dict = field(default_factory=dict)
    zone_lookup_cache: dict = field(default_factory=dict)
