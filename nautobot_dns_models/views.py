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
    AAAARecordModelSerializer,
    ARecordModelSerializer,
    CNAMERecordModelSerializer,
    DNSRuleRecordSerializer,
    DNSRuleSerializer,
    DNSZoneModelSerializer,
    MXRecordModelSerializer,
    NSRecordModelSerializer,
    PTRRecordModelSerializer,
    SRVRecordModelSerializer,
    TXTRecordModelSerializer,
)
from nautobot_dns_models.filters import (
    AAAARecordModelFilterSet,
    ARecordModelFilterSet,
    CNAMERecordModelFilterSet,
    DNSRuleFilterSet,
    DNSRuleRecordFilterSet,
    DNSZoneModelFilterSet,
    MXRecordModelFilterSet,
    NSRecordModelFilterSet,
    PTRRecordModelFilterSet,
    SRVRecordModelFilterSet,
    TXTRecordModelFilterSet,
)
from nautobot_dns_models.forms import (
    AAAARecordModelBulkEditForm,
    AAAARecordModelFilterForm,
    AAAARecordModelForm,
    ARecordModelBulkEditForm,
    ARecordModelFilterForm,
    ARecordModelForm,
    CNAMERecordModelBulkEditForm,
    CNAMERecordModelFilterForm,
    CNAMERecordModelForm,
    DNSRuleBulkEditForm,
    DNSRuleFilterForm,
    DNSRuleForm,
    DNSRuleRecordFilterForm,
    DNSZoneModelBulkEditForm,
    DNSZoneModelFilterForm,
    DNSZoneModelForm,
    MXRecordModelBulkEditForm,
    MXRecordModelFilterForm,
    MXRecordModelForm,
    NSRecordModelBulkEditForm,
    NSRecordModelFilterForm,
    NSRecordModelForm,
    PTRRecordModelBulkEditForm,
    PTRRecordModelFilterForm,
    PTRRecordModelForm,
    SRVRecordModelBulkEditForm,
    SRVRecordModelFilterForm,
    SRVRecordModelForm,
    TXTRecordModelBulkEditForm,
    TXTRecordModelFilterForm,
    TXTRecordModelForm,
)
from nautobot_dns_models.models import (
    AAAARecordModel,
    ARecordModel,
    CNAMERecordModel,
    DNSRule,
    DNSRuleRecord,
    DNSZoneModel,
    MXRecordModel,
    NSRecordModel,
    PTRRecordModel,
    SRVRecordModel,
    TXTRecordModel,
)
from nautobot_dns_models.tables import (
    AAAARecordModelTable,
    ARecordModelTable,
    CNAMERecordModelTable,
    DNSRuleComponentTable,
    DNSRuleRecordTable,
    DNSRuleTable,
    DNSZoneModelTable,
    MXRecordModelTable,
    NSRecordModelTable,
    PTRRecordModelTable,
    SRVRecordModelTable,
    TXTRecordModelTable,
)


class DNSZoneModelUIViewSet(views.NautobotUIViewSet):
    """DnsZoneModel UI ViewSet."""

    form_class = DNSZoneModelForm
    bulk_update_form_class = DNSZoneModelBulkEditForm
    filterset_class = DNSZoneModelFilterSet
    filterset_form_class = DNSZoneModelFilterForm
    serializer_class = DNSZoneModelSerializer
    lookup_field = "pk"
    queryset = DNSZoneModel.objects.all()
    table_class = DNSZoneModelTable

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
                table_class=NSRecordModelTable,
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
                    ARecordModel,
                    AAAARecordModel,
                    CNAMERecordModel,
                    MXRecordModel,
                    PTRRecordModel,
                    SRVRecordModel,
                    TXTRecordModel,
                ],
            ),
            ObjectsTablePanel(
                weight=100,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=ARecordModelTable,
                table_title="A Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=200,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=AAAARecordModelTable,
                table_title="AAAA Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=300,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=CNAMERecordModelTable,
                table_title="CName Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=400,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=MXRecordModelTable,
                table_title="MX Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=500,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=PTRRecordModelTable,
                table_title="PTR Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=600,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=SRVRecordModelTable,
                table_title="SRV Records",
                exclude_columns=["zone"],
                max_display_count=5,
            ),
            ObjectsTablePanel(
                weight=700,
                section=SectionChoices.RIGHT_HALF,
                table_filter="zone",
                table_class=TXTRecordModelTable,
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
                required_permissions=["nautobot_dns_models.change_dnszonemodel"],
                children=(
                    Button(
                        weight=100,
                        link_name="plugins:nautobot_dns_models:zone_a_records_add",
                        label="A Record",
                        required_permissions=["nautobot_dns_models.add_arecordmodel"],
                    ),
                    Button(
                        weight=200,
                        link_name="plugins:nautobot_dns_models:zone_aaaa_records_add",
                        label="AAAA Record",
                        required_permissions=["nautobot_dns_models.add_aaaarecordmodel"],
                    ),
                    Button(
                        weight=300,
                        link_name="plugins:nautobot_dns_models:zone_cname_records_add",
                        label="CNAME Record",
                        required_permissions=["nautobot_dns_models.add_cnamerecordmodel"],
                    ),
                    Button(
                        weight=400,
                        link_name="plugins:nautobot_dns_models:zone_mx_records_add",
                        label="MX Record",
                        required_permissions=["nautobot_dns_models.add_mxrecordmodel"],
                    ),
                    Button(
                        weight=500,
                        link_name="plugins:nautobot_dns_models:zone_ns_records_add",
                        label="NS Record",
                        required_permissions=["nautobot_dns_models.add_nsrecordmodel"],
                    ),
                    Button(
                        weight=600,
                        link_name="plugins:nautobot_dns_models:zone_ptr_records_add",
                        label="PTR Record",
                        required_permissions=["nautobot_dns_models.add_ptrrecordmodel"],
                    ),
                    Button(
                        weight=700,
                        link_name="plugins:nautobot_dns_models:zone_srv_records_add",
                        label="SRV Record",
                        required_permissions=["nautobot_dns_models.add_srvrecordmodel"],
                    ),
                    Button(
                        weight=800,
                        link_name="plugins:nautobot_dns_models:zone_txt_records_add",
                        label="TXT Record",
                        required_permissions=["nautobot_dns_models.add_txtrecordmodel"],
                    ),
                ),
            ),
        ],
    )


