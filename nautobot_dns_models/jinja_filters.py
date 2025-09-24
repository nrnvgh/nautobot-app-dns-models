"""Jinja2 filters for DNS Models plugin."""

import logging
from collections.abc import Iterable

from django_jinja import library
from nautobot.ipam.models import IPAddress

logger = logging.getLogger(__name__)


@library.filter
def ip_address(ip_obj, version=None):
    """
    Extract IPAddress UUID from Nautobot IPAddress objects for DNS record creation.

    This filter returns the UUID/ID of the IPAddress object, which is what DNS record
    models (ARecord, AAAARecord) expect for their address ForeignKey field.

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
        >>> {{ ip_obj | ip_address(4) }}
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        >>> {{ ipv6_obj | ip_address(6) }}
        'b2c3d4e5-f6a7-8901-bcde-f23456789012'
        >>> # With collections (multiple IPs)
        >>> {{ obj.ip_addresses.all | ip_address }}
        'uuid1 uuid2 uuid3'
        >>> {{ obj.ip_addresses.all | ip_address(4) }}
        'uuid1 uuid2'
    """
    if ip_obj is None:
        raise ValueError("Cannot extract IP address from None")

    if isinstance(ip_obj, IPAddress):
        ip_list = [ip_obj]
    elif isinstance(ip_obj, Iterable):
        ip_list = ip_obj
    else:
        raise ValueError(f"Invalid IP object (type={type(ip_obj)})")

    if version is not None and version not in [4, 6]:
        raise ValueError(f"Invalid IP version: {version}. Must be 4, 6, or None")

    result_list = []
    for ip in ip_list:
        if version is None or ip.ip_version == version:
            result_list.append(str(ip.id))

    logger.debug(f"ip_address: {result_list}")
    if result_list:
        logger.debug(f"returning: {result_list}")
        return " ".join(result_list)

    # Handle different error scenarios based on input type
    if isinstance(ip_obj, IPAddress):
        # Single IP object that didn't match version filter
        raise ValueError(f"IP address is IPv{ip_obj.ip_version}, not IPv{version}: {ip_obj.host}")
    else:
        # Collection/QuerySet with no matching IPs
        if version is not None:
            raise ValueError(f"No IPv{version} addresses found in collection")
        else:
            raise ValueError("No IP addresses found in collection")


@library.filter
def normalize(s):
    """Normalize a value so it's DNS compliant."""
    return s.replace("/", "-").replace(".", "-").lower()
