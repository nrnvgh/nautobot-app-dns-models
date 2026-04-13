"""Template-facing proxy wrappers for Nautobot objects used by DNS rule rendering."""

# This module wraps objects used by DNS rule templates so template rendering of IP-related values
# yields IPAddress UUIDs rather than address strings.
#
# If Jinja2 could return live `IPAddress` objects from template evaluation, the engine could consume
# those directly and this proxy layer would be unnecessary. However, since Nautobot supports the use
# of a given IP address in multiple namespaces and since template rendering only returns text the wrapper
# returns the UUID of the IPAddress object.

from functools import cached_property

from django.db.models.query import QuerySet
from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import IPAddress, Service
from nautobot.virtualization.models import VirtualMachine, VMInterface


def wrap_for_template(obj):
    """Return a template proxy for supported Nautobot objects."""
    if isinstance(obj, (Device, VirtualMachine)):
        return DeviceTemplateProxy(obj)

    if isinstance(obj, (Interface, VMInterface)):
        return InterfaceTemplateProxy(obj)

    if isinstance(obj, Service):
        return ServiceTemplateProxy(obj)

    return obj


class TemplateProxyBase:
    """Base proxy that delegates attribute access while allowing value overrides."""

    def __init__(self, obj):
        """Store the wrapped object for delegation."""
        self._obj = obj

    def __repr__(self):
        """Provide a readable debug representation."""
        return f"{type(self).__name__}({self._obj!r})"

    def __str__(self):
        """
        Ensure template usage like ``{{ obj.device }}`` returns Nautobot's native string output.

        Mirrors core behavior so templates render familiar device/interface/service labels.
        """
        return str(self._obj)

    def __getattr__(self, name):
        """Delegate attribute access to the wrapped object, applying value wrapping."""
        value = getattr(self._obj, name)
        return self._wrap_value(value)

    def __dir__(self):
        """Expose both proxy and wrapped object attributes to templates."""
        return sorted({*super().__dir__(), *dir(self._obj)})

    def _wrap_value(self, value):
        """Convert related values into template-friendly proxies."""
        if isinstance(value, TemplateProxyBase):
            return value

        if isinstance(value, IPAddress):
            return TemplateIPAddressProxy(value)

        if isinstance(value, QuerySet) and value.model is IPAddress:
            return TemplateIPAddressQuerySetProxy(value)

        proxied = wrap_for_template(value)

        return proxied


## TODO: sanely handle the case when user uses ip_obj.address or ip_obj.host, even
## TODO: if that's just to throw a loud error.
class TemplateIPAddressProxy(TemplateProxyBase):
    """Proxy an IPAddress object so its string form yields the UUID."""

    def __str__(self):
        """
        Return the UUID string representation.

        Return an empty string when no IP is set to emulate what Jinja2 returns when a variable is undefined.
        """
        if self._obj is None:
            return ""

        return str(self._obj.pk)

    def __bool__(self):  # pragma: no cover - mirrors truthiness of underlying object
        """Return True if the IP is not None."""
        return self._obj is not None

    def __getattr__(self, name):
        """Guard attribute access when no IP is present."""
        if self._obj is None:
            raise AttributeError(name)

        return super().__getattr__(name)

    # These ensure that wrap_for_template() isn't invoked if a template requests the UUID directly.
    @property
    def id(self):
        """Return the UUID string, empty when unset."""
        #
        # Returning self.id here would recurse infinitely.
        return str(self)

    @property
    def pk(self):
        """Alias of ``id`` for templates expecting ``pk``."""
        return self.id


class TemplateIPAddressQuerySetProxy:
    """Wrap IPAddress rows as an in-memory, template-facing collection."""

    def __init__(self, queryset, prefetched_ips=None):
        """Store IPs as a concrete list to avoid hidden queryset round-trips."""
        if prefetched_ips is not None:
            self._ips = list(prefetched_ips)
        else:
            self._ips = list(queryset)

    def __repr__(self):
        """String representation of the proxy."""
        return f"{type(self).__name__}({self._ips!r})"

    def __str__(self):
        """Join UUID representations for readability."""
        return " ".join(str(ip_proxy) for ip_proxy in self)

    def __len__(self):  # pragma: no cover - mirrors QuerySet behavior
        """Return number of rows in this collection."""
        return len(self._ips)

    def __bool__(self):
        """Truthiness matches whether any related IP exists."""
        return bool(self._ips)

    def __iter__(self):
        """Yield proxied IPAddress objects during iteration."""
        for ip_obj in self._ips:
            yield TemplateIPAddressProxy(ip_obj)

    def __getitem__(self, item):
        """Allow indexing and slicing while preserving proxies."""
        result = self._ips[item]
        if isinstance(result, list):
            return TemplateIPAddressQuerySetProxy(queryset=(), prefetched_ips=result)

        return TemplateIPAddressProxy(result)

    def all(self):
        """Return a proxied copy of this in-memory collection."""
        return TemplateIPAddressQuerySetProxy(queryset=(), prefetched_ips=self._ips)

    def first(self):
        """Return the first proxied IP address, if any."""
        return TemplateIPAddressProxy(self._ips[0] if self._ips else None)

    def last(self):
        """Return the last proxied IP address, if any."""
        return TemplateIPAddressProxy(self._ips[-1] if self._ips else None)


