"""DNS Plugin Views."""

from django.core.exceptions import ValidationError
from django.db import models
from nautobot.apps import views
from nautobot.apps.ui import (
    ObjectDetailContent,
    ObjectFieldsPanel,
    ObjectsTablePanel,
    SectionChoices,
    StatsPanel,
    ButtonColorChoices,
    DropdownButton,
    Button,
)

from nautobot_dns_models.api.serializers import (
    AAAARecordSerializer,
    ARecordSerializer,
    CNAMERecordSerializer,
    DNSRuleRecordSerializer,
    DNSRuleSerializer,
    DNSZoneSerializer,
    MXRecordSerializer,
    NSRecordSerializer,
    PTRRecordSerializer,
    SRVRecordSerializer,
    TXTRecordSerializer,
)
from nautobot_dns_models.filters import (
    AAAARecordFilterSet,
    ARecordFilterSet,
    CNAMERecordFilterSet,
    DNSRuleFilterSet,
    DNSRuleRecordFilterSet,
    DNSZoneFilterSet,
    MXRecordFilterSet,
    NSRecordFilterSet,
    PTRRecordFilterSet,
    SRVRecordFilterSet,
    TXTRecordFilterSet,
)
from nautobot_dns_models.forms import (
    AAAARecordBulkEditForm,
    AAAARecordFilterForm,
    AAAARecordForm,
    ARecordBulkEditForm,
    ARecordFilterForm,
    ARecordForm,
    CNAMERecordBulkEditForm,
    CNAMERecordFilterForm,
    CNAMERecordForm,
    DNSRuleBulkEditForm,
    DNSRuleFilterForm,
    DNSRuleForm,
    DNSRuleRecordFilterForm,
    DNSZoneBulkEditForm,
    DNSZoneFilterForm,
    DNSZoneForm,
    MXRecordBulkEditForm,
    MXRecordFilterForm,
    MXRecordForm,
    NSRecordBulkEditForm,
    NSRecordFilterForm,
    NSRecordForm,
    PTRRecordBulkEditForm,
    PTRRecordFilterForm,
    PTRRecordForm,
    SRVRecordBulkEditForm,
    SRVRecordFilterForm,
    SRVRecordForm,
    TXTRecordBulkEditForm,
    TXTRecordFilterForm,
    TXTRecordForm,
)
from nautobot_dns_models.models import (
    AAAARecord,
    ARecord,
    CNAMERecord,
    DNSRule,
    DNSRuleRecord,
    DNSZone,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
)
from nautobot_dns_models.tables import (
    AAAARecordTable,
    ARecordTable,
    CNAMERecordTable,
    DNSRuleComponentTable,
    DNSRuleRecordTable,
    DNSRuleTable,
    DNSZoneTable,
    MXRecordTable,
    NSRecordTable,
    PTRRecordTable,
    SRVRecordTable,
    TXTRecordTable,
)


class DNSZoneUIViewSet(views.NautobotUIViewSet):
    """DNSZone UI ViewSet."""

    form_class = DNSZoneForm
    bulk_update_form_class = DNSZoneBulkEditForm
    filterset_class = DNSZoneFilterSet
    filterset_form_class = DNSZoneFilterForm
    serializer_class = DNSZoneSerializer
    lookup_field = "pk"
    queryset = DNSZone.objects.all()
    table_class = DNSZoneTable

    object_detail_content = ObjectDetailContent(
        panels=[
            # Left pane
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            ),
            ObjectsTablePanel(
                weight=200,
                section=SectionChoices.LEFT_HALF,
                table_filter="zone",
                table_class=NSRecordTable,
                table_title="NS Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            # Right pane
            StatsPanel(
                weight=10,
                section=SectionChoices.RIGHT_HALF,
                label="Records Statistics",
                filter_name="zone",
                related_models=[
                    ARecord,
                    AAAARecord,
                    CNAMERecord,
                    MXRecord,
                    PTRRecord,
                    SRVRecord,
                    TXTRecord,
                ],
            ),
            ObjectsTablePanel(
                weight=100,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=ARecordTable,
                table_title="A Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=200,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=AAAARecordTable,
                table_title="AAAA Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=300,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=CNAMERecordTable,
                table_title="CNAME Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=400,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=MXRecordTable,
                table_title="MX Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=500,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=PTRRecordTable,
                table_title="PTR Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=600,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=SRVRecordTable,
                table_title="SRV Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=700,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=TXTRecordTable,
                table_title="TXT Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
        ],
        extra_buttons=[
            DropdownButton(
                weight=100,
                color=ButtonColorChoices.BLUE,
                label="Add Records",
                icon="mdi-plus-thick",
                required_permissions=["nautobot_dns_models.change_dnszone"],
                children=(
                    Button(
                        weight=100,
                        link_name="plugins:nautobot_dns_models:zone_a_records_add",
                        label="A Record",
                        required_permissions=["nautobot_dns_models.add_arecord"],
                    ),
                    Button(
                        weight=200,
                        link_name="plugins:nautobot_dns_models:zone_aaaa_records_add",
                        label="AAAA Record",
                        required_permissions=["nautobot_dns_models.add_aaaarecord"],
                    ),
                    Button(
                        weight=300,
                        link_name="plugins:nautobot_dns_models:zone_cname_records_add",
                        label="CNAME Record",
                        required_permissions=["nautobot_dns_models.add_cnamerecord"],
                    ),
                    Button(
                        weight=400,
                        link_name="plugins:nautobot_dns_models:zone_mx_records_add",
                        label="MX Record",
                        required_permissions=["nautobot_dns_models.add_mxrecord"],
                    ),
                    Button(
                        weight=500,
                        link_name="plugins:nautobot_dns_models:zone_ns_records_add",
                        label="NS Record",
                        required_permissions=["nautobot_dns_models.add_nsrecord"],
                    ),
                    Button(
                        weight=600,
                        link_name="plugins:nautobot_dns_models:zone_ptr_records_add",
                        label="PTR Record",
                        required_permissions=["nautobot_dns_models.add_ptrrecord"],
                    ),
                    Button(
                        weight=700,
                        link_name="plugins:nautobot_dns_models:zone_srv_records_add",
                        label="SRV Record",
                        required_permissions=["nautobot_dns_models.add_srvrecord"],
                    ),
                    Button(
                        weight=800,
                        link_name="plugins:nautobot_dns_models:zone_txt_records_add",
                        label="TXT Record",
                        required_permissions=["nautobot_dns_models.add_txtrecord"],
                    ),
                ),
            ),
        ],
    )


class NSRecordUIViewSet(views.NautobotUIViewSet):
    """NSRecord UI ViewSet."""

    form_class = NSRecordForm
    bulk_update_form_class = NSRecordBulkEditForm
    filterset_class = NSRecordFilterSet
    filterset_form_class = NSRecordFilterForm
    serializer_class = NSRecordSerializer
    lookup_field = "pk"
    queryset = NSRecord.objects.all()
    table_class = NSRecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ],
    )


