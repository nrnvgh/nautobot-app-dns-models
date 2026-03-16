"""Engine selection helpers for reconciliation modes."""

from nautobot_dns_models.rules.engine_dns import DNSRuleEngine


def get_rule_engine():
    """Return a fresh DNS rule engine instance."""
    return DNSRuleEngine()
