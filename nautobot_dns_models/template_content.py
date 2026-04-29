"""Extensions of baseline Nautobot views."""

from urllib.parse import urlencode

from constance import config as constance_config
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from nautobot.apps.ui import Button, ButtonColorChoices, ObjectsTablePanel, SectionChoices, TemplateExtension
from nautobot.core.views.utils import get_obj_from_context
from nautobot.dcim.models import Device
from netutils.ip import ipaddress_address

from nautobot_dns_models.constants import SUPPORTED_SOURCE_MODELS
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    DNSZone,
    PTRRecord,
)
from nautobot_dns_models.rules.engine import DNSRuleEngine
from nautobot_dns_models.tables import (
    AAAARecordTable,
    ARecordTable,
    PTRRecordTable,
)


class ReconcileDNSObjectButton(Button):
    """Object-detail button that links to single-object DNS reconciliation."""

    @staticmethod
    def _get_parent_object(obj):
        """Return parent object for child-source models, if available."""
        parent_device = getattr(obj, "device", None)
        if parent_device is not None:
            return parent_device

        parent_vm = getattr(obj, "virtual_machine", None)
        if parent_vm is not None:
            return parent_vm

        return None

    def get_link(self, context):
        """Build run URL for reconciliation job with single-object inputs pre-populated."""
        obj = get_obj_from_context(context)
        has_populated_device_bays = False
        if obj.__class__ is Device:
            has_populated_device_bays = obj.device_bays.filter(installed_device__isnull=False).exists()

        query_params = {
            "object_model": str(ContentType.objects.get_for_model(obj).pk),
            "object_model_label": obj._meta.label_lower,
            "object_id": str(obj.pk),
            "object_name": str(obj),
            "object_url": obj.get_absolute_url(),
            "object_has_populated_device_bays": str(has_populated_device_bays).lower(),
            "object_has_interfaces": str(hasattr(obj, "interfaces")).lower(),
        }

        parent_object = self._get_parent_object(obj)
        if parent_object is not None:
            query_params["parent_object_type"] = parent_object.__class__.__name__
            query_params["parent_object_name"] = str(parent_object)
            query_params["parent_object_url"] = parent_object.get_absolute_url()

        if hasattr(obj, "interfaces"):
            query_params["include_interfaces"] = "true"

        query = urlencode(query_params)

        return f"{reverse('extras:job_run_by_class_path', kwargs={'class_path': 'nautobot_dns_models.jobs.ReconcileDNSObjectJob'})}?{query}"

    def should_render(self, context):
        """Render button only when user can run jobs and at least one rule is in scope."""
        if not super().should_render(context):
            return False

        obj = get_obj_from_context(context)
        if obj.__class__ not in SUPPORTED_SOURCE_MODELS:
            return False

        rule_engine = DNSRuleEngine()

        # If there are any rules that apply to the object, return True.
        if rule_engine.get_applicable_rules(obj):
            return True

        # For sibling interfaces under one parent object, applicable-rule resolution is scope-based
        # (content type + location + tenant), so one sampled interface is sufficient for this UI check.
        child_object_manager = getattr(obj, "interfaces", None)
        if child_object_manager is None:
            return False

        child_obj = child_object_manager.first()
        if child_obj is None:
            return False

        return bool(rule_engine.get_applicable_rules(child_obj))


class _BaseReconcileDNSAction(TemplateExtension):  # pylint: disable=abstract-method
    """Shared per-model reconcile button extension."""

    object_detail_buttons = (
        ReconcileDNSObjectButton(
            weight=950,
            label="Reconcile DNS",
            color=ButtonColorChoices.BLUE,
            icon="mdi-dns",
            required_permissions=["extras.run_job"],
        ),
    )


class DeviceReconcileDNSAction(_BaseReconcileDNSAction):  # pylint: disable=abstract-method
    """Device detail-page reconcile DNS action."""

    model = "dcim.device"


class InterfaceReconcileDNSAction(_BaseReconcileDNSAction):  # pylint: disable=abstract-method
    """Interface detail-page reconcile DNS action."""

    model = "dcim.interface"


class ServiceReconcileDNSAction(_BaseReconcileDNSAction):  # pylint: disable=abstract-method
    """Service detail-page reconcile DNS action."""

    model = "ipam.service"


class VirtualMachineReconcileDNSAction(_BaseReconcileDNSAction):  # pylint: disable=abstract-method
    """VirtualMachine detail-page reconcile DNS action."""

    model = "virtualization.virtualmachine"


class VMInterfaceReconcileDNSAction(_BaseReconcileDNSAction):  # pylint: disable=abstract-method
    """VMInterface detail-page reconcile DNS action."""

    model = "virtualization.vminterface"


