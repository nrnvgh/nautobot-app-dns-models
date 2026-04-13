from django.contrib.contenttypes.models import ContentType
from nautobot.apps.choices import InterfaceTypeChoices
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix, Service
from nautobot.tenancy.models import Tenant, TenantGroup
from nautobot.virtualization.models import Cluster, ClusterType, VirtualMachine

from nautobot_dns_models.models import DNSZone
from nautobot_dns_models.rules.engine import DNSRuleEngine


#
# TODO: these mixins need to have setUpTestData pylint warnings quelled.
class BaseRuleEngineMixin:
    """Base test case with comprehensive setup data for all DNS rule engine tests."""

    @classmethod
    def setUpTestData(cls):  # pylint: disable=invalid-name
        """Set up comprehensive shared test data for all test cases."""
        # Create location infrastructure
        cls.location_type = LocationType.objects.create(name="Test Location Type")
        cls.location_type.content_types.add(ContentType.objects.get_for_model(Device))

        cls.location = Location.objects.create(
            name="Test Location",
            location_type=cls.location_type,
            status=Status.objects.get_for_model(Location).first(),
        )

        # Create tenant infrastructure
        cls.tenant_group = TenantGroup.objects.create(name="Test Tenant Group")
        cls.tenant = Tenant.objects.create(name="Test Tenant", tenant_group=cls.tenant_group)

        # Create device infrastructure
        cls.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        cls.device_type = DeviceType.objects.create(manufacturer=cls.manufacturer, model="Test Device Type")
        cls.device_role = Role.objects.create(name="Test Device Role")
        cls.device_role.content_types.add(ContentType.objects.get_for_model(Device))
        cls.interface_status = Status.objects.get_for_model(Interface).first()

        # Create shared device and interface for tests
        cls.device = Device.objects.create(
            name="test-device",
            device_type=cls.device_type,
            location=cls.location,
            role=cls.device_role,
            status=Status.objects.get_for_model(Device).first(),
        )

        cls.interface = Interface.objects.create(
            name="eth0",
            device=cls.device,
            type=InterfaceTypeChoices.TYPE_1GE_FIXED,
            status=cls.interface_status,
        )

        # Create namespace and prefix for IP addresses
        cls.namespace = Namespace.objects.create(name="Test Namespace")
        cls.prefix_status = Status.objects.get_for_model(Prefix).first()
        cls.prefix = Prefix.objects.create(
            network="192.168.1.0",
            prefix_length=24,
            namespace=cls.namespace,
            status=cls.prefix_status,
        )

        cls.ipv6_prefix = Prefix.objects.create(
            network="2001:db8::",
            prefix_length=64,
            namespace=cls.namespace,
            status=cls.prefix_status,
        )

        cls.ip_status = Status.objects.get_for_model(IPAddress).first()
        # Create 3 IPv4 addresses within the namespace and associate with parent prefix
        cls.ip_addresses = []
        for i in range(10, 13):
            ip_address = IPAddress.objects.create(
                address=f"192.168.1.{i}/24",
                status=cls.ip_status,
                namespace=cls.namespace,
                parent=cls.prefix,
            )
            cls.ip_addresses.append(ip_address)

        # Create 3 IPv6 addresses within the namespace and associate with parent prefix
        cls.ipv6_addresses = []
        for i in range(1, 4):
            ipv6_address = IPAddress.objects.create(
                address=f"2001:db8::{i}/64",
                status=cls.ip_status,
                namespace=cls.namespace,
                parent=cls.ipv6_prefix,
            )
            cls.ipv6_addresses.append(ipv6_address)

        # Create Service test data
        cls.service_device_attached = Service.objects.create(
            device=cls.device, name="web-service", protocol="TCP", ports=[80, 443], description="Web service on device"
        )

        # Create VM infrastructure for VM-attached services
        cls.cluster_type = ClusterType.objects.create(name="Test Cluster Type")
        cls.cluster = Cluster.objects.create(name="Test Cluster", cluster_type=cls.cluster_type, location=cls.location)
        cls.vm_status = Status.objects.get_for_model(VirtualMachine).first()
        cls.vm = VirtualMachine.objects.create(cluster=cls.cluster, name="test-vm", status=cls.vm_status)

        cls.service_vm_attached = Service.objects.create(
            virtual_machine=cls.vm, name="api-service", protocol="TCP", ports=[8080], description="API service on VM"
        )

        # Create DNS zone
        cls.dns_zone = DNSZone.objects.create(name="example.com")

        # Content types for validation tests
        cls.device_content_type = ContentType.objects.get_for_model(Device)
        cls.interface_content_type = ContentType.objects.get_for_model(Interface)
        cls.service_content_type = ContentType.objects.get_for_model(Service)

        # Additional status objects that some tests expect
        cls.device_status = Status.objects.get_for_model(Device).first()

        # Additional roles
        cls.interface_role = Role.objects.create(name="Test Interface Role")
        cls.interface_role.content_types.add(ContentType.objects.get_for_model(Interface))

    def setUp(self):  # pylint: disable=invalid-name
        """Set up test data."""
        self.engine = DNSRuleEngine()

    def _calc_desired_record_data(self, rule, obj):
        """Helper for invoking the engine private API in tests."""
        return list(self.engine._materializer.calculate_desired_record_data(rule, obj, phase="unknown"))

    def _render_template(self, template_str, context, field_name):
        """Wrapper around the engine's private _render_template helper."""
        return self.engine._materializer.render_template(template_str, context, field_name)

    def _get_object_location(self, obj):
        """Wrapper around engine object-location extraction."""
        return self.engine._resolver.get_object_location(obj)

    def _get_object_tenant(self, obj):
        """Wrapper around engine object-tenant extraction."""
        return self.engine._resolver.get_object_tenant(obj)