class TemplateIPAddressManagerProxy:
    """Wrap a many-to-many manager returning an in-memory proxy collection."""

    def __init__(self, manager):
        """Store manager reference for one-shot list materialization."""
        self._manager = manager

    def __str__(self):
        """Provide a joined UUID representation."""
        return " ".join(str(ip) for ip in self)

    def __bool__(self):
        """Allow truthiness checks without evaluating templates."""
        return bool(self._materialize_ips())

    def __len__(self):  # pragma: no cover - mirrors manager behaviour
        """Return the number of related IPs."""
        return len(self._materialize_ips())

    def __iter__(self):
        """Yield proxied IPs when iterating over the manager."""
        for ip_obj in self._materialize_ips():
            yield TemplateIPAddressProxy(ip_obj)

    def all(self):
        """Return all related IPs as a proxied queryset."""
        return TemplateIPAddressQuerySetProxy(
            queryset=(),
            prefetched_ips=self._materialize_ips(),
        )

    def first(self):
        """Return the first related IP as a proxy."""
        ip_rows = self._materialize_ips()
        return TemplateIPAddressProxy(ip_rows[0] if ip_rows else None)

    def last(self):
        """Return the last related IP as a proxy."""
        ip_rows = self._materialize_ips()
        return TemplateIPAddressProxy(ip_rows[-1] if ip_rows else None)

    # These next two are provided for completeness, but since they don't
    # leverage prefetched IPs, they're significantly slower (when passed
    # arguments) than the all(), first(), etc. It's probably acceptable
    # for most single-object saves, even with cascading changes, but for
    # large batches (e.g. tens of thousands of objects or more) it's really
    # going to be noticable.
    def filter(self, *args, **kwargs):
        """Pass through queryset filtering; empty filters preserve prefetched all()."""
        if not args and not kwargs:
            return self.all()

        return TemplateIPAddressQuerySetProxy(
            queryset=self._manager.filter(*args, **kwargs),
            prefetched_ips=None,
        )

    def exclude(self, *args, **kwargs):
        """Pass through queryset exclude; empty excludes preserve prefetched all()."""
        if not args and not kwargs:
            return self.all()

        return TemplateIPAddressQuerySetProxy(
            queryset=self._manager.exclude(*args, **kwargs),
            prefetched_ips=None,
        )

    def _materialize_ips(self):
        """Materialize related IP rows once, preferring prefetch cache when available."""
        prefetched_cache = getattr(self._manager.instance, "_prefetched_objects_cache", {})
        prefetched_ips = prefetched_cache.get(self._manager.prefetch_cache_name)
        if prefetched_ips is not None:
            return list(prefetched_ips)

        return list(self._manager.all())


#
# Top-level proxy objects.
class DeviceTemplateProxy(TemplateProxyBase):
    """Expose Device attributes with template-friendly overrides."""

    @cached_property
    def primary_ip(self):
        """Return the primary IP UUID for any protocol family."""
        return TemplateIPAddressProxy(self._obj.primary_ip)

    @cached_property
    def primary_ip4(self):
        """Return the primary IPv4 UUID."""
        return TemplateIPAddressProxy(self._obj.primary_ip4)

    @cached_property
    def primary_ip6(self):
        """Return the primary IPv6 UUID."""
        return TemplateIPAddressProxy(self._obj.primary_ip6)


class InterfaceTemplateProxy(TemplateProxyBase):
    """Expose Interface attributes with template-friendly overrides."""

    @cached_property
    def ip_addresses(self):
        """Return a proxied view of the interface IP manager."""
        return TemplateIPAddressManagerProxy(self._obj.ip_addresses)


class ServiceTemplateProxy(TemplateProxyBase):
    """Expose Service attributes with template-friendly overrides."""

    @cached_property
    def ip_addresses(self):
        """Return a proxied view of the service IP manager."""
        return TemplateIPAddressManagerProxy(self._obj.ip_addresses)

    @cached_property
    def parent(self):
        """Return the proxied parent device or virtual machine."""
        return wrap_for_template(self._obj.parent)
