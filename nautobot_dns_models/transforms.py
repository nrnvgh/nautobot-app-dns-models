"""Transform functions for GUI-based DNS rule builder."""

import re

from .transform_registry import dns_transform

# =============================================================================
# DNS Transform Functions
# =============================================================================


@dns_transform
def lower(value):
    """Convert text to lowercase."""
    return str(value).lower() if value else ""


@dns_transform
def normalize(value):
    """Convert interface names to lowercase alphanumeric (removes /, -, spaces)."""
    if not value:
        return ""

    # Convert to lowercase and replace common separators
    normalized = str(value).lower()
    normalized = normalized.replace("/", "")
    normalized = normalized.replace("-", "")
    normalized = normalized.replace("_", "")
    normalized = normalized.replace(" ", "")

    return normalized


@dns_transform
def remove_interface_prefix(value):
    """Remove common interface prefixes (ethernet, eth, ge-, etc.)."""
    if not value:
        return ""

    prefixes = ["ethernet", "eth", "gigabitethernet", "ge-", "xe-", "et-"]
    value_lower = str(value).lower()

    for prefix in prefixes:
        if value_lower.startswith(prefix):
            return value[len(prefix) :]

    return str(value)


@dns_transform
def remove_spaces(value):
    """Remove all whitespace from text."""
    return str(value).replace(" ", "") if value else ""


@dns_transform
def replace_slashes(value):
    """Replace forward slashes with hyphens for DNS compatibility."""
    return str(value).replace("/", "-") if value else ""


@dns_transform
def truncate_domain(value):
    """Remove domain suffix from FQDN (e.g., 'host.example.com' -> 'host')."""
    if not value:
        return ""

    parts = str(value).split(".")
    return parts[0] if parts else ""


@dns_transform
def upper(value):
    """Convert text to uppercase."""
    return str(value).upper() if value else ""


@dns_transform
def vlan_extract(value):
    """Extract VLAN ID number from interface names (e.g., 'Vlan100' -> '100')."""
    if not value:
        return ""

    match = re.search(r"vlan(\d+)", str(value), re.IGNORECASE)
    return match.group(1) if match else str(value)


# Export the transform functions for backward compatibility
__all__ = [
    "lower",
    "normalize",
    "remove_interface_prefix",
    "remove_spaces",
    "replace_slashes",
    "truncate_domain",
    "upper",
    "vlan_extract",
]
