"""Forms for nautobot_dns_models."""

from django import forms
from nautobot.apps.forms import (
    DatePicker,
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    NautobotBulkEditForm,
    NautobotFilterForm,
    NautobotModelForm,
    TagsBulkEditFormMixin,
)
from nautobot.extras.models import Status
from nautobot.ipam.choices import IPAddressVersionChoices
from nautobot.ipam.models import IPAddress, Prefix
from nautobot.tenancy.forms import TenancyFilterForm, TenancyForm
from nautobot.tenancy.models import Tenant

from nautobot_dns_models import models

EXPIRATION_DATE_INPUT_FORMATS = ("%Y-%m-%d",)


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


class DNSRegistrarForm(NautobotModelForm):
    """DNSRegistrar creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.DNSRegistrar
        fields = "__all__"


class DNSRegistrarBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSRegistrar bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSRegistrar.objects.all(), widget=forms.MultipleHiddenInput)
    url = forms.URLField(required=False)
    account_number = forms.CharField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "url",
            "account_number",
        ]


class DNSRegistrarFilterForm(NautobotFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name, URL, and Account Number.",
    )
    name = forms.CharField(required=False, label="Name")
    url = forms.CharField(required=False, label="URL")
    account_number = forms.CharField(required=False, label="Account Number")
    model = models.DNSRegistrar
    fields = [
        "q",
        "name",
        "url",
        "account_number",
    ]


class DNSRegistrationForm(NautobotModelForm):
    """DNSRegistration creation/edit form."""

    expiration_date = forms.DateField(
        required=False,
        widget=DatePicker(),
        input_formats=EXPIRATION_DATE_INPUT_FORMATS,
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSRegistration
        fields = "__all__"


class DNSRegistrationBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSRegistration bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSRegistration.objects.all(), widget=forms.MultipleHiddenInput)
    dns_registrar = DynamicModelChoiceField(
        queryset=models.DNSRegistrar.objects.all(),
        required=False,
    )
    dns_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        required=False,
    )
    status = DynamicModelChoiceField(
        queryset=Status.objects.all(),
        required=False,
    )
    expiration_date = forms.DateField(
        required=False,
        widget=DatePicker(),
        input_formats=EXPIRATION_DATE_INPUT_FORMATS,
    )
    auto_renewal = forms.NullBooleanField(required=False)
    registry_locked = forms.NullBooleanField(required=False)
    transfer_locked = forms.NullBooleanField(required=False)
    privacy_enabled = forms.NullBooleanField(required=False)
    website_forwarding_enabled = forms.NullBooleanField(required=False)
    renewal_term_months = forms.IntegerField(required=False, min_value=1)
    dnssec_enabled = forms.NullBooleanField(required=False)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "expiration_date",
            "renewal_term_months",
        ]


class DNSRegistrationFilterForm(NautobotFilterForm):
    """Filter form for DNSRegistration searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Registrar and Zone.",
    )
    dns_registrar = DynamicModelChoiceField(
        queryset=models.DNSRegistrar.objects.all(),
        required=False,
        label="Registrar",
    )
    dns_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        required=False,
        label="Zone",
    )
    status = DynamicModelChoiceField(
        queryset=Status.objects.all(),
        required=False,
        label="Status",
    )
    expiration_date__lte = forms.DateField(
        required=False,
        label="Expiration Date (Before)",
        widget=DatePicker(),
        input_formats=EXPIRATION_DATE_INPUT_FORMATS,
    )
    expiration_date__gte = forms.DateField(
        required=False,
        label="Expiration Date (After)",
        widget=DatePicker(),
        input_formats=EXPIRATION_DATE_INPUT_FORMATS,
    )
    auto_renewal = forms.NullBooleanField(required=False, label="Auto Renewal")
    registry_locked = forms.NullBooleanField(required=False, label="Registry Locked")
    transfer_locked = forms.NullBooleanField(required=False, label="Transfer Locked")
    privacy_enabled = forms.NullBooleanField(required=False, label="Privacy Enabled")
    website_forwarding_enabled = forms.NullBooleanField(required=False, label="Website Forwarding Enabled")
    renewal_term_months = forms.IntegerField(required=False, min_value=1, label="Renewal Term (Months)")
    dnssec_enabled = forms.NullBooleanField(required=False, label="DNSSEC Enabled")
    model = models.DNSRegistration
    fields = [
        "q",
        "dns_registrar",
        "dns_zone",
        "status",
        "expiration_date__lte",
        "expiration_date__gte",
        "auto_renewal",
        "registry_locked",
        "transfer_locked",
        "privacy_enabled",
        "website_forwarding_enabled",
        "renewal_term_months",
        "dnssec_enabled",
    ]


