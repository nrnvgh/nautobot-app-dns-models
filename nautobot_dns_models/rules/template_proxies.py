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

        We return an empty string when no IP is set to emulate what Jinja2 returns when a variable is undefined.
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
    """Wrap a QuerySet of IPAddress objects to yield proxied results."""

    def __init__(self, queryset, prefetched_ips=None):
        """Store queryset and optional prefetched IP cache."""
        self._queryset = queryset
        self._prefetched_ips = prefetched_ips

    def __str__(self):
        """Join UUID representations for readability."""
        print(f"[TemplateIPAddressQuerySetProxy] __str__: Returning all related IPs as a proxied queryset")
        return " ".join(str(ip) for ip in self.all())

    def __len__(self):  # pragma: no cover - mirrors QuerySet behaviour
        """Return the length via the underlying queryset."""
        prefetched_ips = self._effective_prefetched_ips()
        if prefetched_ips is not None:
            return len(prefetched_ips)

        return self._effective_queryset().count()

    def __iter__(self):
        """Yield proxied IPAddress objects during iteration."""
        print(f"[TemplateIPAddressQuerySetProxy] __iter__: Yielding proxied IPAddress objects during iteration")
        prefetched_ips = self._effective_prefetched_ips()
        if prefetched_ips is not None:
            for ip in prefetched_ips:
                print(f"YIELD from cache ({ip=})")
                yield TemplateIPAddressProxy(ip)

            return

        for ip in self._effective_queryset():
            print(f"YIELD from queryset({ip=})")
            yield TemplateIPAddressProxy(ip)

    def __getitem__(self, item):
        """Allow indexing and slicing while preserving proxies."""
        prefetched_ips = self._effective_prefetched_ips()
        if prefetched_ips is not None:
            result = prefetched_ips[item]
            if isinstance(result, list):
                return TemplateIPAddressQuerySetProxy(
                    self._effective_queryset(),
                    prefetched_ips=result,
                )

            return TemplateIPAddressProxy(result)

        result = self._effective_queryset()[item]
        return self._wrap_result(result)

    def __getattr__(self, name):
        """Delegate attribute access to the queryset, wrapping callables."""
        attr = getattr(self._effective_queryset(), name)
        if callable(attr):
            return self._wrap_callable(attr)

        return attr

    def all(self):
        """Return a proxied queryset of IP addresses."""
        print(f"[TemplateIPAddressQuerySetProxy] Returning all related IPs as a proxied queryset")
        return TemplateIPAddressQuerySetProxy(
            self._effective_queryset().all(),
            prefetched_ips=self._effective_prefetched_ips(),
        )

    def first(self):
        """Return the first proxied IP address, if any."""
        prefetched_ips = self._effective_prefetched_ips()
        if prefetched_ips is not None:
            return TemplateIPAddressProxy(prefetched_ips[0] if prefetched_ips else None)

        ip = self._effective_queryset().first()

        return TemplateIPAddressProxy(ip)

    def last(self):
        """Return the last proxied IP address, if any."""
        prefetched_ips = self._effective_prefetched_ips()
        if prefetched_ips is not None:
            return TemplateIPAddressProxy(prefetched_ips[-1] if prefetched_ips else None)

        ip = self._effective_queryset().last()

        return TemplateIPAddressProxy(ip)

    def _effective_queryset(self):
        """Return underlying queryset as-is."""
        return self._queryset

    def _effective_prefetched_ips(self):
        """Return cached prefetched IPs when available."""
        if self._prefetched_ips is None:
            return None

        return self._prefetched_ips

    def _wrap_result(self, result):
        """Wrap queryset or model results as template proxies."""
        if isinstance(result, QuerySet) and result.model is IPAddress:
            return TemplateIPAddressQuerySetProxy(result)

        if isinstance(result, IPAddress):
            return TemplateIPAddressProxy(result)

        return result

    def _wrap_callable(self, func):
        """Wrap queryset methods so their return values stay proxied."""

        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            return self._wrap_result(result)

        return wrapper


class TemplateIPAddressManagerProxy:
    """Wrap a many-to-many manager returning IPAddress objects."""

    def __init__(self, manager):
        """Store manager and prefetched related-IP cache."""
        self._manager = manager

    def __str__(self):
        """Provide a joined UUID representation."""
        print(f"[TemplateIPAddressManagerProxy] __str__: Returning all related IPs from manager as a proxied queryset")
        return " ".join(str(ip) for ip in self)

    def __bool__(self):
        """Allow truthiness checks without evaluating templates."""
        prefetched_ips = self._get_prefetched_ips()
        if prefetched_ips is not None:
            return bool(prefetched_ips)

        return self._effective_queryset().exists()

    def __len__(self):  # pragma: no cover - mirrors manager behaviour
        """Return the number of related IPs."""
        prefetched_ips = self._get_prefetched_ips()
        if prefetched_ips is not None:
            return len(prefetched_ips)

        return self._effective_queryset().count()

    def __iter__(self):
        """Yield proxied IPs when iterating over the manager."""
        prefetched_ips = self._get_prefetched_ips()
        if prefetched_ips is not None:
            for ip in prefetched_ips:
                yield TemplateIPAddressProxy(ip)

            return

        for ip in self._effective_queryset():
            yield TemplateIPAddressProxy(ip)

    def __getattr__(self, name):
        """Delegate to the manager, wrapping callables."""
        attr = getattr(self._effective_queryset(), name)
        if callable(attr):
            return self._wrap_callable(attr)

        return attr

    def all(self):
        """Return all related IPs as a proxied queryset."""
        print(f"[TemplateIPAddressManagerProxy] Returning all related IPs as a proxied queryset")
        return TemplateIPAddressQuerySetProxy(
            self._effective_queryset(),
            prefetched_ips=self._get_prefetched_ips(),
        )

    def first(self):
        """Return the first related IP as a proxy."""
        prefetched_ips = self._get_prefetched_ips()
        if prefetched_ips is not None:
            return TemplateIPAddressProxy(prefetched_ips[0] if prefetched_ips else None)

        ip = self._effective_queryset().first()

        return TemplateIPAddressProxy(ip)

    def last(self):
        """Return the last related IP as a proxy."""
        prefetched_ips = self._get_prefetched_ips()
        if prefetched_ips is not None:
            return TemplateIPAddressProxy(prefetched_ips[-1] if prefetched_ips else None)

        ip = self._effective_queryset().last()

        return TemplateIPAddressProxy(ip)

    def _effective_queryset(self):
        """Return manager queryset as-is."""
        return self._manager.all()

    def _get_prefetched_ips(self):
        """Read prefetched related IPs from the model prefetch cache."""
        # Fast path: if the relationship was prefetched by the queryset builder,
        # reuse those in-memory rows for first()/last()/len()/bool()/iteration
        # instead of issuing follow-up queryset calls.

        prefetched_cache = getattr(self._manager.instance, "_prefetched_objects_cache", {})
        prefetched_ips = prefetched_cache.get(self._manager.prefetch_cache_name)
        if prefetched_ips is None:
            return None

        return list(prefetched_ips)

    def _wrap_result(self, result):
        """Wrap manager results into template proxies."""
        if isinstance(result, QuerySet) and result.model is IPAddress:
            return TemplateIPAddressQuerySetProxy(result)

        if isinstance(result, IPAddress):
            return TemplateIPAddressProxy(result)

        return result

    def _wrap_callable(self, func):
        """Ensure callable results remain proxied."""

        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            return self._wrap_result(result)

        return wrapper

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