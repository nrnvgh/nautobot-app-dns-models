"""Tables for nautobot_dns_models."""

from urllib.parse import urlencode

import django_tables2 as tables
from django.conf import settings
from django.urls import reverse
from django.utils.html import format_html
from nautobot.apps.tables import BaseTable, BooleanColumn, ButtonsColumn, LinkedCountColumn, ToggleColumn
from nautobot.tenancy.tables import TenantColumn

from nautobot_dns_models import models


class LinkedCountBadgeColumn(LinkedCountColumn):
    """LinkedCountColumn variant that always renders count badges."""

    def render(self, *, bound_column, record, value):  # pylint: disable=arguments-differ  # tables2 varies its kwargs
        """Render `1` as a linked badge instead of object hyperlink."""
        if value != 1:
            return super().render(bound_column=bound_column, record=record, value=value)

        url = reverse(self.viewname, kwargs=self.view_kwargs)
        if self.url_params:
            url += "?" + urlencode(
                {k: (getattr(record, v) or settings.FILTERS_NULL_CHOICE_VALUE) for k, v in self.url_params.items()}
            )
        # Bootstrap 3.4 badges don't support colors natively, so we use labels with a danger color.
        return format_html('<a href="{}" class="label label-danger">{}</a>', url, value)


class DNSRecordTable(BaseTable):  # pylint: disable=nb-no-model-found
    """Base table for DNS records list view."""

    pk = ToggleColumn()
    name = tables.LinkColumn()
    zone = tables.LinkColumn()
    ttl = tables.Column(accessor="ttl", verbose_name="TTL", orderable=False)
    source_object = tables.LinkColumn()
    dns_rule = tables.LinkColumn(verbose_name="DNS Rule")


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


class DNSZoneTable(BaseTable):
    """Table for DNS Zone list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    dns_view = tables.Column(linkify=True)
    actions = ButtonsColumn(
        models.DNSZone,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSZone
        fields = (
            "pk",
            "name",
            "dns_view",
            "ttl",
            "filename",
            "description",
            "soa_expire",
            "soa_rname",
            "soa_refresh",
            "soa_retry",
            "soa_serial",
            "soa_minimum",
            "actions",
        )

        default_columns = ("pk", "name", "dns_view", "ttl", "filename", "soa_expire", "soa_rname", "actions")


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
            "actions",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "name",
            "server",
            "zone",
            "ttl",
            "actions",
        )


class ARecordTable(DNSRecordTable):
    """Table for list view."""

    address = tables.LinkColumn()
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
            "address",
            "zone",
            "comment",
            "ttl",
            "description",
            "actions",
            "source_object",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "address",
            "zone",
            "comment",
            "ttl",
            "actions",
            "source_object",
        )


class AAAARecordTable(DNSRecordTable):
    """Table for list view."""

    address = tables.LinkColumn()
    actions = ButtonsColumn(
        models.AAAARecord,
        buttons=("changelog", "edit", "delete"),
    )
    dns_rule = tables.LinkColumn(verbose_name="DNS Rule")

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.AAAARecord
        fields = (
            "pk",
            "name",
            "address",
            "zone",
            "comment",
            "ttl",
            "description",
            "actions",
            "source_object",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "address",
            "zone",
            "comment",
            "ttl",
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
            "actions",
            "source_object",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "alias",
            "zone",
            "comment",
            "ttl",
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
            "zone",
            "comment",
            "ttl",
            "description",
            "actions",
            "source_object",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "mail_server",
            "zone",
            "comment",
            "ttl",
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
            "actions",
            "source_object",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "text",
            "zone",
            "comment",
            "ttl",
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
            "actions",
            "source_object",
        )

        # Option for modifying the columns that show up in the list view by default:
        default_columns = (
            "pk",
            "name",
            "ptrdname",
            "zone",
            "comment",
            "ttl",
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
            "actions",
            "source_object",
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
            "actions",
        )


class DNSRuleTable(BaseTable):
    """Table for DNS Rule list view."""

    pk = ToggleColumn()
    name = tables.LinkColumn()
    enabled = BooleanColumn()
    content_type = tables.Column()
    location = tables.LinkColumn()
    tenant = TenantColumn()
    record_type = tables.Column()
    failure_state_count = LinkedCountBadgeColumn(
        viewname="plugins:nautobot_dns_models:dnsrulefailurestate_list",
        url_params={"rule": "pk"},
        verbose_name="Failures",
    )
    actions = ButtonsColumn(models.DNSRule)

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSRule
        fields = (
            "pk",
            "name",
            "description",
            "enabled",
            "content_type",
            "location",
            "tenant",
            "record_type",
            "failure_state_count",
            "actions",
        )


class DNSRuleFailureStateTable(BaseTable):
    """Table for DNS rule failure-state list view."""

    pk = ToggleColumn()
    source_content_type = tables.Column(verbose_name="Source Type")
    source_object = tables.Column(verbose_name="Source Object", orderable=False)
    rule = tables.Column(linkify=True)
    candidate_record_type = tables.Column(verbose_name="Record Type")
    candidate_name = tables.Column(verbose_name="Candidate Name")
    last_seen = tables.DateTimeColumn()
    consecutive_failures = tables.Column(verbose_name="Consecutive")

    def render_source_object(self, value, record):
        """Render source object as a link when available."""
        if value is None:
            return str(record.source_object_id)

        source_url = getattr(value, "get_absolute_url", None)
        if callable(source_url):
            return format_html('<a href="{}">{}</a>', source_url(), value)

        return str(value)

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSRuleFailureState
        fields = (
            "pk",
            "source_content_type",
            "source_object_id",
            "source_object",
            "rule",
            "candidate_record_type",
            "candidate_name",
            "candidate_zone_id",
            "candidate_address_id",
            "attempt_count",
            "consecutive_failures",
            "last_seen",
        )
        default_columns = (
            "pk",
            "source_content_type",
            "source_object",
            "rule",
            "candidate_record_type",
            "candidate_name",
            "consecutive_failures",
            "last_seen",
        )
