"""Engine selection helpers for reconciliation modes."""

from __future__ import annotations

from nautobot_dns_models.rules.engine_experimental import ExperimentalDNSRuleEngine
from nautobot_dns_models.rules.engine_experimental_pipeline import ExperimentalPipelineDNSRuleEngine
from nautobot_dns_models.rules.engine_fast import FastDNSRuleEngine
from nautobot_dns_models.rules.engine_safe import SafeDNSRuleEngine

rule_engine_safe = SafeDNSRuleEngine()
rule_engine_fast = FastDNSRuleEngine()
rule_engine_experimental = ExperimentalDNSRuleEngine()
rule_engine_experimental_pipeline = ExperimentalPipelineDNSRuleEngine()


def get_rule_engine(performance_mode: str | None):
    """Return safe/fast engine instance for the requested mode."""
    mode = (performance_mode or "safe").strip().lower()
    if mode == "fast":
        return rule_engine_fast
    if mode == "experimental":
        return rule_engine_experimental
    return rule_engine_safe


def get_experimental_pipeline_engine():
    """Return dedicated experimental engine for batch-native pipeline job."""
    # Future simplification option: return a fresh ExperimentalPipelineDNSRuleEngine()
    # per call for stronger state isolation, if benchmarked performance impact is negligible.
    return rule_engine_experimental_pipeline

