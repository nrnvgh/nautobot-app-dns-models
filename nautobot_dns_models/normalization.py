"""Normalization helpers for DNS-safe names and domain-like values.

Implements per-label normalization with trim/collapse and underscore-led label handling.
"""

import re

_TRANSLATE_TO_HYPHEN = str.maketrans(
    {
        "/": "-",
        "_": "-",
        " ": "-",
    }
)


def normalize_dns_name(value):
    """Normalize a DNS name or domain-like value.

    Policy:
    - Preserve dots as label separators; normalize each label independently.
    - Do not drop empty labels; upstream validation will catch them if present.
    - See _normalize_label() for per-label rules.
    """
    if value is None:
        return value

    # Fast path for empty strings
    if value == "":
        return value

    labels = value.split(".")
    normalized_labels = [_normalize_label(label) for label in labels]
    return ".".join(normalized_labels)


def _normalize_label(label):
    """Normalize a single DNS label according to plugin policy.

    - Lowercase
    - Translate '/', '_', and space to '-'
    - Collapse runs of '-'
    - Trim leading/trailing '-'
    - If the original label starts with '_', preserve a single leading underscore and
      normalize the remainder. Underscores elsewhere are translated to '-'.
    """
    if not label:
        return label

    #
    # This leading underscore handling could be smartened up to only apply to the
    # records which require it (e.g. SRV records).
    leading_underscore = label.startswith("_")
    remainder = label[1:] if leading_underscore else label

    # Apply transforms to the remainder only; preserve a single leading underscore when present
    normalized = remainder.lower().translate(_TRANSLATE_TO_HYPHEN)
    normalized = _collapse_hyphens(normalized)
    normalized = _trim_hyphens(normalized)

    if leading_underscore:
        return f"_{normalized}" if normalized else "_"
    return normalized


def _collapse_hyphens(value):
    """Collapse consecutive hyphens to a single hyphen."""
    return re.sub(r"-+", "-", value)


def _trim_hyphens(value):
    """Trim leading and trailing hyphens from a label."""
    return value.strip("-")