class ForwardDNSRecordsTablePanel(ObjectsTablePanel):
    """Add A/AAAA DNS Records to the right side of the IP Address page."""

    def should_render(self, context):
        """Check if the table should be rendered."""
        show_panel = constance_config.nautobot_dns_models__SHOW_FORWARD_PANEL
        if show_panel == "never":
            return False

        if show_panel == "if_present":
            ip_address = get_obj_from_context(context)
            if ip_address.ip_version == 4:
                return ARecord.objects.filter(address=ip_address).exists()
            if ip_address.ip_version == 6:
                return AAAARecord.objects.filter(address=ip_address).exists()

        return True

    def get_extra_context(self, context):
        """Set the table class based on the IP version of the IP address."""
        # Get the IP address from the context.
        ip_address = get_obj_from_context(context)

        # Use ARecordTable for IPv4 and AAAARecordTable for IPv6.
        url = ""
        if ip_address.ip_version == 4:
            self.table_class = ARecordTable
            url = reverse("plugins:nautobot_dns_models:arecord_add")
        elif ip_address.ip_version == 6:
            self.table_class = AAAARecordTable
            url = reverse("plugins:nautobot_dns_models:aaaarecord_add")

        # Construct the URL query to auto-populate fields when adding a new record.
        autopop_fields = {"address": ip_address.id}
        try:
            name, zone = ip_address.dns_name.split(".", 1)
        except ValueError:
            name = zone = ""
        if DNSZone.objects.filter(name=zone).exists():
            autopop_fields["name"] = name
            autopop_fields["zone"] = DNSZone.objects.get(name=zone).id

        # Tweak returned ctx
        ctx = super().get_extra_context(context)
        return_url = reverse("ipam:ipaddress", kwargs={"pk": ip_address.pk})
        ctx["body_content_table_add_url"] = f"{url}?{urlencode(autopop_fields)}&return_url={return_url}"
        return ctx


class ReverseDNSRecordsTablePanel(ObjectsTablePanel):
    """Add PTR DNS Records to the right side of the IP Address page."""

    def should_render(self, context):
        """Check if the table should be rendered."""
        show_panel = constance_config.nautobot_dns_models__SHOW_REVERSE_PANEL
        if show_panel == "never":
            return False
        if show_panel == "if_present":
            ip_address = get_obj_from_context(context)
            ptrdname = ipaddress_address(ip_address.host, "reverse_pointer")
            return PTRRecord.objects.filter(ptrdname=ptrdname).exists()
        return True

    def get_extra_context(self, context):
        """Set the table class based on the IP version of the IP address."""
        # Calculate the ptrdname based on the IP address.
        ip_address = get_obj_from_context(context)
        ptrdname = ipaddress_address(ip_address.host, "reverse_pointer")

        # Construct the table with the filtered PTR records, apply permissions.
        queryset = PTRRecord.objects.filter(ptrdname=ptrdname)
        queryset = queryset.restrict(context.get("request").user, "view")
        ptrdtable = PTRRecordTable(queryset)

        # Inject the table into the context.
        context["ptrdtable"] = ptrdtable
        self.context_table_key = "ptrdtable"

        # Construct the URL query to auto-populate fields when adding a new record.
        autopop_fields = {
            "address": ip_address.id,
            "name": ip_address.dns_name,
            "ptrdname": ptrdname,
        }
        try:
            zone = ptrdname.split(".", 1)[1]
        except ValueError:
            zone = ""
        if DNSZone.objects.filter(name=zone).exists():
            autopop_fields["zone"] = DNSZone.objects.get(name=zone).id

        # Tweak returned ctx
        url = reverse("plugins:nautobot_dns_models:ptrrecord_add")
        return_url = reverse("ipam:ipaddress", kwargs={"pk": ip_address.pk})
        ctx = super().get_extra_context(context)
        ctx["body_content_table_add_url"] = f"{url}?{urlencode(autopop_fields)}&return_url={return_url}"
        return ctx


class IPAddressDNSRecords(TemplateExtension):  # pylint: disable=abstract-method
    """Add DNS Records to the right side of the IP Address page."""

    model = "ipam.ipaddress"

    object_detail_panels = [
        #
        # XXX: Are there prefetch/select_related optimizations to be done here?
        ForwardDNSRecordsTablePanel(
            weight=100,
            section=SectionChoices.RIGHT_HALF,
            table_class=ARecordTable,
            table_filter="address",
            include_columns=["name", "zone", "ttl", "actions", "source_object"],
        ),
        ReverseDNSRecordsTablePanel(
            weight=110,
            section=SectionChoices.RIGHT_HALF,
            table_class=PTRRecordTable,
            table_filter="ptrdname",
            include_columns=["name", "zone", "ttl", "actions"],
        ),
    ]


template_extensions = [
    IPAddressDNSRecords,
    DeviceReconcileDNSAction,
    InterfaceReconcileDNSAction,
    ServiceReconcileDNSAction,
    VirtualMachineReconcileDNSAction,
    VMInterfaceReconcileDNSAction,
]
