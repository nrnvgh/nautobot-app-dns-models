"""DNS Plugin Views."""

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from nautobot.apps import views
from nautobot.apps.forms import ConfirmationForm, restrict_form_fields
from nautobot.apps.ui import (
    ButtonColorChoices,
    ObjectDetailContent,
    ObjectFieldsPanel,
    ObjectsTablePanel,
    SectionChoices,
    StatsPanel,
)
from nautobot.apps.views import ObjectDestroyViewMixin, ObjectEditViewMixin, get_obj_from_context
from nautobot.core.ui import object_detail
from nautobot.core.utils.requests import convert_querydict_to_dict

# Not re-exported through `nautobot.apps`, but this is the helper core's own bulk edit view and job
# use to resolve a selection: pk_list, "select all" with its filters, saved views, and permissions.
from nautobot.core.views.utils import get_bulk_queryset_from_view
from nautobot.ipam.tables import PrefixTable
from rest_framework.decorators import action

from nautobot_dns_models.api.serializers import (
    AAAARecordSerializer,
    ARecordSerializer,
    CatalogZoneMembershipSerializer,
    CNAMERecordSerializer,
    DNSRegistrarSerializer,
    DNSRegistrationSerializer,
    DNSViewSerializer,
    DNSZoneSerializer,
    MXRecordSerializer,
    NSRecordSerializer,
    PTRRecordSerializer,
    SRVRecordSerializer,
    TXTRecordSerializer,
)
from nautobot_dns_models.choices import DNSZoneTypeChoices
from nautobot_dns_models.filters import (
    AAAARecordFilterSet,
    ARecordFilterSet,
    CNAMERecordFilterSet,
    DNSRegistrarFilterSet,
    DNSRegistrationFilterSet,
    DNSViewFilterSet,
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
    CatalogZoneMembershipForm,
    CNAMERecordBulkEditForm,
    CNAMERecordFilterForm,
    CNAMERecordForm,
    DNSRegistrarBulkEditForm,
    DNSRegistrarFilterForm,
    DNSRegistrarForm,
    DNSRegistrationBulkEditForm,
    DNSRegistrationFilterForm,
    DNSRegistrationForm,
    DNSViewBulkEditForm,
    DNSViewFilterForm,
    DNSViewForm,
    DNSZoneBulkAddMembershipForm,
    DNSZoneBulkEditForm,
    DNSZoneFilterForm,
    DNSZoneForm,
    DNSZoneWithCatalogBulkEditForm,
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
    CatalogZoneMembership,
    CNAMERecord,
    DNSRegistrar,
    DNSRegistration,
    DNSView,
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
    CatalogMemberZoneTable,
    CNAMERecordTable,
    DNSRegistrarTable,
    DNSRegistrationTable,
    DNSViewTable,
    DNSZoneTable,
    MXRecordTable,
    NSRecordTable,
    PTRRecordTable,
    SRVRecordTable,
    TXTRecordTable,
)


class ZoneFieldsPanel(ObjectFieldsPanel):
    """The zone's own fields, minus membership fields that cannot apply to this zone type.

    A whole-panel `should_render()` cannot drop a single row, so `catalog` is dropped from the data
    on a catalog zone instead.
    """

    def get_data(self, context):
        """Drop fields that this zone's type cannot use."""
        data = super().get_data(context)
        zone = get_obj_from_context(context)
        if zone is not None and zone.is_catalog_zone:
            data.pop("catalog", None)

        return data


class ZoneRecordsTablePanel(ObjectsTablePanel):
    """A table of one record type on the zone detail page, shown according to what the zone's type allows."""

    def __init__(self, **kwargs):
        """Instantiate a zone-records panel.

        Keyword Args:
            system_managed (bool): Show this panel on catalog zones only, without write controls.
                Defaults to False, which shows it wherever the record type is user-creatable.
            **kwargs: Passed to `ObjectsTablePanel`.
        """
        self.system_managed = kwargs.pop("system_managed", False)
        table_class = kwargs.get("table_class") or self.table_class
        kwargs.setdefault("table_title", table_class.Meta.model._meta.verbose_name_plural)
        kwargs.setdefault("table_filter", "zone")
        kwargs.setdefault("max_display_count", 5)

        if self.system_managed:
            kwargs.setdefault("add_button_route", None)
            kwargs.setdefault("exclude_columns", ["zone", "actions"])
        else:
            kwargs.setdefault("exclude_columns", ["zone"])

        super().__init__(**kwargs)

    def should_render(self, context):
        """Render a user-managed panel where the type is creatable, or a system panel on a catalog."""
        if not super().should_render(context):
            return False

        zone = get_obj_from_context(context)
        if zone is None:
            return False

        if self.system_managed:
            return zone.is_catalog_zone

        return DNSZone.zone_type_allows_records(zone.zone_type)


