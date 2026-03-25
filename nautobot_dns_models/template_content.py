"""Extensions of baseline Nautobot views."""

from urllib.parse import urlencode

from constance import config as constance_config
from django.urls import reverse
from nautobot.apps.ui import Button, ButtonColorChoices, ObjectsTablePanel, SectionChoices, TemplateExtension
from nautobot.core.views.utils import get_obj_from_context
from netutils.ip import ipaddress_address

from nautobot_dns_models.constants.supported_models import (
    SUPPORTED_PARENT_CHILD_MODEL_RELATIONS,
    SUPPORTED_SOURCE_MODELS,
)
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
    def _get_parent_object_name(obj):
        """Return parent object display name for child-source models, if available."""
        parent_device = getattr(obj, "device", None)
        if parent_device is not None:
            return str(parent_device)

        parent_vm = getattr(obj, "virtual_machine", None)
        if parent_vm is not None:
            return str(parent_vm)

        return None

    def get_link(self, context):
        """Build run URL for reconciliation job with single-object inputs pre-populated."""
        obj = get_obj_from_context(context)
        query_params = {
            "object_model": obj._meta.label_lower,
            "object_id": str(obj.pk),
            "object_name": str(obj),
            "object_url": obj.get_absolute_url(),
        }
        parent_object_name = self._get_parent_object_name(obj)
        if parent_object_name:
            query_params["parent_object_name"] = parent_object_name
        if obj.__class__ in SUPPORTED_PARENT_CHILD_MODEL_RELATIONS:
            query_params["include_children"] = "true"
        query = urlencode(query_params)
        return f"{reverse('extras:job_run_by_class_path', kwargs={'class_path': 'nautobot_dns_models.jobs.ReconcileDNSObjectJob'})}?{query}"

    def should_render(self, context):
        """Render button only when user can run jobs and at least one rule is in scope."""
        if not super().should_render(context):
            return False

        obj = get_obj_from_context(context)
        rule_engine = DNSRuleEngine()
        if obj.__class__ not in SUPPORTED_SOURCE_MODELS:
            return False

        try:
            if rule_engine.get_applicable_rules(obj):
                return True

            relation = SUPPORTED_PARENT_CHILD_MODEL_RELATIONS.get(obj.__class__)
            if relation is None:
                return False

            _child_model_class, related_manager_name = relation
            child_manager = getattr(obj, related_manager_name, None)
            if child_manager is None:
                return False

            for child_obj in child_manager.all():
                if rule_engine.get_applicable_rules(child_obj):
                    return True

            return False
        except Exception:  # pylint: disable=broad-exception-caught
            return False


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


class DeviceReconcileDNSAction(_BaseReconcileDNSAction):
    """Device detail-page reconcile DNS action."""

    model = "dcim.device"


class InterfaceReconcileDNSAction(_BaseReconcileDNSAction):
    """Interface detail-page reconcile DNS action."""

    model = "dcim.interface"


class ServiceReconcileDNSAction(_BaseReconcileDNSAction):
    """Service detail-page reconcile DNS action."""

    model = "ipam.service"


class VirtualMachineReconcileDNSAction(_BaseReconcileDNSAction):
    """VirtualMachine detail-page reconcile DNS action."""

    model = "virtualization.virtualmachine"


class VMInterfaceReconcileDNSAction(_BaseReconcileDNSAction):
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