class ARecordUIViewSet(views.NautobotUIViewSet):
    """ARecord UI ViewSet."""

    form_class = ARecordForm
    bulk_update_form_class = ARecordBulkEditForm
    filterset_class = ARecordFilterSet
    filterset_form_class = ARecordFilterForm
    serializer_class = ARecordSerializer
    lookup_field = "pk"
    queryset = ARecord.objects.all()
    table_class = ARecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class AAAARecordUIViewSet(views.NautobotUIViewSet):
    """AAAARecord UI ViewSet."""

    form_class = AAAARecordForm
    bulk_update_form_class = AAAARecordBulkEditForm
    filterset_class = AAAARecordFilterSet
    filterset_form_class = AAAARecordFilterForm
    serializer_class = AAAARecordSerializer
    lookup_field = "pk"
    queryset = AAAARecord.objects.all()
    table_class = AAAARecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class CNAMERecordUIViewSet(views.NautobotUIViewSet):
    """CNAMERecord UI ViewSet."""

    form_class = CNAMERecordForm
    bulk_update_form_class = CNAMERecordBulkEditForm
    filterset_class = CNAMERecordFilterSet
    filterset_form_class = CNAMERecordFilterForm
    serializer_class = CNAMERecordSerializer
    lookup_field = "pk"
    queryset = CNAMERecord.objects.all()
    table_class = CNAMERecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class MXRecordUIViewSet(views.NautobotUIViewSet):
    """MXRecord UI ViewSet."""

    form_class = MXRecordForm
    bulk_update_form_class = MXRecordBulkEditForm
    filterset_class = MXRecordFilterSet
    filterset_form_class = MXRecordFilterForm
    serializer_class = MXRecordSerializer
    lookup_field = "pk"
    queryset = MXRecord.objects.all()
    table_class = MXRecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class TXTRecordUIViewSet(views.NautobotUIViewSet):
    """TXTRecord UI ViewSet."""

    form_class = TXTRecordForm
    bulk_update_form_class = TXTRecordBulkEditForm
    filterset_class = TXTRecordFilterSet
    filterset_form_class = TXTRecordFilterForm
    serializer_class = TXTRecordSerializer
    lookup_field = "pk"
    queryset = TXTRecord.objects.all()
    table_class = TXTRecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class PTRRecordUIViewSet(views.NautobotUIViewSet):
    """PTRRecord UI ViewSet."""

    form_class = PTRRecordForm
    bulk_update_form_class = PTRRecordBulkEditForm
    filterset_class = PTRRecordFilterSet
    filterset_form_class = PTRRecordFilterForm
    serializer_class = PTRRecordSerializer
    lookup_field = "pk"
    queryset = PTRRecord.objects.all()
    table_class = PTRRecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class SRVRecordUIViewSet(views.NautobotUIViewSet):
    """SRVRecord UI ViewSet."""

    form_class = SRVRecordForm
    bulk_update_form_class = SRVRecordBulkEditForm
    filterset_class = SRVRecordFilterSet
    filterset_form_class = SRVRecordFilterForm
    serializer_class = SRVRecordSerializer
    lookup_field = "pk"
    queryset = SRVRecord.objects.all()
    table_class = SRVRecordTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