class ZoneRegistrationPanel(ObjectsTablePanel):
    """The zone's registrar row, omitted on catalog zones, which are not registered names."""

    def should_render(self, context):
        """Render only for zones that are not catalogs."""
        if not super().should_render(context):
            return False

        zone = get_obj_from_context(context)
        return zone is not None and not zone.is_catalog_zone


class CatalogMemberZoneTablePanel(ObjectsTablePanel):
    """Memberships of a catalog zone, listed as its member zones."""

    def __init__(self, **kwargs):
        """Apply member-zone table defaults on the catalog detail page."""
        kwargs.setdefault("table_filter", "catalog_zone")
        kwargs.setdefault("table_title", "Member Zones")
        kwargs.setdefault("related_list_url_name", "plugins:nautobot_dns_models:dnszone_list")
        kwargs.setdefault("related_field_name", "catalog")
        kwargs.setdefault(
            "footer_content_template_path",
            "nautobot_dns_models/panels/member_zones_footer.html",
        )
        super().__init__(**kwargs)

    def should_render(self, context):
        """Render only for catalog zones."""
        if not super().should_render(context):
            return False

        zone = get_obj_from_context(context)
        return zone is not None and zone.is_catalog_zone

    def _get_table_add_url(self, context):
        """Seed the add form's `catalog_zone` field.

        `related_field_name` is `catalog` so the count badge can link to the zone list. The add form
        field is `catalog_zone`; the parent's add URL would otherwise pass `catalog=` and leave the
        picker empty.
        """
        request = context["request"]
        if not request.user.has_perm("nautobot_dns_models.add_catalogzonemembership"):
            return None

        obj = get_obj_from_context(context)
        add_route = reverse("plugins:nautobot_dns_models:catalogzonemembership_add")
        return_url = context.get("return_url", obj.get_absolute_url())
        return f"{add_route}?catalog_zone={obj.pk}&return_url={return_url}"


class RecordStatsPanel(StatsPanel):
    """Record counts for a zone that holds user-managed records.

    A subclass rather than a conditional `related_models`, because `StatsPanel` takes that list once
    at construction and its `should_render()` is unconditional.
    """

    def should_render(self, context):
        """Render only where the zone permits users to manage records."""
        zone = get_obj_from_context(context)
        return zone is not None and DNSZone.zone_type_allows_records(zone.zone_type)


class AddRecordButton(object_detail.Button):
    """An Add Records menu entry, offered only where the zone's type permits that record type."""

    def __init__(self, *, record_model, **kwargs):
        """Bind the record type this entry creates."""
        self.record_model = record_model
        kwargs.setdefault("label", record_model._meta.verbose_name)
        super().__init__(**kwargs)

    def should_render(self, context):
        """Render only where this entry's record type is user-creatable."""
        if not super().should_render(context):
            return False

        zone = get_obj_from_context(context)
        return zone is not None and DNSZone.zone_type_allows_records(zone.zone_type)


class AddRecordsDropdownButton(object_detail.DropdownButton):
    """The Add Records menu, hidden when the zone's type leaves it with nothing to offer.

    `DropdownButton` filters its children on render but still draws itself, so a zone with no
    creatable record types would otherwise show a menu that opens onto nothing.
    """

    def should_render(self, context):
        """Render only while at least one record type remains on offer."""
        if not super().should_render(context):
            return False

        return any(child.should_render(context) for child in self.children)


