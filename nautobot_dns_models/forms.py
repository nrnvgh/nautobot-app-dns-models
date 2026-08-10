"""Forms for nautobot_dns_models."""

from django import forms
from nautobot.apps.forms import (
    BulkEditNullBooleanSelect,
    DatePicker,
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    NautobotBulkEditForm,
    NautobotFilterForm,
    NautobotModelForm,
    StaticSelect2,
    StaticSelect2Multiple,
    TagsBulkEditFormMixin,
)

# This should be updated after https://github.com/nautobot/nautobot/issues/9302 is resolved
from nautobot.core.forms.constants import BOOLEAN_WITH_BLANK_CHOICES
from nautobot.extras.models import Status
from nautobot.ipam.choices import IPAddressVersionChoices
from nautobot.ipam.models import IPAddress, Prefix
from nautobot.tenancy.forms import TenancyFilterForm, TenancyForm
from nautobot.tenancy.models import Tenant

from nautobot_dns_models import models
from nautobot_dns_models.choices import DNSZoneTypeChoices

EXPIRATION_DATE_INPUT_FORMATS = ("%Y-%m-%d",)


class EnabledBeforeDescriptionMixin:
    """Render the `enabled` field right before `description` on create/edit forms.

    `enabled` is declared on the abstract `DNSModel` base while the concrete models override
    `name`, so with `fields = "__all__"` Django's declaration order puts `enabled` first.
    Must be listed before the form base class so this reordering runs after the fields are built.
    """

    def __init__(self, *args, **kwargs):
        """Move `enabled` so it renders immediately before `description`."""
        super().__init__(*args, **kwargs)
        if "enabled" not in self.fields or "description" not in self.fields:
            return
        enabled = self.fields.pop("enabled")
        reordered = {}
        for field_name, field in self.fields.items():
            if field_name == "description":
                reordered["enabled"] = enabled
            reordered[field_name] = field
        self.fields = reordered


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


class DNSZoneForm(EnabledBeforeDescriptionMixin, NautobotModelForm, TenancyForm):
    """DNSZone creation/edit form."""

    dns_view = DynamicModelChoiceField(
        queryset=models.DNSView.objects.all(),
        required=True,
        label="View",
    )
    catalog = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        query_params={
            "zone_type": DNSZoneTypeChoices.TYPE_CATALOG,
            "dns_view": "$dns_view",
        },
        required=False,
        label="Catalog Zone",
        help_text="Catalog zone this zone belongs to.",
    )

    field_order = ["name", "zone_type", "dns_view", "catalog", "auto_create_ptr"]

    class Meta:
        """Meta attributes."""

        model = models.DNSZone
        fields = "__all__"
        widgets = {"zone_type": StaticSelect2()}

    class Media:
        """Load create-time toggling of the controls a catalog zone cannot use."""

        js = ("nautobot_dns_models/js/dns_zone_form.js",)

    def __init__(self, *args, **kwargs):
        """Show the current catalog enrollment and disable fields the model forbids setting for this instance."""
        super().__init__(*args, **kwargs)

        if self.instance.present_in_database:
            self.initial["catalog"] = self.instance.catalog
            self.fields["zone_type"].disabled = True
            self.fields["zone_type"].help_text = "Zone type cannot be changed after creation."

            if self.instance.zone_type == DNSZoneTypeChoices.TYPE_CATALOG:
                self.fields["auto_create_ptr"].disabled = True
                self.fields["auto_create_ptr"].help_text = "Catalog zones cannot enable automatic PTR creation."
                self.fields["catalog"].disabled = True
                self.fields["catalog"].help_text = "A catalog zone cannot be a member of another catalog zone."

    def clean(self):
        """Reject an enrollment `CatalogZoneMember` would refuse, so the error lands on the field."""
        super().clean()

        catalog_zone = self.cleaned_data.get("catalog")
        if catalog_zone is None:
            return self.cleaned_data

        if self.cleaned_data.get("zone_type") == DNSZoneTypeChoices.TYPE_CATALOG:
            raise forms.ValidationError({"catalog": "A catalog zone cannot be a member of another catalog zone."})

        if not catalog_zone.is_catalog_zone:
            raise forms.ValidationError({"catalog": "The selected zone is not a catalog zone."})

        dns_view = self.cleaned_data.get("dns_view")
        if dns_view is not None and catalog_zone.dns_view_id != dns_view.pk:
            raise forms.ValidationError({"catalog": "The catalog zone must be in the same view as this zone."})

        return self.cleaned_data

    def save(self, commit=True):
        """Write the zone, then bring its catalog enrollment into line with the form."""
        zone = super().save(commit=commit)

        if commit:
            self._sync_catalog_membership(zone)

        return zone

    def _sync_catalog_membership(self, zone):
        """Create, move, or remove the membership enrolling `zone` in a catalog.

        Moving one keeps its member label, and removing one withdraws the catalog's PTR through the
        `post_delete` receiver, so neither case needs handling here.
        """
        catalog_zone = self.cleaned_data.get("catalog")
        membership = zone.catalog_membership.first()

        if catalog_zone is None:
            if membership is not None:
                membership.delete()
        elif membership is None:
            models.CatalogZoneMember(catalog_zone=catalog_zone, member_zone=zone).validated_save()
        elif membership.catalog_zone_id != catalog_zone.pk:
            membership.catalog_zone = catalog_zone
            membership.validated_save()


class DNSZoneBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """DNSZone bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.DNSZone.objects.all(), widget=forms.MultipleHiddenInput)
    dns_view = DynamicModelChoiceField(
        queryset=models.DNSView.objects.all(),
        required=False,
        label="View",
    )
    ttl = forms.IntegerField(
        required=False,
        max_value=models.UINT32_MAX,
        label="TTL",
        help_text="Time To Live.",
    )
    soa_mname = forms.CharField(
        required=False,
        max_length=200,
        help_text="FQDN of the Authoritative Name Server for Zone.",
        label="SOA MNAME",
    )
    soa_rname = forms.EmailField(
        required=False,
        help_text="Admin Email for the Zone in the form",
        label="SOA RNAME",
    )
    soa_refresh = forms.IntegerField(
        required=False,
        max_value=models.UINT32_MAX,
        help_text="Number of seconds after which secondary name servers should query the master for the SOA record, to detect zone changes.",
        label="SOA Refresh",
    )
    soa_retry = forms.IntegerField(
        required=False,
        max_value=models.UINT32_MAX,
        help_text="Number of seconds after which secondary name servers should retry to request the serial number from the master if the master does not respond.",
        label="SOA Refresh",
    )
    soa_expire = forms.IntegerField(
        required=False,
        max_value=models.UINT32_MAX,
        help_text="Number of seconds after which secondary name servers should stop answering request for this zone if the master does not respond. This value must be bigger than the sum of Refresh and Retry.",
        label="SOA Expire",
    )
    soa_serial = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=models.UINT32_MAX,
        help_text="Serial number of the zone. This value must be incremented each time the zone is changed, and secondary DNS servers must be able to retrieve this value to check if the zone has been updated.",
        label="SOA Serial",
    )
    soa_minimum = forms.IntegerField(
        required=False,
        max_value=models.UINT32_MAX,
        help_text="Minimum TTL for records in this zone.",
        label="SOA Minimum",
    )
    description = forms.CharField(required=False)
    tenant = DynamicModelChoiceField(
        queryset=Tenant.objects.all(),
        required=False,
    )
    auto_create_ptr = forms.NullBooleanField(
        required=False, label="Auto-create PTR Records", widget=BulkEditNullBooleanSelect
    )
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

    class Meta:
        """Meta attributes."""

        nullable_fields = [
            "description",
            "tenant",
        ]


class DNSZoneWithCatalogBulkEditForm(DNSZoneBulkEditForm):
    """DNSZone bulk edit form for a selection that includes at least one catalog zone.

    A catalog zone refuses `auto_create_ptr`, and the bulk edit job saves each object in turn outside
    a transaction, so offering the control would write the primary zones and then fail on the first
    catalog zone. `DNSZoneUIViewSet.get_form_class` chooses this form once it knows the selection.
    """

    def __init__(self, *args, **kwargs):
        """Withdraw the control no catalog zone in the selection could accept."""
        super().__init__(*args, **kwargs)

        self.fields["auto_create_ptr"].disabled = True
        self.fields["auto_create_ptr"].help_text = "Catalog zones cannot enable this, and the selection includes one."


class DNSZoneFilterForm(NautobotFilterForm, TenancyFilterForm):
    """Filter form to filter searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Name, Filename, SOA MNAME, and SOA RNAME.",
    )
    name = forms.CharField(required=False, label="Name")
    zone_type = forms.MultipleChoiceField(
        required=False,
        choices=DNSZoneTypeChoices,
        widget=StaticSelect2Multiple(),
        label="Zone Type",
    )
    catalog = DynamicModelMultipleChoiceField(
        queryset=models.DNSZone.objects.all(),
        query_params={"zone_type": DNSZoneTypeChoices.TYPE_CATALOG},
        required=False,
        label="Catalog Zone",
    )
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    filename = forms.CharField(required=False, label="Filename")
    model = models.DNSZone
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "zone_type",
        "catalog",
        "enabled",
        "filename",
    ]


