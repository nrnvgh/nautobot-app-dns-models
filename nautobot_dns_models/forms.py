"""Forms for nautobot_dns_models."""

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import models as django_models
from nautobot.apps.forms import (
    NautobotBulkEditForm,
    NautobotModelForm,
    TagsBulkEditFormMixin,
)
from nautobot.extras.forms import NautobotFilterForm

from nautobot_dns_models import models


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


class DNSRuleForm(NautobotModelForm):
    """DNSRule creation/edit form with dynamic field display."""

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


class DNSRuleFilterForm(NautobotFilterForm):
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
        "record_type",
    ]