class DNSViewUIViewSet(views.NautobotUIViewSet):
    """DNSView UI ViewSet."""

    form_class = DNSViewForm
    bulk_update_form_class = DNSViewBulkEditForm
    filterset_class = DNSViewFilterSet
    filterset_form_class = DNSViewFilterForm
    serializer_class = DNSViewSerializer
    lookup_field = "pk"
    queryset = DNSView.objects.all()
    table_class = DNSViewTable

    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            ),
            ObjectsTablePanel(
                weight=100,
                section=SectionChoices.RIGHT_HALF,
                table_filter="dns_view",
                table_class=DNSZoneTable,
                table_title="Zones",
                include_columns=["name", "ttl", "filename", "soa_rname", "actions"],
            ),
            ObjectsTablePanel(
                weight=200,
                section=SectionChoices.RIGHT_HALF,
                table_filter="dns_views",
                related_field_name="nautobot_dns_models_dns_views",
                table_class=PrefixTable,
                table_title="Assigned Prefixes",
                include_columns=["prefix", "status", "location_count", "namespace"],
            ),
        ],
    )


class DNSRegistrarUIViewSet(views.NautobotUIViewSet):
    """DNSRegistrar UI ViewSet."""

    form_class = DNSRegistrarForm
    bulk_update_form_class = DNSRegistrarBulkEditForm
    filterset_class = DNSRegistrarFilterSet
    filterset_form_class = DNSRegistrarFilterForm
    serializer_class = DNSRegistrarSerializer
    lookup_field = "pk"
    queryset = DNSRegistrar.objects.all()
    table_class = DNSRegistrarTable

    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            ),
            ObjectsTablePanel(
                weight=100,
                section=SectionChoices.RIGHT_HALF,
                table_filter="dns_registrar",
                table_class=DNSRegistrationTable,
                table_title="Registrations",
                include_columns=["dns_zone", "status", "expiration_date", "auto_renewal", "actions"],
            ),
        ],
    )


class DNSRegistrationUIViewSet(views.NautobotUIViewSet):
    """DNSRegistration UI ViewSet."""

    form_class = DNSRegistrationForm
    bulk_update_form_class = DNSRegistrationBulkEditForm
    filterset_class = DNSRegistrationFilterSet
    filterset_form_class = DNSRegistrationFilterForm
    serializer_class = DNSRegistrationSerializer
    lookup_field = "pk"
    queryset = DNSRegistration.objects.all()
    table_class = DNSRegistrationTable

    object_detail_content = ObjectDetailContent(
        panels=[
            ObjectFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
            ),
        ],
    )


