"""Template-facing proxy wrappers for Nautobot objects."""

# Needed for forward references until python 3.11
from __future__ import annotations

from functools import cached_property
from typing import Any, Callable

from django.db.models.manager import BaseManager
from django.db.models.query import QuerySet
from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import IPAddress, Service
from nautobot.virtualization.models import VirtualMachine, VMInterface


class TemplateProxyBase:
    """Base proxy that delegates attribute access while allowing value overrides."""

    def __init__(self, obj: Any) -> None:
        """Store the wrapped object for delegation."""
        self._obj = obj

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the wrapped object, applying value wrapping."""
        value = getattr(self._obj, name)
        return self._wrap_value(value)

    def __str__(self) -> str:
        """
        Ensure template usage like ``{{ obj.device }}`` returns Nautobot's native string output.

        Mirrors core behavior so templates render familiar device/interface/service labels.
        """
        return str(self._obj)

    def __repr__(self) -> str:
        """Provide a readable debug representation."""
        return f"{self.__class__.__name__}({self._obj!r})"

    def __dir__(self) -> list[str]:
        """Expose both proxy and wrapped object attributes to templates."""
        return sorted({*super().__dir__(), *dir(self._obj)})

    def _wrap_value(self, value: Any) -> Any:
        """Convert related values into template-friendly proxies."""
        if isinstance(value, TemplateProxyBase):
            return value
        if isinstance(value, IPAddress):
            return TemplateIPAddressProxy(value)
        if isinstance(value, QuerySet) and value.model is IPAddress:
            return TemplateIPAddressQuerySetProxy(value)

        proxied = wrap_for_template(value)
        return proxied


class TemplateIPAddressProxy(TemplateProxyBase):
    """Proxy an IPAddress object so its string form yields the UUID."""

    def __bool__(self) -> bool:  # pragma: no cover - mirrors truthiness of underlying object
        """Return True if the IP is not None."""
        return self._obj is not None

    def __getattr__(self, name: str) -> Any:
        """Guard attribute access when no IP is present."""
        if self._obj is None:
            raise AttributeError(name)
        return super().__getattr__(name)

    def __str__(self) -> str:
        """
        Return the UUID string representation.

        We return an empty string when no IP is set to emulate what Jinja2 returns when a variable is undefined.
        """
        if self._obj is None:
            return ""

        return str(self._obj.pk)

    def __repr__(self) -> str:
        """Provide a readable debug representation."""
        return f"TemplateIPAddressProxy({str(self)})"

    def __format__(self, format_spec: str) -> str:
        """Respect format specifiers while returning the UUID."""
        return format(str(self), format_spec)

    @property
    def id(self) -> str:
        """Return the UUID string, empty when unset."""
        #
        # This gets a little referential, so: this triggers a call to __str__, which returns the UUID (or empty string)
        return str(self)

    @property
    def pk(self) -> str:
        """Alias of ``id`` for templates expecting ``pk``."""
        return self.id


class TemplateIPAddressQuerySetProxy:
    """Wrap a QuerySet of IPAddress objects to yield proxied results."""

    def __init__(self, queryset: QuerySet[IPAddress]) -> None:
        """Store the queryset for later evaluation."""
        self._queryset = queryset

    def __iter__(self):
        """Yield proxied IPAddress objects during iteration."""
        for ip in self._queryset:
            yield TemplateIPAddressProxy(ip)

    def __getitem__(self, item: Any):
        """Allow indexing and slicing while preserving proxies."""
        result = self._queryset[item]
        return self._wrap_result(result)

    def __len__(self) -> int:  # pragma: no cover - mirrors QuerySet behaviour
        """Return the length via the underlying queryset."""
        return self._queryset.count()

    def __str__(self) -> str:
        """Join UUID representations for readability."""
        return " ".join(str(ip) for ip in self.all())

    def all(self) -> TemplateIPAddressQuerySetProxy:
        """Return a proxied queryset of IP addresses."""
        return TemplateIPAddressQuerySetProxy(self._queryset.all())

    def first(self) -> TemplateIPAddressProxy | None:
        """Return the first proxied IP address, if any."""
        ip = self._queryset.first()
        return TemplateIPAddressProxy(ip)

    def last(self) -> TemplateIPAddressProxy | None:
        """Return the last proxied IP address, if any."""
        ip = self._queryset.last()
        return TemplateIPAddressProxy(ip)

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the queryset, wrapping callables."""
        attr = getattr(self._queryset, name)
        if callable(attr):
            return self._wrap_callable(attr)
        return attr

    def _wrap_callable(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap queryset methods so their return values stay proxied."""

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            return self._wrap_result(result)

        return wrapper

    @staticmethod
    def _wrap_result(result: Any) -> Any:
        """Wrap queryset or model results as template proxies."""
        if isinstance(result, QuerySet) and result.model is IPAddress:
            return TemplateIPAddressQuerySetProxy(result)
        if isinstance(result, IPAddress):
            return TemplateIPAddressProxy(result)
        return result


class TemplateIPAddressManagerProxy:
    """Wrap a many-to-many manager returning IPAddress objects."""

    def __init__(self, manager: BaseManager[IPAddress]) -> None:
        """Store the underlying manager."""
        self._manager = manager

    def __iter__(self):
        """Yield proxied IPs when iterating over the manager."""
        for ip in self._manager.all():
            yield TemplateIPAddressProxy(ip)

    def __len__(self) -> int:  # pragma: no cover - mirrors manager behaviour
        """Return the number of related IPs."""
        return self._manager.count()

    def __str__(self) -> str:
        """Provide a joined UUID representation."""
        return " ".join(str(ip) for ip in self)

    def __bool__(self) -> bool:
        """Allow truthiness checks without evaluating templates."""
        return self._manager.exists()

    def all(self) -> TemplateIPAddressQuerySetProxy:
        """Return all related IPs as a proxied queryset."""
        return TemplateIPAddressQuerySetProxy(self._manager.all())

    def first(self) -> TemplateIPAddressProxy | None:
        """Return the first related IP as a proxy."""
        ip = self._manager.first()
        return TemplateIPAddressProxy(ip)

    def last(self) -> TemplateIPAddressProxy | None:
        """Return the last related IP as a proxy."""
        ip = self._manager.last()
        return TemplateIPAddressProxy(ip)

    def __getattr__(self, name: str) -> Any:
        """Delegate to the manager, wrapping callables."""
        attr = getattr(self._manager, name)
        if callable(attr):
            return self._wrap_callable(attr)
        return attr

    def _wrap_callable(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Ensure callable results remain proxied."""

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            return self._wrap_result(result)

        return wrapper

    @staticmethod
    def _wrap_result(result: Any) -> Any:
        """Wrap manager results into template proxies."""
        if isinstance(result, QuerySet) and result.model is IPAddress:
            return TemplateIPAddressQuerySetProxy(result)
        if isinstance(result, IPAddress):
            return TemplateIPAddressProxy(result)
        return result


class DeviceTemplateProxy(TemplateProxyBase):
    """Expose Device attributes with template-friendly overrides."""

    @cached_property
    def primary_ip(self) -> TemplateIPAddressProxy | None:
        """Return the primary IP UUID for any protocol family."""
        ip = getattr(self._obj, "primary_ip", None)
        return TemplateIPAddressProxy(ip) if ip else None

    @cached_property
    def primary_ip4(self) -> TemplateIPAddressProxy | None:
        """Return the primary IPv4 UUID."""
        ip = getattr(self._obj, "primary_ip4", None)
        return TemplateIPAddressProxy(ip) if ip else None

    @cached_property
    def primary_ip6(self) -> TemplateIPAddressProxy | None:
        """Return the primary IPv6 UUID."""
        ip = getattr(self._obj, "primary_ip6", None)
        return TemplateIPAddressProxy(ip) if ip else None


class InterfaceTemplateProxy(TemplateProxyBase):
    """Expose Interface attributes with template-friendly overrides."""

    @cached_property
    def ip_addresses(self) -> TemplateIPAddressManagerProxy:
        """Return a proxied view of the interface IP manager."""
        return TemplateIPAddressManagerProxy(self._obj.ip_addresses)


class ServiceTemplateProxy(TemplateProxyBase):
    """Expose Service attributes with template-friendly overrides."""

    @cached_property
    def ip_addresses(self) -> TemplateIPAddressManagerProxy:
        """Return a proxied view of the service IP manager."""
        return TemplateIPAddressManagerProxy(self._obj.ip_addresses)

    @cached_property
    def parent(self) -> Any:
        """Return the proxied parent device or virtual machine."""
        return wrap_for_template(self._obj.parent)


def wrap_for_template(obj: Any) -> Any:
    """Return a template proxy for supported Nautobot objects."""
    if isinstance(obj, (Device, VirtualMachine)):
        return DeviceTemplateProxy(obj)
    if isinstance(obj, (Interface, VMInterface)):
        return InterfaceTemplateProxy(obj)
    if isinstance(obj, Service):
        return ServiceTemplateProxy(obj)
    return obj
