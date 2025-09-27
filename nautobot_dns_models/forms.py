"""Forms for nautobot_dns_models."""

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import models as django_models
from nautobot.apps.forms import (
    DynamicModelMultipleChoiceField,
    DynamicModelChoiceField,
    NautobotBulkEditForm,
    NautobotModelForm,
    TagsBulkEditFormMixin,
)
from nautobot.core.forms import add_blank_choice
from nautobot.core.forms.widgets import StaticSelect2
from nautobot.dcim.form_mixins import LocatableModelFormMixin, LocatableModelFilterFormMixin
from nautobot.extras.forms import NautobotFilterForm
from nautobot.ipam.models import Prefix

from nautobot_dns_models import models


class DNSViewForm(NautobotModelForm):
    """DNSView creation/edit form."""

    prefixes = DynamicModelMultipleChoiceField(
        queryset=Prefix.objects.all(),
        required=False,
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSView
        fields = "__all__"


class DNSViewBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSView bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSView.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class DNSViewFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name and Description.",
    )
    name = forms.CharField(required=False, label="Name")
    model = models.DNSView
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
    ]


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


class DNSRuleFormDisabled(NautobotModelForm):
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
        queryset=models.DNSZone.objects.all().order_by("name"),
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


class DNSRuleForm(LocatableModelFormMixin, NautobotModelForm):
    """DNSRule creation/edit form with dynamic field display."""

    content_type = forms.ModelChoiceField(
        queryset=ContentType.objects.filter(
            django_models.Q(app_label="dcim", model="device")
            | django_models.Q(app_label="dcim", model="interface")
            | django_models.Q(app_label="virtualization", model="virtualmachine")
            | django_models.Q(app_label="virtualization", model="vminterface")
        ).order_by("app_label", "model"),
        widget=StaticSelect2(),
        help_text="Type of object this rule applies to (Device, Interface, VM, VM Interface)",
    )

    record_type = forms.ChoiceField(
        choices=add_blank_choice(models.RECORD_TYPE_CHOICES),
        widget=StaticSelect2(),
        help_text="Type of DNS record this rule creates",
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSRule
        fields = "__all__"

    class Media:
        """Media for dynamic form behavior."""

        js = ["nautobot_dns_models/js/dns_rule_form.js"]

    def __init__(self, *args, **kwargs):
        """Initialize form with dynamic field setup."""
        super().__init__(*args, **kwargs)

        # Add CSS classes for dynamic showing/hiding
        template_fields = [
            "value_template",
            "preference_template",
            "priority_template",
            "weight_template",
            "port_template",
        ]

        for field_name in template_fields:
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.update({"class": f"template-field {field_name.replace('_', '-')}"})

        # Add enhanced help text for record-type specific fields
        field_help_text = {
            "preference_template": "MX records only: Mail server preference value (lower = higher priority)",
            "priority_template": "SRV records only: Service priority value (lower = higher priority)",
            "weight_template": "SRV records only: Service weight for load balancing",
            "port_template": "SRV records only: Service port number",
        }

        for field_name, help_text in field_help_text.items():
            if field_name in self.fields:
                self.fields[field_name].help_text = help_text


class DNSRuleBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSRule bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSRule.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False)
    priority = forms.IntegerField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
        ]


class DNSRuleFilterForm(LocatableModelFilterFormMixin, NautobotFilterForm):
    """Filter form for DNSRule searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name and Description.",
    )
    name = forms.CharField(required=False, label="Name")
    enabled = forms.NullBooleanField(required=False, label="Enabled")
    content_type = forms.ModelChoiceField(
        queryset=ContentType.objects.all().order_by("app_label", "model"),
        required=False,
        label="Content Type",
        widget=StaticSelect2(),
    )

    record_type = forms.ChoiceField(
        choices=add_blank_choice(models.RECORD_TYPE_CHOICES),
        required=False,
        label="Record Type",
        widget=StaticSelect2(),
    )

    model = models.DNSRule

    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "content_type",
        "location",
        "record_type",
    ]
