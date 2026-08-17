"""Tables for nautobot_dns_models."""

import django_tables2 as tables
from nautobot.apps.tables import BaseTable, BooleanColumn, ButtonsColumn, ToggleColumn
from nautobot.tenancy.tables import TenantColumn

from nautobot_dns_models import models

DNSZONE_BUTTONS = """
{% if not record.is_catalog_zone %}
    {% with membership=record.catalog_memberships.first %}
        {% if not membership %}
            {% if perms.nautobot_dns_models.add_catalogzonemembership %}
                <li>
                    <a href="{% url 'plugins:nautobot_dns_models:catalogzonemembership_add' %}?member_zone={{ record.pk }}&return_url={{ request.path }}" class="dropdown-item text-success">
                        <span class="mdi mdi-folder-plus-outline me-4" aria-hidden="true"></span>Add to Catalog
                    </a>
                </li>
            {% endif %}
        {% elif perms.nautobot_dns_models.delete_catalogzonemembership %}
            <li>
                <a href="{% url 'plugins:nautobot_dns_models:catalogzonemembership_delete' pk=membership.pk %}?return_url={{ request.path }}" class="dropdown-item text-danger">
                    <span class="mdi mdi-folder-minus-outline me-4" aria-hidden="true"></span>Remove from Catalog
                </a>
            </li>
        {% endif %}
    {% endwith %}
{% endif %}
"""