class CatalogZoneMemberForm(NautobotModelForm):
    """CatalogZoneMember creation/edit form.

    The member label is system-assigned on create and immutable afterward, so it is omitted from
    the UI.
    """

    catalog_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        query_params={
            "zone_type": DNSZoneTypeChoices.TYPE_CATALOG,
            "same_dns_view_as": "$member_zone",
        },
        label="Catalog Zone",
    )
    member_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        # Catalogs are left out of the picker because `CatalogZoneMember.clean()` refuses them.
        # `$catalog_zone` only yields a PK, so same_dns_view_as maps that zone to its view.
        query_params={
            "zone_type__n": DNSZoneTypeChoices.TYPE_CATALOG,
            "same_dns_view_as": "$catalog_zone",
        },
        label="Member Zone",
    )

    class Meta:
        """Meta attributes."""

        model = models.CatalogZoneMember
        # Not `__all__`: `member_label` is system-assigned on create and immutable afterward, so the
        # form has nothing to offer for it.
        fields = ["catalog_zone", "member_zone"]  # pylint: disable=nb-use-fields-all

    def __init__(self, *args, **kwargs):
        """Hide already-enrolled zones from the picker."""
        super().__init__(*args, **kwargs)

        editing = self.instance.present_in_database
        # Set here rather than declared above because `add_query_param` appends: declaring the create-time
        # value would leave the edit-time one as a second entry the filter has to disambiguate.
        # Passing the membership's PK keeps its own member_zone selectable while other enrolled zones stay hidden.
        self.fields["member_zone"].widget.add_query_param(
            "available_for_catalog_membership", str(self.instance.pk) if editing else "true"
        )


class CatalogZoneMemberBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """CatalogZoneMember bulk edit form.

    Only the catalog is editable in bulk: `member_zone` is unique per membership and `member_label` is
    fixed once the membership exists.
    """

    pk = forms.ModelMultipleChoiceField(
        queryset=models.CatalogZoneMember.objects.all(), widget=forms.MultipleHiddenInput
    )
    catalog_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        query_params={"zone_type": DNSZoneTypeChoices.TYPE_CATALOG},
        required=False,
        label="Catalog Zone",
    )

    class Meta:
        """Meta attributes."""

        nullable_fields = []


class CatalogZoneMemberFilterForm(NautobotFilterForm):
    """Filter form for CatalogZoneMember searches."""

    q = forms.CharField(
        required=False,
        label="Search",
        help_text="Search within Catalog Zone, Member Zone, and Member Label.",
    )
    catalog_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        query_params={"zone_type": DNSZoneTypeChoices.TYPE_CATALOG},
        required=False,
        label="Catalog Zone",
    )
    member_zone = DynamicModelChoiceField(
        queryset=models.DNSZone.objects.all(),
        query_params={"same_dns_view_as": "$catalog_zone"},
        required=False,
        label="Member Zone",
    )
    member_label = forms.CharField(required=False, label="Member Label")
    model = models.CatalogZoneMember
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "catalog_zone",
        "member_zone",
        "member_label",
    ]


class NSRecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
    """NSRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.NSRecord
        fields = "__all__"


class NSRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """NSRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.NSRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.NSRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "description",
    ]


class ARecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
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
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.ARecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "description",
    ]


class AAAARecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
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
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.AAAARecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "description",
    ]


class CNAMERecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
    """CNAMERecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.CNAMERecord
        fields = "__all__"


class CNAMERecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """CNAMERecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.CNAMERecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.CNAMERecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "description",
    ]


class MXRecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
    """MXRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.MXRecord
        fields = "__all__"


class MXRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """MXRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.MXRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.MXRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "preference",
        "description",
    ]


class TXTRecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
    """TXTRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.TXTRecord
        fields = "__all__"


class TXTRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """TXTRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.TXTRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.TXTRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "description",
    ]


class PTRRecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
    """PTRRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.PTRRecord
        fields = "__all__"


class PTRRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """PTRRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.PTRRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.PTRRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "ttl",
        "comment",
        "description",
    ]


class SRVRecordForm(EnabledBeforeDescriptionMixin, NautobotModelForm):
    """SRVRecord creation/edit form."""

    class Meta:
        """Meta attributes."""

        model = models.SRVRecord
        fields = "__all__"


class SRVRecordBulkEditForm(TagsBulkEditFormMixin, NautobotBulkEditForm):
    """SRVRecord bulk edit form."""

    pk = forms.ModelMultipleChoiceField(queryset=models.SRVRecord.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect)

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
    enabled = forms.NullBooleanField(
        required=False,
        widget=StaticSelect2(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    model = models.SRVRecord
    # Define the fields above for ordering and widget purposes
    fields = [
        "q",
        "name",
        "enabled",
        "priority",
        "weight",
        "port",
        "target",
    ]