class NSRecordModelUIViewSet(views.NautobotUIViewSet):
    """NSRecordModel UI ViewSet."""

    form_class = NSRecordModelForm
    bulk_update_form_class = NSRecordModelBulkEditForm
    filterset_class = NSRecordModelFilterSet
    filterset_form_class = NSRecordModelFilterForm
    serializer_class = NSRecordModelSerializer
    lookup_field = "pk"
    queryset = NSRecordModel.objects.all()
    table_class = NSRecordModelTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ],
    )


class ARecordModelUIViewSet(views.NautobotUIViewSet):
    """ARecordModel UI ViewSet."""

    form_class = ARecordModelForm
    bulk_update_form_class = ARecordModelBulkEditForm
    filterset_class = ARecordModelFilterSet
    filterset_form_class = ARecordModelFilterForm
    serializer_class = ARecordModelSerializer
    lookup_field = "pk"
    queryset = ARecordModel.objects.all()
    table_class = ARecordModelTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class AAAARecordModelUIViewSet(views.NautobotUIViewSet):
    """AAAARecordModel UI ViewSet."""

    form_class = AAAARecordModelForm
    bulk_update_form_class = AAAARecordModelBulkEditForm
    filterset_class = AAAARecordModelFilterSet
    filterset_form_class = AAAARecordModelFilterForm
    serializer_class = AAAARecordModelSerializer
    lookup_field = "pk"
    queryset = AAAARecordModel.objects.all()
    table_class = AAAARecordModelTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class CNAMERecordModelUIViewSet(views.NautobotUIViewSet):
    """CNAMERecordModel UI ViewSet."""

    form_class = CNAMERecordModelForm
    bulk_update_form_class = CNAMERecordModelBulkEditForm
    filterset_class = CNAMERecordModelFilterSet
    filterset_form_class = CNAMERecordModelFilterForm
    serializer_class = CNAMERecordModelSerializer
    lookup_field = "pk"
    queryset = CNAMERecordModel.objects.all()
    table_class = CNAMERecordModelTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class MXRecordModelUIViewSet(views.NautobotUIViewSet):
    """MXRecordModel UI ViewSet."""

    form_class = MXRecordModelForm
    bulk_update_form_class = MXRecordModelBulkEditForm
    filterset_class = MXRecordModelFilterSet
    filterset_form_class = MXRecordModelFilterForm
    serializer_class = MXRecordModelSerializer
    lookup_field = "pk"
    queryset = MXRecordModel.objects.all()
    table_class = MXRecordModelTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class TXTRecordModelUIViewSet(views.NautobotUIViewSet):
    """TXTRecordModel UI ViewSet."""

    form_class = TXTRecordModelForm
    bulk_update_form_class = TXTRecordModelBulkEditForm
    filterset_class = TXTRecordModelFilterSet
    filterset_form_class = TXTRecordModelFilterForm
    serializer_class = TXTRecordModelSerializer
    lookup_field = "pk"
    queryset = TXTRecordModel.objects.all()
    table_class = TXTRecordModelTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class PTRRecordModelUIViewSet(views.NautobotUIViewSet):
    """PTRRecordModel UI ViewSet."""

    form_class = PTRRecordModelForm
    bulk_update_form_class = PTRRecordModelBulkEditForm
    filterset_class = PTRRecordModelFilterSet
    filterset_form_class = PTRRecordModelFilterForm
    serializer_class = PTRRecordModelSerializer
    lookup_field = "pk"
    queryset = PTRRecordModel.objects.all()
    table_class = PTRRecordModelTable
    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            )
        ]
    )


class SRVRecordModelUIViewSet(views.NautobotUIViewSet):
    """SRVRecordModel UI ViewSet."""

    form_class = SRVRecordModelForm
    bulk_update_form_class = SRVRecordModelBulkEditForm
    filterset_class = SRVRecordModelFilterSet
    filterset_form_class = SRVRecordModelFilterForm
    serializer_class = SRVRecordModelSerializer
    lookup_field = "pk"
    queryset = SRVRecordModel.objects.all()
    table_class = SRVRecordModelTable
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
