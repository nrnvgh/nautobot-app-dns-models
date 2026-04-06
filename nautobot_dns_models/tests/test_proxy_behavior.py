"""Unit tests for Jinja template proxy objects."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from nautobot_dns_models.rules.template_proxies import wrap_for_template
from nautobot_dns_models.tests.test_rule_engine import BaseRuleEngineMixin


class Mixins:
    """Mixins are nested to avoid being discovered as test cases by Django. This mimics Nautobot core's test structure."""

    class PrimaryIPProxyMixin(BaseRuleEngineMixin):
        """Common assertions for primary IP proxy behavior on devices and VMs."""

        proxy_target_attr = ""

        @classmethod
        def setUpTestData(cls):
            super().setUpTestData()

            if not cls.proxy_target_attr:
                raise ValueError("proxy_target_attr must be defined on subclasses")

            cls.proxy_target = getattr(cls, cls.proxy_target_attr)
            cls.ip_address = cls.ip_addresses[0]
            cls.ip_address2 = cls.ip_addresses[1]
            cls.ipv6_address = cls.ipv6_addresses[0]
            cls.primary_ipv6 = cls.ipv6_address

        def _assert_uuid(self, proxy_field, expected_pk):
            self.assertTrue(proxy_field)
            self.assertEqual(str(proxy_field), str(expected_pk))
            self.assertEqual(proxy_field.id, str(expected_pk))
            self.assertEqual(proxy_field.pk, str(expected_pk))

        def test_primary_ip4_returns_uuid(self):
            """Ensure IPv4 primary proxies render UUID strings."""

            self.proxy_target.primary_ip4 = self.ip_address
            self.proxy_target.save()

            proxy = wrap_for_template(self.proxy_target)
            self._assert_uuid(proxy.primary_ip4, self.ip_address.pk)

            self.proxy_target.primary_ip4 = None
            self.proxy_target.save()

            proxy = wrap_for_template(self.proxy_target)
            self.assertFalse(proxy.primary_ip4)
            self.assertEqual(str(proxy.primary_ip4), "")

        def test_primary_ip_returns_uuid(self):
            """Ensure combined primary_ip selects the correct UUID."""

            self.proxy_target.primary_ip4 = self.ip_address
            self.proxy_target.primary_ip6 = None
            self.proxy_target.save()

            proxy = wrap_for_template(self.proxy_target)
            self._assert_uuid(proxy.primary_ip, self.ip_address.pk)

            self.proxy_target.primary_ip6 = self.primary_ipv6
            self.proxy_target.save()

            proxy = wrap_for_template(self.proxy_target)
            self._assert_uuid(proxy.primary_ip, self.primary_ipv6.pk)

        def test_primary_ip_unset_returns_empty_string(self):
            """An unset primary_ip renders as an empty string."""

            proxy = wrap_for_template(self.proxy_target)
            self.assertFalse(proxy.primary_ip)
            self.assertEqual(str(proxy.primary_ip), "")

        def test_primary_ip6_returns_uuid(self):
            """Ensure IPv6 primary proxies render UUID strings."""

            self.proxy_target.primary_ip6 = self.primary_ipv6
            self.proxy_target.save()

            proxy = wrap_for_template(self.proxy_target)
            self._assert_uuid(proxy.primary_ip6, self.primary_ipv6.pk)

            self.proxy_target.primary_ip6 = None
            self.proxy_target.save()

            proxy = wrap_for_template(self.proxy_target)
            self.assertFalse(proxy.primary_ip6)
            self.assertEqual(str(proxy.primary_ip6), "")

    class IPAddressManagerMixin(BaseRuleEngineMixin):
        """Common assertions for ip_addresses manager proxies."""

        manager_source_attr = ""

        @classmethod
        def setUpTestData(cls):
            super().setUpTestData()
            if not cls.manager_source_attr:
                raise ValueError("manager_source_attr must be defined on subclasses")
            cls.ip_address = cls.ip_addresses[0]
            cls.ip_address2 = cls.ip_addresses[1]
            cls.ipv6_address = cls.ipv6_addresses[0]

        def setUp(self):
            super().setUp()
            source = getattr(self, self.manager_source_attr)
            source.ip_addresses.set([self.ip_address, self.ip_address2])

        def _get_manager_proxy(self):
            return wrap_for_template(getattr(self, self.manager_source_attr)).ip_addresses

        def _get_prefetched_manager_proxy(self):
            source = getattr(self, self.manager_source_attr)
            prefetched_source = source.__class__.objects.prefetch_related("ip_addresses").get(pk=source.pk)
            self.assertIn("ip_addresses", getattr(prefetched_source, "_prefetched_objects_cache", {}))
            return wrap_for_template(prefetched_source).ip_addresses

        def test_all_returns_space_delimited_uuids(self):
            """str() on ip_addresses.all() should join UUIDs with spaces."""
            proxy_manager = self._get_manager_proxy()
            expected = f"{self.ip_address.pk} {self.ip_address2.pk}"
            self.assertEqual(str(proxy_manager.all()), expected)

        def test_iteration_yields_proxies(self):
            """Iterating over ip_addresses yields TemplateIPAddressProxy instances."""
            proxy_manager = self._get_manager_proxy()
            uuid_list = [str(ip) for ip in proxy_manager]
            expected = [str(self.ip_address.pk), str(self.ip_address2.pk)]
            self.assertEqual(uuid_list, expected)

        def test_first_returns_uuid(self):
            """first() should return a proxied IP address with UUID str()."""
            proxy_manager = self._get_manager_proxy()
            first_proxy = proxy_manager.first()
            self.assertEqual(str(first_proxy), str(self.ip_address.pk))

        def test_last_returns_uuid(self):
            """last() should return the final proxied IP address with UUID str()."""
            proxy_manager = self._get_manager_proxy()
            last_proxy = proxy_manager.last()
            self.assertEqual(str(last_proxy), str(self.ip_address2.pk))

        def test_all_returns_empty_string_when_no_ips(self):
            """When no IPs exist, str(all()) should be empty."""
            source = getattr(self, self.manager_source_attr)
            source.ip_addresses.clear()
            proxy_manager = self._get_manager_proxy()
            self.assertEqual(str(proxy_manager.all()), "")

        def test_first_and_last_are_empty_when_no_ips(self):
            """Empty managers should yield falsey proxies with empty strings."""
            source = getattr(self, self.manager_source_attr)
            source.ip_addresses.clear()
            proxy_manager = self._get_manager_proxy()
            first_proxy = proxy_manager.first()
            last_proxy = proxy_manager.last()
            self.assertFalse(first_proxy)
            self.assertEqual(str(first_proxy), "")
            self.assertFalse(last_proxy)
            self.assertEqual(str(last_proxy), "")

        def test_filter_without_args_uses_prefetch_cache(self):
            """Empty filter() should preserve all() behavior without extra DB queries."""
            proxy_manager = self._get_prefetched_manager_proxy()
            expected = str(proxy_manager.all())

            with CaptureQueriesContext(connection) as query_context:
                result = str(proxy_manager.filter())

            self.assertEqual(result, expected)
            self.assertEqual(len(query_context), 0)

        def test_exclude_without_args_uses_prefetch_cache(self):
            """Empty exclude() should preserve all() behavior without extra DB queries."""
            proxy_manager = self._get_prefetched_manager_proxy()
            expected = str(proxy_manager.all())

            with CaptureQueriesContext(connection) as query_context:
                result = str(proxy_manager.exclude())

            self.assertEqual(result, expected)
            self.assertEqual(len(query_context), 0)

        def test_filter_with_lookup_returns_filtered_proxy_rows(self):
            """Non-empty filter() should return proxied, filtered IP rows."""
            source = getattr(self, self.manager_source_attr)
            source.ip_addresses.set([self.ip_address, self.ip_address2, self.ipv6_address])
            proxy_manager = self._get_manager_proxy()

            filtered = proxy_manager.filter(ip_version=6)
            rendered_values = [str(ip_proxy) for ip_proxy in filtered]

            self.assertEqual(rendered_values, [str(self.ipv6_address.pk)])
            self.assertEqual(str(filtered.first()), str(self.ipv6_address.pk))

        def test_exclude_with_lookup_returns_filtered_proxy_rows(self):
            """Non-empty exclude() should return proxied rows after exclusion."""
            source = getattr(self, self.manager_source_attr)
            source.ip_addresses.set([self.ip_address, self.ip_address2, self.ipv6_address])
            proxy_manager = self._get_manager_proxy()

            filtered = proxy_manager.exclude(ip_version=6)
            rendered_values = {str(ip_proxy) for ip_proxy in filtered}

            self.assertEqual(rendered_values, {str(self.ip_address.pk), str(self.ip_address2.pk)})

        def test_unsupported_queryset_chain_raises_attribute_error(self):
            """Unsupported queryset-style chaining should fail loudly."""
            proxy_manager = self._get_manager_proxy()
            filtered = proxy_manager.filter(ip_version=4)

            with self.assertRaises(AttributeError):
                filtered.exclude(ip_version=6)


class DevicePrimaryIPProxyTestCase(Mixins.PrimaryIPProxyMixin, TestCase):
    """Device proxy should mirror native primary IP behavior."""

    proxy_target_attr = "device"


class VirtualMachinePrimaryIPProxyTestCase(Mixins.PrimaryIPProxyMixin, TestCase):
    """Virtual machine proxy should mirror native primary IP behavior."""

    proxy_target_attr = "vm"


class InterfaceIPProxyTestCase(Mixins.IPAddressManagerMixin, TestCase):
    """Interface ip_addresses proxies should render UUID strings."""

    manager_source_attr = "interface"


class DeviceServiceIPProxyTestCase(Mixins.IPAddressManagerMixin, TestCase):
    """Device-attached service ip_addresses proxies should render UUID strings."""

    manager_source_attr = "service_device_attached"


class VMServiceIPProxyTestCase(Mixins.IPAddressManagerMixin, TestCase):
    """VM-attached service ip_addresses proxies should render UUID strings."""

    manager_source_attr = "service_vm_attached"
