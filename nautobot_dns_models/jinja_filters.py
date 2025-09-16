"""Jinja2 filters for DNS Models plugin."""

import logging

from django_jinja import library

logger = logging.getLogger(__name__)


@library.filter
def ip_address(ip_obj, version=None):
    """
    Extract IPAddress UUID from Nautobot IPAddress objects for DNS record creation.

    This filter returns the UUID/ID of the IPAddress object, which is what DNS record
    models (ARecordModel, AAAARecordModel) expect for their address ForeignKey field.

    Args:
        ip_obj (IPAddress): Nautobot IPAddress object
        version (int): IP version to filter for (4 for IPv4, 6 for IPv6, None for any)

    Returns:
        (UUID): IPAddress object UUID suitable for DNS record ForeignKey fields

    Raises:
        ValueError: If IP version doesn't match the specified version or value is None

    Examples:
        >>> # In a Jinja template with an IPAddress object
        >>> {{ ip_obj | ip_address }}
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        >>> {{ ip_obj | ip_address:4 }}
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        >>> {{ ipv6_obj | ip_address:6 }}
        'b2c3d4e5-f6a7-8901-bcde-f23456789012'
    """
    if ip_obj is None:
        raise ValueError("Cannot extract IP address from None")

    if version is not None and version not in [4, 6]:
        raise ValueError(f"Invalid IP version: {version}. Must be 4, 6, or None")

    if version is None or ip_obj.ip_version == version:
        return ip_obj.id

    raise ValueError(f"IP address is IPv{ip_obj.ip_version}, not IPv{version}: {ip_obj.host}")


@library.filter
def normalize(s):
    """Normalize a value so it's DNS compliant."""
    return s.replace("/", "-").replace(".", "-").lower()
