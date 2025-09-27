"""Forms for nautobot_dns_models."""

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import models as django_models
from django.forms import inlineformset_factory, BaseInlineFormSet
from nautobot.apps.forms import (
    NautobotBulkEditForm,
    NautobotModelForm,
    StaticSelect2,
    TagsBulkEditFormMixin,
)
from nautobot.core.forms import add_blank_choice
from nautobot.extras.forms import NautobotFilterForm

from nautobot_dns_models import models, transforms


class DNSZoneForm(NautobotModelForm):
    """DNSZone creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.DNSZone
        fields = "__all__"


class DNSZoneBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSZone bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSZone.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class DNSZoneFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.DNSZone
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
    ]


class NSRecordForm(NautobotModelForm):
    """NSRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.NSRecord
        fields = "__all__"


class NSRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """NSRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.NSRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class NSRecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    server = forms.CharField(required=False, label="Server")
    model = models.NSRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class ARecordForm(NautobotModelForm):
    """ARecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.ARecord
        fields = "__all__"


class ARecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """ARecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.ARecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class ARecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    zone = forms.CharField(required=False, label="Zone")
    model = models.ARecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class AAAARecordForm(NautobotModelForm):
    """AAAARecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.AAAARecord
        fields = "__all__"


class AAAARecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """AAAARecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.AAAARecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class AAAARecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.AAAARecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class CNAMERecordForm(NautobotModelForm):
    """CNAMERecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.CNAMERecord
        fields = "__all__"


class CNAMERecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """CNAMERecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.CNAMERecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class CNAMERecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.CNAMERecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class MXRecordForm(NautobotModelForm):
    """MXRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.MXRecord
        fields = "__all__"


class MXRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """MXRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.MXRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class MXRecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.MXRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "preference",
        "description",
    ]


class TXTRecordForm(NautobotModelForm):
    """TXTRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.TXTRecord
        fields = "__all__"


class TXTRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """TXTRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.TXTRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class TXTRecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.TXTRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class PTRRecordForm(NautobotModelForm):
    """PTRRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.PTRRecord
        fields = "__all__"


class PTRRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """PTRRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.PTRRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class PTRRecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.PTRRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "ttl",
        "comment",
        "description",
    ]


class SRVRecordForm(NautobotModelForm):
    """SRVRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.SRVRecord
        fields = "__all__"


class SRVRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """SRVRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.SRVRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class SRVRecordFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.SRVRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "priority",
        "weight",
        "port",
        "target",
    ]


# =============================================================================
# GUI Rule Builder Forms
# =============================================================================


class DNSRuleComponentForm(forms.ModelForm):
    """Form for individual DNS rule components."""
    
    class Meta:
        """Meta attributes."""
        
        model = models.DNSRuleComponent
        fields = ["target_field", "component_type", "value", "transform_function", "order"]
        widgets = {
            "target_field": StaticSelect2(),
            "component_type": StaticSelect2(),
            "value": forms.TextInput(attrs={
                "class": "form-control", 
                "placeholder": "Enter value based on component type"
            }),
            "transform_function": StaticSelect2(),
            "order": forms.HiddenInput(),
        }
    
    def __init__(self, *args, **kwargs):
        """Initialize component form with proper choices."""
        super().__init__(*args, **kwargs)
        
        # Make fields not required so we can handle empty forms ourselves
        self.fields["target_field"].required = False
        self.fields["component_type"].required = False
        
        # Set target field choices
        self.fields["target_field"].choices = add_blank_choice([
            ("name", "Name"),
            ("value", "Value"),
        ])
        
        # Set component type choices  
        self.fields["component_type"].choices = add_blank_choice([
            ("field_reference", "Field Reference"),
            ("literal", "Literal Value"),
        ])
        
        # Set transform function choices
        transform_choices = models.DNSRuleComponent.get_transform_choices()
        self.fields["transform_function"].choices = add_blank_choice(transform_choices)
    
    def clean(self):
        """Custom validation to handle completely empty forms."""
        cleaned_data = super().clean()
        
        # Check if this is a completely empty form
        target_field = cleaned_data.get('target_field')
        component_type = cleaned_data.get('component_type')
        value = cleaned_data.get('value')
        
        # If all main fields are empty, mark this form for deletion
        all_empty = (
            not target_field and 
            not component_type and 
            not value
        )
        
        if all_empty:
            # Mark this form instance for deletion by setting a flag
            self._empty_form = True
            # Clear any validation errors since we're deleting this form
            self._errors.clear()
        else:
            # For non-empty forms, validate that required fields are present
            if not target_field:
                raise forms.ValidationError({'target_field': 'This field is required.'})
            if not component_type:
                raise forms.ValidationError({'component_type': 'This field is required.'})
            if not value:
                raise forms.ValidationError({'value': 'Value is required for all components.'})
            
        return cleaned_data
    
    # has_changed() uses default behavior - don't override


class BaseDNSRuleComponentFormSet(BaseInlineFormSet):
    """Minimal custom formset that only handles save filtering."""
    
    def save(self, commit=True):
        """Override save to skip empty forms."""
        # Don't save forms marked as empty by the form's clean() method
        instances = []
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                # Skip forms marked as empty
                if hasattr(form, '_empty_form') and form._empty_form:
                    continue
                # Only save forms with actual data
                if form.cleaned_data.get('target_field') or form.cleaned_data.get('component_type') or form.cleaned_data.get('value'):
                    if form.has_changed():
                        instances.append(form.save(commit=commit))
        
        # Handle deletions
        self.save_m2m = getattr(self, 'save_m2m', lambda: None)
        return instances


# Create the inline formset for DNS rule components
DNSRuleComponentFormSet = inlineformset_factory(
    models.DNSRule,
    models.DNSRuleComponent,
    form=DNSRuleComponentForm,
    formset=BaseDNSRuleComponentFormSet,
    fields=["target_field", "component_type", "value", "transform_function", "order"],
    extra=1,  # Start with one empty form
    can_delete=True,
    can_order=False,  # We'll handle ordering with JavaScript
)


class DNSRuleForm(NautobotModelForm):
    """DNSRule creation/edit form."""

    # Class attribute field definitions (proper Django pattern)
    content_type = forms.ModelChoiceField(
        queryset=ContentType.objects.filter(
            django_models.Q(app_label="dcim", model="device")
            | django_models.Q(app_label="dcim", model="interface")
            | django_models.Q(app_label="virtualization", model="virtualmachine")
            | django_models.Q(app_label="virtualization", model="vminterface")
        ).order_by("app_label", "model"),
        widget=StaticSelect2(),
        label="Applies To",
        help_text="Type of object this rule applies to (Device, Interface, VM, VM Interface)",
    )

    record_type = forms.ModelChoiceField(
        queryset=ContentType.objects.filter(
            app_label="nautobot_dns_models", 
            model__endswith="recordmodel"
        ).order_by("model"),
        widget=StaticSelect2(),
        label="Creates", 
        help_text="Type of DNS record this rule creates",
        empty_label="---------",
    )

    zone_fixed = forms.ModelChoiceField(
        queryset=models.DNSZoneModel.objects.all().order_by("name"),
        required=False,
        widget=StaticSelect2(),
        label="Fixed Zone",
        help_text="Fixed DNS zone (when zone source is 'Fixed Zone')",
    )

    zone_source = forms.ChoiceField(
        choices=add_blank_choice(
            [
                ("fixed", "Fixed Zone"),
                ("field_reference", "Model Field Path"),
                ("custom_field", "Custom Field"),
            ]
        ),
        widget=StaticSelect2(),
        label="Zone Source",
        help_text="How to determine the DNS zone for generated records",
    )

    zone_field_path = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "device.location.zone"}),
        label="Zone Field Path",
        help_text="Model field path like 'device.location.zone' (when zone source is 'Model Field Path')",
    )

    zone_custom_field = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "dns_zone"}),
        label="Zone Custom Field",
        help_text="Custom field name like 'dns_zone' (when zone source is 'Custom Field')",
    )

    description = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Description",
        help_text="Optional description of what this rule does",
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSRule
        fields = "__all__"

    class Media:
        """Form media for JavaScript functionality."""
        
        js = ("nautobot_dns_models/js/dns_rule_form.js",)

    def __init__(self, *args, **kwargs):
        """Initialize form with record type choices using verbose names and logical ordering."""
        super().__init__(*args, **kwargs)

        # Set up custom ordering and display for record types
        content_types = ContentType.objects.filter(app_label="nautobot_dns_models", model__endswith="recordmodel")
        
        # Define preferred ordering for DNS records
        preferred_order = [
            "arecordmodel",  # A Record
            "aaaarecordmodel",  # AAAA Record
            "cnamerecordmodel",  # CNAME Record
            "mxrecordmodel",  # MX Record
            "nsrecordmodel",  # NS Record
            "ptrrecordmodel",  # PTR Record
            "srvrecordmodel",  # SRV Record
            "txtrecordmodel",  # TXT Record
        ]

        # Sort content types by preferred order
        content_types_list = list(content_types)
        content_types_list.sort(key=lambda ct: preferred_order.index(ct.model) if ct.model in preferred_order else 999)
        
        # Update the queryset to use our preferred ordering
        self.fields["record_type"].queryset = ContentType.objects.filter(
            id__in=[ct.id for ct in content_types_list]
        ).extra(
            select={'ordering': f"CASE {' '.join([f'WHEN id={ct.id} THEN {i}' for i, ct in enumerate(content_types_list)])} ELSE 999 END"}
        ).order_by('ordering')


class DNSRuleBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSRule bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSRule.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.BooleanField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class DNSRuleFilterForm(NautobotFilterForm):
    """Filter form for DNS rules."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name and Description.",
    )
    name = forms.CharField(required=False, label="Name")
    enabled = forms.BooleanField(required=False, label="Enabled")
    content_type = forms.ModelChoiceField(queryset=ContentType.objects.all(), required=False, label="Applies To")
    record_type = forms.ModelChoiceField(
        queryset=ContentType.objects.filter(app_label="nautobot_dns_models", model__endswith="recordmodel").exclude(
            model="dnsrecordmodel"
        ),
        required=False,
        label="Creates",
    )
    zone_source = forms.ChoiceField(
        choices=[("", "All")]
        + [
            ("fixed", "Fixed Zone"),
            ("field_reference", "Model Field Path"),
            ("custom_field", "Custom Field"),
        ],
        required=False,
        label="Zone Source",
    )

    model = models.DNSRule
    fields = [
        "q",
        "name",
        "enabled",
        "content_type",
        "record_type",
        "zone_source",
    ]


class DNSRuleRecordFilterForm(NautobotFilterForm):
    """Filter form for DNS rule records (tracking)."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Rule name.",
    )
    rule = forms.ModelChoiceField(queryset=models.DNSRule.objects.all(), required=False, label="Rule")

    model = models.DNSRuleRecord
    fields = [
        "q",
        "rule",
    ]