# =============================================================================
# GUI Rule Builder ViewSets
# =============================================================================


class DNSRuleUIViewSet(views.NautobotUIViewSet):
    """DNSRule UI ViewSet."""

    queryset = DNSRule.objects.all()
    lookup_field = "pk"
    table_class = DNSRuleTable
    filterset_class = DNSRuleFilterSet
    filterset_form_class = DNSRuleFilterForm
    form_class = DNSRuleForm
    bulk_update_form_class = DNSRuleBulkEditForm
    serializer_class = DNSRuleSerializer

    # UI Component Framework detail page configuration
    object_detail_content = ObjectDetailContent(
        panels=[
            # Left side - Basic Rule Information
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                label="DNS Rule Information",
                fields=[
                    "name",
                    "status",
                    "enabled",
                    "content_type",
                    "record_type",
                    "description",
                ],
                # Use default field rendering - no custom transforms
            ),

            # Left side - Zone Configuration (all fields for now)
            ObjectFieldsPanel(
                weight=200,
                section=SectionChoices.LEFT_HALF,
                label="Zone Configuration",
                fields=[
                    "zone_source",
                    "zone_fixed",
                    "zone_field_path",
                    "zone_custom_field",
                ],
            ),

            # Left side - Rule Components Table (positioned above tags)
            ObjectsTablePanel(
                weight=250,  # Lower weight to appear above tags
                section=SectionChoices.LEFT_HALF,
                table_class=DNSRuleComponentTable,
                table_title="DNS Rule Components",
                table_attribute="components",
                related_field_name="rule",  # DNSRuleComponent.rule field points to DNSRule
            ),
        ]
    )

    def get_extra_context(self, request, instance):
        """Add component formset to template context - following Nautobot pattern."""
        context = super().get_extra_context(request, instance)

        # Components table is handled automatically by UI Component Framework via table_attribute

        if self.action in ("create", "update"):
            # Only create formset if we have a real model instance
            if not hasattr(instance, 'pk') or not isinstance(instance, models.Model):
                # instance is likely a redirect response or not a model, skip formset creation
                print(f"DEBUG: Skipping formset creation, instance type: {type(instance)}")
                return context

            # Initialize formset following Nautobot pattern
            formset_kwargs = {"instance": instance if instance.pk else None}
            if request.POST:
                formset_kwargs["data"] = request.POST
                formset_kwargs["files"] = request.FILES

            # Import transforms first to ensure they're registered before formset creation
            from nautobot_dns_models import transforms  # noqa: F401
            from nautobot_dns_models.forms import DNSRuleComponentFormSet

            # Follow exact Nautobot pattern from CustomFieldUIViewSet
            if request.POST:
                context["component_formset"] = DNSRuleComponentFormSet(data=request.POST, instance=instance, prefix="components")
            else:
                context["component_formset"] = DNSRuleComponentFormSet(instance=instance, prefix="components")

            # Force update transform choices on all forms including the empty form
            component_formset = context["component_formset"]
            from nautobot_dns_models.models import DNSRuleComponent
            from nautobot.core.forms import add_blank_choice

            transform_choices = add_blank_choice(DNSRuleComponent.get_transform_choices())

            # Update choices on all forms including the empty form
            for form in component_formset.forms:
                if 'transform_function' in form.fields:
                    form.fields['transform_function'].choices = transform_choices
                    # Also update the widget's choices if it has them
                    if hasattr(form.fields['transform_function'].widget, 'choices'):
                        form.fields['transform_function'].widget.choices = transform_choices

            # Also update empty form
            if 'transform_function' in component_formset.empty_form.fields:
                component_formset.empty_form.fields['transform_function'].choices = transform_choices
                if hasattr(component_formset.empty_form.fields['transform_function'].widget, 'choices'):
                    component_formset.empty_form.fields['transform_function'].widget.choices = transform_choices

        return context

    def form_save(self, form, **kwargs):
        """Handle formset saving after main form save - following exact Nautobot pattern."""
        # Save the main object first
        obj = super().form_save(form, **kwargs)

        # Process the formset for components (exact pattern from CustomFieldUIViewSet)
        ctx = self.get_extra_context(self.request, obj)
        component_formset = ctx.get("component_formset")

        if component_formset:
            if component_formset.is_valid():
                component_formset.save()
            else:
                raise ValidationError(component_formset.errors)

        return obj

    def get_template_names(self):
        """Use custom template for create/edit forms."""
        if self.action in ['create', 'update', 'edit', 'add']:
            return ["nautobot_dns_models/dnsrule_create.html"]
        return super().get_template_names()


class DNSRuleRecordUIViewSet(views.NautobotUIViewSet):
    """DNSRuleRecord UI ViewSet (read-only tracking records)."""

    queryset = DNSRuleRecord.objects.all()
    lookup_field = "pk"
    table_class = DNSRuleRecordTable
    filterset_class = DNSRuleRecordFilterSet
    filterset_form_class = DNSRuleRecordFilterForm
    serializer_class = DNSRuleRecordSerializer

    # Note: No create/edit forms - these are read-only tracking records
