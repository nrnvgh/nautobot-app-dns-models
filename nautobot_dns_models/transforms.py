"""Transform functions for GUI-based DNS rule builder."""

import re

from .transform_registry import dns_transform

# =============================================================================
# DNS Transform Functions
# =============================================================================


@dns_transform(
    name="normalize",
    display_name="Normalize Interface",
    description="Convert interface names to lowercase alphanumeric (removes /, -, spaces)",
)
def interface_normalize(value):
    """Normalize interface names for DNS compatibility."""
    if not value:
        return ""

    # Convert to lowercase and replace common separators
    normalized = str(value).lower()
    normalized = normalized.replace("/", "")
    normalized = normalized.replace("-", "")
    normalized = normalized.replace("_", "")
    normalized = normalized.replace(" ", "")

    return normalized


@dns_transform(
    name="remove_interface_prefix",
    display_name="Remove Interface Prefix",
    description="Remove common interface prefixes (ethernet, eth, ge-, etc.)",
)
def remove_interface_prefix(value):
    """Remove common interface prefixes."""
    if not value:
        return ""

    prefixes = ["ethernet", "eth", "gigabitethernet", "ge-", "xe-", "et-"]
    value_lower = str(value).lower()

    for prefix in prefixes:
        if value_lower.startswith(prefix):
            return value[len(prefix) :]

    return str(value)


@dns_transform(
    name="vlan_extract",
    display_name="Extract VLAN ID",
    description="Extract VLAN ID number from interface names (e.g., 'Vlan100' -> '100')",
)
def vlan_extract(value):
    """Extract VLAN ID from interface names."""
    if not value:
        return ""

    match = re.search(r"vlan(\d+)", str(value), re.IGNORECASE)
    return match.group(1) if match else str(value)


@dns_transform(
    name="replace_slashes",
    display_name="Replace / with -",
    description="Replace forward slashes with hyphens for DNS compatibility",
)
def replace_slashes(value):
    """Replace forward slashes with hyphens."""
    return str(value).replace("/", "-") if value else ""


@dns_transform(name="lower", display_name="Lowercase", description="Convert text to lowercase")
def to_lowercase(value):
    """Convert text to lowercase."""
    return str(value).lower() if value else ""


@dns_transform(name="upper", display_name="Uppercase", description="Convert text to uppercase")
def to_uppercase(value):
    """Convert text to uppercase."""
    return str(value).upper() if value else ""


@dns_transform(name="remove_spaces", display_name="Remove Spaces", description="Remove all whitespace from text")
def remove_spaces(value):
    """Remove all whitespace from text."""
    return str(value).replace(" ", "") if value else ""


@dns_transform(
    name="truncate_domain",
    display_name="Truncate Domain",
    description="Remove domain suffix from FQDN (e.g., 'host.example.com' -> 'host')",
)
def truncate_domain(value):
    """Remove domain suffix from FQDN."""
    if not value:
        return ""

    parts = str(value).split(".")
    return parts[0] if parts else ""


# Export the transform functions for backward compatibility
__all__ = [
    "interface_normalize",
    "remove_interface_prefix",
    "vlan_extract",
    "replace_slashes",
    "to_lowercase",
    "to_uppercase",
    "remove_spaces",
    "truncate_domain",
]