class DNSRecordTable(BaseTable):  # pylint: disable=nb-no-model-found
    """Base table for DNS records list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    zone = tables.LinkColumn()
    ttl = tables.Column(accessor="ttl", verbose_name="TTL", orderable=False)
    enabled = BooleanColumn()


class DNSViewTable(BaseTable):
    """Table for DNS View list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    actions = ButtonsColumn(
        models.DNSView,
        # Option for modifying the default action buttons on each row:
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
        # pk_field="pk",
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSView
        fields = (
            "pk",
            "name",
            "description",
            "actions",
        )

        default_columns = (
            "pk",
            "name",
            "description",
            "actions",
        )


class DNSRegistrarTable(BaseTable):
    """Table for DNS Registrar list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    actions = ButtonsColumn(
        models.DNSRegistrar,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSRegistrar
        fields = (
            "pk",
            "name",
            "url",
            "account_number",
            "actions",
        )

        default_columns = (
            "pk",
            "name",
            "url",
            "account_number",
            "actions",
        )


class DNSRegistrationTable(BaseTable):
    """Table for DNS Registration list view."""

    pk = ToggleColumn()
    dns_registrar = tables.Column(linkify=True)
    dns_zone = tables.Column(linkify=True)
    status = tables.Column(linkify=True)
    actions = ButtonsColumn(
        models.DNSRegistration,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSRegistration
        fields = (
            "pk",
            "dns_registrar",
            "dns_zone",
            "status",
            "expiration_date",
            "auto_renewal",
            "registry_locked",
            "transfer_locked",
            "privacy_enabled",
            "website_forwarding_enabled",
            "renewal_term_months",
            "dnssec_enabled",
            "actions",
        )

        default_columns = (
            "pk",
            "dns_registrar",
            "dns_zone",
            "status",
            "expiration_date",
            "auto_renewal",
            "actions",
        )


class DNSZoneTable(BaseTable):
    """Table for DNS Zone list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    tenant = TenantColumn()
    dns_view = tables.Column(linkify=True)
    enabled = BooleanColumn()
    catalog = tables.Column(
        linkify=True,
        verbose_name="Catalog Zone",
        order_by="catalog_memberships__catalog_zone__name",
    )
    actions = ButtonsColumn(
        models.DNSZone,
        buttons=("changelog", "edit", "delete"),
        prepend_template=DNSZONE_BUTTONS,
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSZone
        fields = (
            "pk",
            "name",
            "type",
            "dns_view",
            "catalog",
            "enabled",
            "ttl",
            "filename",
            "description",
            "soa_expire",
            "soa_rname",
            "soa_refresh",
            "soa_retry",
            "soa_serial",
            "soa_minimum",
            "tenant",
            "auto_create_ptr",
            "actions",
        )

        default_columns = (
            "pk",
            "name",
            "type",
            "dns_view",
            "catalog",
            "enabled",
            "ttl",
            "filename",
            "soa_expire",
            "soa_rname",
            "actions",
        )

    def render_catalog(self, value):
        """Name the catalog alone; `DNSZone.__str__` would repeat the view the row already carries."""
        return value.name


class CatalogMemberZoneTable(BaseTable):  # pylint: disable=nb-sub-class-name
    """Membership rows on a catalog zone's Member Zones panel, listed by member zone."""

    member_zone = tables.Column(linkify=True, verbose_name="Member Zone")
    published_as = tables.Column(accessor="member_label", empty_values=(), verbose_name="Published As")
    actions = ButtonsColumn(
        models.CatalogZoneMembership,
        buttons=("edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.CatalogZoneMembership
        fields = (
            "member_zone",
            "published_as",
            "actions",
        )
        default_columns = (
            "member_zone",
            "published_as",
            "actions",
        )

    def render_member_zone(self, value):
        """Name the zone alone; `DNSZone.__str__` would repeat the view the catalog already implies."""
        return value.name

    def render_published_as(self, record):
        """RFC 9432 §4.1 owner name relative to the catalog apex."""
        return f"{record.member_label}.zones"


class NSRecordTable(DNSRecordTable):
    """Table for list view."""

    actions = ButtonsColumn(
        models.NSRecord,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.NSRecord
        fields = (
            "pk",
            "name",
            "server",
            "zone",
            "description",
            "comment",
            "ttl",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "name",
            "server",
            "zone",
            "ttl",
            "enabled",
            "actions",
        )


class ARecordTable(DNSRecordTable):
    """Table for list view."""

    ip_address = tables.Column(linkify=True)
    actions = ButtonsColumn(
        models.ARecord,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.ARecord
        fields = (
            "pk",
            "name",
            "ip_address",
            "zone",
            "comment",
            "ttl",
            "description",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "ip_address",
            "zone",
            "comment",
            "ttl",
            "enabled",
            "actions",
        )


class AAAARecordTable(DNSRecordTable):
    """Table for list view."""

    ip_address = tables.Column(linkify=True)
    actions = ButtonsColumn(
        models.AAAARecord,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.AAAARecord
        fields = (
            "pk",
            "name",
            "ip_address",
            "zone",
            "comment",
            "ttl",
            "description",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "ip_address",
            "zone",
            "comment",
            "ttl",
            "enabled",
            "actions",
        )


class CNAMERecordTable(DNSRecordTable):
    """Table for list view."""

    actions = ButtonsColumn(
        models.CNAMERecord,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.CNAMERecord
        fields = (
            "pk",
            "name",
            "alias",
            "zone",
            "comment",
            "ttl",
            "description",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "alias",
            "zone",
            "comment",
            "ttl",
            "enabled",
            "actions",
        )


class MXRecordTable(DNSRecordTable):
    """Table for list view."""

    actions = ButtonsColumn(
        models.MXRecord,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.MXRecord
        fields = (
            "pk",
            "name",
            "mail_server",
            "preference",
            "zone",
            "comment",
            "ttl",
            "description",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "mail_server",
            "preference",
            "zone",
            "comment",
            "ttl",
            "enabled",
            "actions",
        )


class TXTRecordTable(DNSRecordTable):
    """Table for list view."""

    actions = ButtonsColumn(
        models.TXTRecord,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.TXTRecord
        fields = (
            "pk",
            "name",
            "text",
            "zone",
            "comment",
            "ttl",
            "description",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "text",
            "zone",
            "comment",
            "ttl",
            "enabled",
            "actions",
        )


class PTRRecordTable(DNSRecordTable):
    """Table for list view."""

    actions = ButtonsColumn(
        models.PTRRecord,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.PTRRecord
        fields = (
            "pk",
            "name",
            "ptrdname",
            "zone",
            "comment",
            "ttl",
            "description",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "ptrdname",
            "zone",
            "comment",
            "ttl",
            "enabled",
            "actions",
        )


class SRVRecordTable(DNSRecordTable):
    """Table for list view."""

    actions = ButtonsColumn(
        models.SRVRecord,
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.SRVRecord
        fields = (
            "pk",
            "name",
            "priority",
            "weight",
            "port",
            "target",
            "zone",
            "comment",
            "ttl",
            "description",
            "enabled",
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "priority",
            "weight",
            "port",
            "target",
            "zone",
            "enabled",
            "actions",
        )