class DNSZoneUIViewSet(views.NautobotUIViewSet):
    """DNSZone UI ViewSet."""

    form_class = DNSZoneForm
    bulk_update_form_class = DNSZoneBulkEditForm
    filterset_class = DNSZoneFilterSet
    filterset_form_class = DNSZoneFilterForm
    serializer_class = DNSZoneSerializer
    lookup_field = "pk"
    queryset = DNSZone.objects.prefetch_related("catalog_memberships__catalog_zone")
    table_class = DNSZoneTable

    object_detail_content = ObjectDetailContent(
        panels=[
            # Left pane
            ZoneFieldsPanel(
                weight=100,
                section=SectionChoices.LEFT_HALF,
                fields="__all__",
                additional_fields=["catalog"],
                key_transforms={"catalog": "Catalog Zone"},
            ),
            ZoneRegistrationPanel(
                weight=200,
                section=SectionChoices.LEFT_HALF,
                table_filter="dns_zone",
                table_class=DNSRegistrationTable,
                table_title="Registration",
                include_columns=["dns_registrar", "status", "expiration_date", "auto_renewal", "actions"],
                max_display_count=1,
            ),
            # Same weight: only one of these renders, so they occupy the same left-pane slot.
            ZoneRecordsTablePanel(
                weight=300,
                section=SectionChoices.LEFT_HALF,
                table_class=NSRecordTable,
            ),
            ZoneRecordsTablePanel(
                weight=300,
                section=SectionChoices.LEFT_HALF,
                table_class=NSRecordTable,
                system_managed=True,
            ),
            ZoneRecordsTablePanel(
                weight=400,
                section=SectionChoices.LEFT_HALF,
                table_class=TXTRecordTable,
                system_managed=True,
            ),
            # Right pane
            RecordStatsPanel(
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
            CatalogMemberZoneTablePanel(
                weight=50,
                section=SectionChoices.RIGHT_HALF,
                table_class=CatalogMemberZoneTable,
                max_display_count=10,
            ),
            ZoneRecordsTablePanel(
                weight=100,
                section=SectionChoices.RIGHT_HALF,
                table_class=ARecordTable,
            ),
            ZoneRecordsTablePanel(
                weight=200,
                section=SectionChoices.RIGHT_HALF,
                table_class=AAAARecordTable,
            ),
            ZoneRecordsTablePanel(
                weight=300,
                section=SectionChoices.RIGHT_HALF,
                table_class=CNAMERecordTable,
            ),
            ZoneRecordsTablePanel(
                weight=400,
                section=SectionChoices.RIGHT_HALF,
                table_class=MXRecordTable,
            ),
            ZoneRecordsTablePanel(
                weight=500,
                section=SectionChoices.RIGHT_HALF,
                table_class=PTRRecordTable,
            ),
            ZoneRecordsTablePanel(
                weight=600,
                section=SectionChoices.RIGHT_HALF,
                table_class=SRVRecordTable,
            ),
            ZoneRecordsTablePanel(
                weight=700,
                section=SectionChoices.RIGHT_HALF,
                table_class=TXTRecordTable,
            ),
        ],
        extra_buttons=[
            AddRecordsDropdownButton(
                weight=100,
                color=ButtonColorChoices.BLUE,
                label="Add Records",
                icon="mdi-plus-thick",
                required_permissions=["nautobot_dns_models.change_dnszone"],
                children=(
                    AddRecordButton(
                        weight=100,
                        record_model=ARecord,
                        link_name="plugins:nautobot_dns_models:zone_a_records_add",
                        required_permissions=["nautobot_dns_models.add_arecord"],
                    ),
                    AddRecordButton(
                        weight=200,
                        record_model=AAAARecord,
                        link_name="plugins:nautobot_dns_models:zone_aaaa_records_add",
                        required_permissions=["nautobot_dns_models.add_aaaarecord"],
                    ),
                    AddRecordButton(
                        weight=300,
                        record_model=CNAMERecord,
                        link_name="plugins:nautobot_dns_models:zone_cname_records_add",
                        required_permissions=["nautobot_dns_models.add_cnamerecord"],
                    ),
                    AddRecordButton(
                        weight=400,
                        record_model=MXRecord,
                        link_name="plugins:nautobot_dns_models:zone_mx_records_add",
                        required_permissions=["nautobot_dns_models.add_mxrecord"],
                    ),
                    AddRecordButton(
                        weight=500,
                        record_model=NSRecord,
                        link_name="plugins:nautobot_dns_models:zone_ns_records_add",
                        required_permissions=["nautobot_dns_models.add_nsrecord"],
                    ),
                    AddRecordButton(
                        weight=600,
                        record_model=PTRRecord,
                        link_name="plugins:nautobot_dns_models:zone_ptr_records_add",
                        required_permissions=["nautobot_dns_models.add_ptrrecord"],
                    ),
                    AddRecordButton(
                        weight=700,
                        record_model=SRVRecord,
                        link_name="plugins:nautobot_dns_models:zone_srv_records_add",
                        required_permissions=["nautobot_dns_models.add_srvrecord"],
                    ),
                    AddRecordButton(
                        weight=800,
                        record_model=TXTRecord,
                        link_name="plugins:nautobot_dns_models:zone_txt_records_add",
                        required_permissions=["nautobot_dns_models.add_txtrecord"],
                    ),
                ),
            ),
        ],
    )

    def form_save(self, form, **kwargs):
        """Refuse a membership change the user could not have made on the membership itself.

        The form's `catalog` field writes `CatalogZoneMembership` rows, which `change_dnszone` alone
        should not authorize. Object-level constraints are evaluated against the stored row, so a
        new membership can only be tested once it exists; the enclosing transaction takes the zone
        back out with it.
        """
        operation, current_membership = self._get_pending_membership_change(form)
        if operation is not None:
            self._require_membership_permission(form, operation, current_membership)

        zone = super().form_save(form, **kwargs)

        if operation in ("add", "change"):
            # Read the row from the database: the zone carries the memberships it was loaded with,
            # which predate the row this save wrote.
            self._require_membership_permission(
                form, operation, CatalogZoneMembership.objects.filter(member_zone=zone).first()
            )

        return zone

    def get_form_class(self, **kwargs):
        """Disable the bulk PTR control when the selection includes a catalog zone."""
        if self.action == "bulk_update" and self._selection_includes_catalog_zone():
            return DNSZoneWithCatalogBulkEditForm

        return super().get_form_class(**kwargs)

    @action(
        detail=False,
        methods=["POST"],
        url_path="add-membership",
        url_name="bulk_add_membership",
        custom_view_base_action="change",
        custom_view_additional_permissions=["nautobot_dns_models.add_catalogzonemembership"],
    )
    def bulk_add_membership(self, request):
        """Add a selection of zones to one catalog, confirming the selection first.

        Bulk edit only writes fields on the zone. Adding a membership is a write on a different
        model, and bulk edit would not check permission on that write. The list sends the
        selection here to confirm; submitting the form applies it in one transaction.
        """
        model = self.get_queryset().model
        select_all = bool(request.POST.get("_all"))
        pk_list = list(request.POST.getlist("pk"))
        zones = self._get_selected_zones(request)
        if not zones.exists():
            messages.warning(request, "No zones were selected.")
            return redirect(self.get_return_url(request))

        applying = "_apply" in request.POST
        form = DNSZoneBulkAddMembershipForm(zones, request.POST if applying else None)
        restrict_form_fields(form, request.user)

        if applying and form.is_valid():
            try:
                with transaction.atomic():
                    added, moved = self._add_memberships(zones, form.cleaned_data["catalog"])
            except ObjectDoesNotExist:
                form.add_error(None, "Adding to the catalog failed due to object-level permissions violation.")
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"Added {added} and moved {moved} zones.")
                return redirect(self.get_return_url(request))

        return render(
            request,
            "nautobot_dns_models/dnszone_bulk_add_membership.html",
            {
                "form": form,
                "obj_type_plural": model._meta.verbose_name_plural,
                "pk_list": pk_list,
                "return_url": self.get_return_url(request),
                "select_all": select_all,
                # Listing every zone behind a "select all" would be a page of its own, so that case
                # reports the count instead, as the bulk delete confirmation does.
                "selected_count": zones.count(),
                "table": None if select_all else self.get_table_class()(zones, orderable=False),
            },
        )

    @action(
        detail=False,
        methods=["POST"],
        url_path="remove-membership",
        url_name="bulk_remove_membership",
        custom_view_base_action="change",
        custom_view_additional_permissions=["nautobot_dns_models.delete_catalogzonemembership"],
    )
    def bulk_remove_membership(self, request):
        """Remove a selection of zones from the catalogs holding them, confirming the selection first.

        Zones with no catalog are left alone.
        """
        model = self.get_queryset().model
        select_all = bool(request.POST.get("_all"))
        pk_list = list(request.POST.getlist("pk"))
        zones = self._get_selected_zones(request)
        if not zones.exists():
            messages.warning(request, "No zones were selected.")
            return redirect(self.get_return_url(request))

        memberships = CatalogZoneMembership.objects.filter(member_zone__in=zones)
        applying = "_apply" in request.POST
        form = ConfirmationForm(request.POST if applying else None)

        if applying and form.is_valid():
            try:
                with transaction.atomic():
                    removed = self._remove_memberships(memberships)
            except ObjectDoesNotExist:
                form.add_error(None, "Removing from the catalog failed due to object-level permissions violation.")
            else:
                messages.success(request, f"Removed {removed} zones from their catalogs.")
                return redirect(self.get_return_url(request))

        return render(
            request,
            "nautobot_dns_models/dnszone_bulk_remove_membership.html",
            {
                "membership_count": memberships.count(),
                "form": form,
                "obj_type_plural": model._meta.verbose_name_plural,
                "pk_list": pk_list,
                "return_url": self.get_return_url(request),
                "select_all": select_all,
                "selected_count": zones.count(),
                "table": None if select_all else self.get_table_class()(zones, orderable=False),
            },
        )

    def _get_selected_zones(self, request):
        """Return the zones the list selected for a bulk membership action."""
        return get_bulk_queryset_from_view(
            user=request.user,
            action="change",
            content_type=ContentType.objects.get_for_model(self.get_queryset().model),
            edit_all=bool(request.POST.get("_all")),
            filter_query_params=convert_querydict_to_dict(request.GET),
            pk_list=list(request.POST.getlist("pk")),
            saved_view_id=request.GET.get("saved_view", ""),
        )

    def _add_memberships(self, zones, catalog_zone):
        """Write the memberships the selection implies, returning how many were added and how many moved."""
        written = {"add": [], "change": []}
        memberships = {
            membership.member_zone_id: membership
            for membership in CatalogZoneMembership.objects.filter(member_zone__in=zones)
        }

        # The check after the writes reads each row as the move left it. An object-level constraint
        # can admit a row in the destination catalog while holding it out of the one it is leaving,
        # so a move is authorized against the stored row first, as `form_save` does.
        self._require_bulk_membership_permission(
            [membership.pk for membership in memberships.values() if membership.catalog_zone_id != catalog_zone.pk],
            "change",
        )

        for zone in zones:
            membership = memberships.get(zone.pk)
            if membership is None:
                membership = CatalogZoneMembership(catalog_zone=catalog_zone, member_zone=zone)
                operation = "add"
            elif membership.catalog_zone_id != catalog_zone.pk:
                membership.catalog_zone = catalog_zone
                operation = "change"
            else:
                continue

            membership.validated_save()
            written[operation].append(membership.pk)

        for operation, pks in written.items():
            self._require_bulk_membership_permission(pks, operation)

        return len(written["add"]), len(written["change"])

    def _require_bulk_membership_permission(self, pks, operation):
        """Refuse the batch unless `operation` is within reach on every membership listed."""
        permitted = CatalogZoneMembership.objects.restrict(self.request.user, operation).filter(pk__in=pks)
        if permitted.count() != len(pks):
            raise ObjectDoesNotExist

    def _remove_memberships(self, memberships):
        """Delete the memberships a selection holds, refusing the batch if one of them is out of reach."""
        pks = list(memberships.values_list("pk", flat=True))
        if not pks:
            return 0

        self._require_bulk_membership_permission(pks, "delete")

        # Delete the rows the check covered: `memberships` is evaluated again on its own delete, so
        # a membership written for a selected zone in between would go with them unchecked.
        CatalogZoneMembership.objects.filter(pk__in=pks).delete()
        return len(pks)

    def _get_pending_membership_change(self, form):
        """Name the membership operation the submitted catalog implies, and the row it acts on."""
        membership = form.instance.catalog_memberships.first() if form.instance.present_in_database else None
        catalog_zone = form.cleaned_data.get("catalog")

        if membership is None:
            return ("add", None) if catalog_zone is not None else (None, None)

        if catalog_zone is None:
            return "delete", membership

        if membership.catalog_zone_id != catalog_zone.pk:
            return "change", membership

        return None, None

    def _require_membership_permission(self, form, operation, membership):
        """Refuse the save unless the user may perform this membership operation, reporting on the catalog field."""
        if self.request.user.has_perm(f"nautobot_dns_models.{operation}_catalogzonemembership", membership):
            return

        message = {
            "add": "You do not have permission to add a zone to a catalog.",
            "change": "You do not have permission to move a zone to another catalog.",
            "delete": "You do not have permission to remove a zone from its catalog.",
        }[operation]
        form.add_error("catalog", message)
        raise ValidationError(message)

    def _selection_includes_catalog_zone(self):
        """Report whether the zones this bulk edit would reach include a catalog zone."""
        selection = get_bulk_queryset_from_view(user=self.request.user, action="change", **self.key_params)
        return selection.filter(zone_type=DNSZoneTypeChoices.TYPE_CATALOG).exists()


class CatalogZoneMembershipUIViewSet(ObjectEditViewMixin, ObjectDestroyViewMixin):
    """Add, edit, and delete pages for a catalog membership.

    The membership is a through model and has no list or detail of its own.
    """

    default_return_url = "plugins:nautobot_dns_models:dnszone_list"
    form_class = CatalogZoneMembershipForm
    lookup_field = "pk"
    object_detail_content = None
    queryset = CatalogZoneMembership.objects.select_related("catalog_zone__dns_view", "member_zone__dns_view")
    serializer_class = CatalogZoneMembershipSerializer


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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
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
            ObjectFieldsPanel(weight=100, section=SectionChoices.LEFT_HALF, fields="__all__", additional_fields=["ttl"])
        ]
    )
