"""Engine selection helpers for reconciliation modes."""

from __future__ import annotations

from nautobot_dns_models.rules.engine_dns import DNSRuleEngine

rule_engine_default = DNSRuleEngine()

def get_rule_engine():
    """Return default DNS rule engine instance."""
    return rule_engine_default


def get_experimental_pipeline_engine():
    """Return default DNS rule engine instance."""
    # Future simplification option: return a fresh DNSRuleEngine()
    # per call for stronger state isolation, if benchmarked performance impact is negligible.
    return rule_engine_default

