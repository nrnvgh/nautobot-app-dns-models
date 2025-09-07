"""Forms for nautobot_dns_models."""

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import models as django_models
from django.forms import inlineformset_factory
from nautobot.apps.forms import (
    NautobotBulkEditForm,
    NautobotModelForm,
    StaticSelect2,
    TagsBulkEditFormMixin,
)
from nautobot.core.forms import add_blank_choice
from nautobot.extras.forms import NautobotFilterForm

from nautobot_dns_models import models

# Force import of transforms at module level to ensure they're registered
try:
    from nautobot_dns_models import transforms  # noqa: F401
except ImportError:
    pass  # Handle cases where transforms might not be available yet


class DNSZoneModelForm(NautobotModelForm):
    """DnsZoneModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.DNSZoneModel
        fields = "__all__"


class DNSZoneModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DnsZoneModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSZoneModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class DNSZoneModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.DNSZoneModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
    ]


class NSRecordModelForm(NautobotModelForm):
    """NSRecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.NSRecordModel
        fields = "__all__"


class NSRecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """NSRecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.NSRecordModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class NSRecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    server = forms.CharField(required=False, label="Server")
    model = models.NSRecordModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class ARecordModelForm(NautobotModelForm):
    """ARecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.ARecordModel
        fields = "__all__"


class ARecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """ARecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.ARecordModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class ARecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    zone = forms.CharField(required=False, label="Zone")
    model = models.ARecordModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class AAAARecordModelForm(NautobotModelForm):
    """AAAARecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.AAAARecordModel
        fields = "__all__"


class AAAARecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """AAAARecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.AAAARecordModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class AAAARecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.AAAARecordModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class CNAMERecordModelForm(NautobotModelForm):
    """CNAMERecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.CNAMERecordModel
        fields = "__all__"


class CNAMERecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """CNAMERecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(
        queryset=models.CNAMERecordModel.objects.all(), widget=forms.MultipleHiddenInput
    )
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class CNAMERecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.CNAMERecordModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class MXRecordModelForm(NautobotModelForm):
    """MXRecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.MXRecordModel
        fields = "__all__"


class MXRecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """MXRecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.MXRecordModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class MXRecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.MXRecordModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "preference",
        "description",
    ]


class TXTRecordModelForm(NautobotModelForm):
    """TXTRecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.TXTRecordModel
        fields = "__all__"


class TXTRecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """TXTRecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.TXTRecordModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class TXTRecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.TXTRecordModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class PTRRecordModelForm(NautobotModelForm):
    """PTRRecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.PTRRecordModel
        fields = "__all__"


class PTRRecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """PTRRecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.PTRRecordModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class PTRRecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.PTRRecordModel
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "ttl",
        "comment",
        "description",
    ]


class SRVRecordModelForm(NautobotModelForm):
    """SRVRecordModel creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.SRVRecordModel
        fields = "__all__"


class SRVRecordModelBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """SRVRecordModel bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.SRVRecordModel.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class SRVRecordModelFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.SRVRecordModel
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
        fields = ["target_field", "component_type", "field_path", "literal_value", "transform_function", "order"]
        widgets = {
            "target_field": StaticSelect2(),
            "component_type": StaticSelect2(),
            "field_path": forms.TextInput(attrs={
                "class": "form-control", 
                "placeholder": "device.name"
            }),
            "literal_value": forms.TextInput(attrs={
                "class": "form-control", 
                "placeholder": "static text"
            }),
            "transform_function": StaticSelect2(),
            "order": forms.NumberInput(attrs={"class": "form-control", "style": "display: none;"}),
        }
    
    def __init__(self, *args, **kwargs):
        """Initialize component form with proper choices."""
        super().__init__(*args, **kwargs)
        
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


# Create the inline formset for DNS rule components
DNSRuleComponentFormSet = inlineformset_factory(
    models.DNSRule,
    models.DNSRuleComponent,
    form=DNSRuleComponentForm,
    fields=["target_field", "component_type", "field_path", "literal_value", "transform_function", "order"],
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

    record_type = forms.ChoiceField(
        choices=[],  # Will be populated in __init__ with verbose names
        widget=StaticSelect2(),
        label="Creates",
        help_text="Type of DNS record this rule creates",
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

        # Generate record type choices with verbose names and proper DNS ordering
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

        # Generate choices with verbose names
        record_type_choices = []
        for ct in content_types_list:
            model_class = ct.model_class()
            if model_class:
                verbose_name = model_class._meta.verbose_name
                record_type_choices.append((ct.id, verbose_name))

        # Add blank choice at the top for better UX
        self.fields["record_type"].choices = add_blank_choice(record_type_choices)


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