class DNSZoneForm(NautobotModelForm, TenancyForm):
    """DNSZone creation/edit form."""

    dns_view = DynamicModelChoiceField(
        queryset=models.DNSView.objects.all(),
        required=True,
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSZone
        fields = "__all__"


class DNSZoneBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSZone bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSZone.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    tenant = DynamicModelChoiceField(
        queryset=Tenant.objects.all(),
        required=False,
    )

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
            "tenant",
        ]


class DNSZoneFilterForm(NautobotFilterForm, TenancyFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name, Filename, SOA MNAME, and SOA RNAME.",
    )
    name = forms.CharField(required=False, label="Name")
    filename = forms.CharField(required=False, label="Filename")
    member_of_catalog_zones = DynamicModelMultipleChoiceField(
        queryset=models.CatalogZone.objects.all(),
        required=False,
        to_field_name="id",
        label="Catalog Zone",
    )
    model = models.DNSZone
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "filename",
        "member_of_catalog_zones",
    ]


# TODO: determine if we should be setting default timer (retry, expire, etc) values for new catalog zones
class CatalogZoneForm(NautobotModelForm, TenancyForm):
    """CatalogZone creation/edit form."""

    name = forms.CharField(required=True)
    ttl = forms.IntegerField(
        required=False,
        disabled=True,
        label="TTL",
        initial=models.CATALOG_ZONE_DEFAULT_TTL,
        help_text="Immutable for catalog zones. This value is system-managed.",
    )
    filename = forms.CharField(required=True)
    dns_view = DynamicModelChoiceField(
        queryset=models.DNSView.objects.all(),
        required=True,
        initial=models.DNSZone._meta.get_field("dns_view").default,
    )
    soa_mname = forms.CharField(
        required=False,
        disabled=True,
        label="SOA MNAME",
        initial=models.CATALOG_ZONE_DEFAULT_SOA_MNAME,
        help_text="Immutable for catalog zones. This value is system-managed.",
    )
    soa_rname = forms.EmailField(
        required=False,
        disabled=True,
        label="SOA RNAME",
        initial=models.CATALOG_ZONE_DEFAULT_SOA_RNAME,
        help_text="Immutable for catalog zones. This value is system-managed.",
    )
    soa_refresh = forms.IntegerField(required=True, min_value=300, max_value=2147483647, label="SOA Refresh")
    soa_retry = forms.IntegerField(required=True, min_value=300, max_value=2147483647, label="SOA Retry")
    soa_expire = forms.IntegerField(required=True, min_value=300, max_value=2147483647, label="SOA Expire")
    soa_serial = forms.IntegerField(
        required=False,
        disabled=True,
        label="SOA Serial",
        initial=models.CATALOG_ZONE_DEFAULT_SOA_SERIAL,
        help_text="Immutable for catalog zones. This value is system-managed.",
    )
    soa_minimum = forms.IntegerField(required=True, min_value=300, max_value=2147483647, label="SOA Minimum")
    field_order = (
        "name",
        "dns_view",
        "ttl",
        "filename",
        "description",
        "soa_mname",
        "soa_rname",
        "soa_refresh",
        "soa_retry",
        "soa_expire",
        "soa_serial",
        "soa_minimum",
        "tenant",
        "tags",
    )

    class Meta:
        """Meta attributes."""

        model = models.CatalogZone
        # Backing DNS zone is system-managed, so exclude it from the form.
        fields = "__all__"
        exclude = ("dns_zone",)  # pylint: disable=modelform-uses-exclude

    def __init__(self, *args, **kwargs):
        """Populate curated backing-zone fields when editing."""
        super().__init__(*args, **kwargs)

        # Keep wrapper form help text aligned with DNSZone for writable shared fields.
        dns_zone_field_names = {field.name for field in models.DNSZone._meta.fields}
        for field_name, form_field in self.fields.items():
            if form_field.disabled or field_name not in dns_zone_field_names:
                continue

            form_field.help_text = models.DNSZone._meta.get_field(field_name).help_text

        if self.instance and self.instance.pk and self.instance.dns_zone_id:
            zone = self.instance.dns_zone
            self.fields["name"].initial = zone.name
            self.fields["ttl"].initial = zone.ttl
            self.fields["filename"].initial = zone.filename
            self.fields["dns_view"].initial = zone.dns_view
            self.fields["soa_mname"].initial = zone.soa_mname
            self.fields["soa_rname"].initial = zone.soa_rname
            self.fields["tenant"].initial = zone.tenant
            self.fields["soa_refresh"].initial = zone.soa_refresh
            self.fields["soa_retry"].initial = zone.soa_retry
            self.fields["soa_expire"].initial = zone.soa_expire
            self.fields["soa_serial"].initial = zone.soa_serial
            self.fields["soa_minimum"].initial = zone.soa_minimum

    def clean(self):
        """Allow wrapper create validation before backing zone exists."""
        cleaned_data = super().clean()
        if self.instance._state.adding:  # pylint: disable=protected-access
            self.instance._allow_missing_backing_zone = True  # pylint: disable=protected-access

        return cleaned_data

    def save(self, commit=True):
        """Persist catalog wrapper via model-owned backing-zone orchestration."""
        if not commit:
            raise ValueError("CatalogZoneForm requires commit=True.")

        instance = super().save(commit=False)
        payload = {
            "name": self.cleaned_data["name"],
            "filename": self.cleaned_data["filename"],
            "dns_view": self.cleaned_data["dns_view"],
            "tenant": self.cleaned_data.get("tenant"),
            "soa_refresh": self.cleaned_data["soa_refresh"],
            "soa_retry": self.cleaned_data["soa_retry"],
            "soa_expire": self.cleaned_data["soa_expire"],
            "soa_minimum": self.cleaned_data["soa_minimum"],
            "description": self.cleaned_data.get("description", ""),
        }

        if not instance._state.adding:  # pylint: disable=protected-access
            instance.update_backing_zone_payload(**payload)
            return instance

        return models.CatalogZone.create_with_backing_zone_payload(**payload)


class CatalogZoneBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """CatalogZone bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.CatalogZone.objects.all(), widget=forms.MultipleHiddenInput)
    dns_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        required=False,
        label="Backing DNS Zone",
        query_params={"sort": "name"},
    )

    class Meta:
        """Meta attributes."""

        nullable_fields = []


class CatalogZoneFilterForm(NautobotFilterForm):
    """Filter form to filter catalog zone searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within backing DNS Zone name.",
    )
    dns_zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        required=False,
        label="Backing DNS Zone",
        query_params={"has_catalog_zone": True, "sort": "name"},
    )
    member_zones = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        required=False,
        label="Member DNS Zones",
        query_params={"has_catalog_zone": False, "sort": "name"},
    )
    model = models.CatalogZone
    fields = [
        "q",
        "dns_zone",
        "member_zones",
    ]


class CatalogZoneMembershipForm(NautobotModelForm):
    """CatalogZoneMembership creation/edit form."""

    catalog_zone = DynamicModelChoiceField(
        queryset=models.CatalogZone.objects.all(),
        required=True,
        label="Catalog Zone",
    )
    member_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        required=True,
        label="Member DNS Zone",
        query_params={"eligible_for_catalog_zone": "$catalog_zone", "sort": "name"},
    )

    class Meta:
        """Meta attributes."""

        model = models.CatalogZoneMembership
        fields = "__all__"


class CatalogZoneMembershipFilterForm(NautobotFilterForm):
    """Filter form to filter catalog membership searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within catalog zone, member zone, and member node label.",
    )
    catalog_zone = DynamicModelMultipleChoiceField(
        queryset=models.CatalogZone.objects.all(),
        required=False,
        label="Catalog Zone",
    )
    member_zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        required=False,
        label="Member DNS Zone",
    )
    model = models.CatalogZoneMembership
    fields = [
        "q",
        "catalog_zone",
        "member_zone",
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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
    model = models.NSRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class ARecordForm(NautobotModelForm):
    """ARecord creation/edit form."""

    ip_address = DynamicModelChoiceField(
        queryset=IPAddress.objects.all(),
        required=True,
        query_params={"ip_version": IPAddressVersionChoices.VERSION_4},
    )

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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
    model = models.ARecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "description",
    ]


class AAAARecordForm(NautobotModelForm):
    """AAAARecord creation/edit form."""

    ip_address = DynamicModelChoiceField(
        queryset=IPAddress.objects.all(),
        required=True,
        query_params={"ip_version": IPAddressVersionChoices.VERSION_6},
    )

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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
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
    zone = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        to_field_name="name",
        required=False,
        label="Zone",
    )
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
