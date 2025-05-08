"""Forms for nautobot_dns_models."""

from django import forms
from nautobot.apps.forms import (
    NautobotBulkEditForm,
    NautobotModelForm,
    TagsBulkEditFormMixin,
)
from nautobot.extras.forms import NautobotFilterForm
from jinja2 import Environment, TemplateSyntaxError
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from nautobot_dns_models import models


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


class DNSRuleForm(NautobotModelForm):
    """DNS Rule creation/edit form."""

    class Meta:
        """Meta attributes."""
        model = models.DNSRule
        fields = [
            'name',
            'description',
            'enabled',
            'content_type',
            'priority',
            'record_type',
            'zone_template',
            'name_template',
            'value_template',
            'ttl',
            'mx_preference',
        ]
        widgets = {
            'zone_template': forms.Textarea(attrs={'rows': 3}),
            'name_template': forms.Textarea(attrs={'rows': 3}),
            'value_template': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Update content types to include ipam.ipaddresstointerface
        self.fields['content_type'].queryset = ContentType.objects.filter(
            Q(app_label='dcim', model__in=['device', 'interface']) |
            Q(app_label='ipam', model__in=['ipaddresstointerface'])
        ).order_by('app_label', 'model')

    def clean(self):
        """Validate the DNS rule form."""
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data

        # Validate templates syntax
        env = Environment()
        for field in ['zone_template', 'name_template', 'value_template']:
            template = cleaned_data.get(field)
            if template:
                try:
                    env.parse(template)
                except TemplateSyntaxError as e:
                    self.add_error(field, f"Invalid Jinja2 template syntax: {str(e)}")

        # Validate MX preference is set when record type is MX
        record_type = cleaned_data.get('record_type')
        if record_type == 'MX' and not cleaned_data.get('mx_preference'):
            self.add_error('mx_preference', "MX preference is required for MX records")

        return cleaned_data


class DNSRuleBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNS Rule bulk edit form."""

    pk = forms.ModelMultipleChoiceField(
        queryset=models.DNSRule.objects.all(),
        widget=forms.MultipleHiddenInput
    )
    enabled = forms.NullBooleanField(required=False)
    priority = forms.IntegerField(required=False)
    ttl = forms.IntegerField(required=False)
    description = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""
        nullable_fields = [
            'description',
        ]


class DNSRuleFilterForm(NautobotFilterForm):
    """Filter form for DNS Rules."""

    model = models.DNSRule

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name and Description",
    )
    name = forms.CharField(required=False)
    content_type = forms.ModelChoiceField(
        queryset=ContentType.objects.filter(
            app_label='dcim',
            model__in=['device', 'interface']
        ).order_by('model'),
        required=False
    )
    record_type = forms.ChoiceField(
        choices=[('', '---------')] + models.DNSRule._meta.get_field('record_type').choices,
        required=False
    )
    enabled = forms.NullBooleanField(required=False)

    class Meta:
        """Meta attributes."""
        fields = [
            'q',
            'name',
            'content_type',
            'record_type',
            'enabled',
        ]
