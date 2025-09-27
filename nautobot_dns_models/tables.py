"""Tables for nautobot_dns_models."""

import django_tables2 as tables
from nautobot.apps.tables import BaseTable, ButtonsColumn, ToggleColumn

from nautobot_dns_models import models


class DNSRecordTable(BaseTable):  # pylint: disable=nb-no-model-found
    """Base table for DNS records list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    zone = tables.LinkColumn()
    ttl = tables.Column(accessor="ttl", verbose_name="TTL")


class DNSZoneTable(BaseTable):
    """Table for DNS Zone list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    actions = ButtonsColumn(
        models.DNSZone,
        # Option for modifying the default action buttons on each row:
        # buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
        # pk_field="pk",
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSZone
        fields = (
            "pk",
            "name",
            "ttl",
            "filename",
            "description",
            "soa_expire",
            "soa_rname",
            "soa_refresh",
            "soa_retry",
            "soa_serial",
            "soa_minimum",
        )

        default_columns = (
            "pk",
            "name",
            "ttl",
            "filename",
            "soa_expire",
            "soa_rname",
        )


class NSRecordTable(DNSRecordTable):
    """Table for list view."""

    actions = ButtonsColumn(
        models.NSRecord,
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the default action buttons on each row:
        # buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
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
        # Option for modifying the default action buttons on each row:
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
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


class AAAARecordTable(DNSRecordTable):
    """Table for list view."""

    address = tables.LinkColumn()
    actions = ButtonsColumn(
        models.AAAARecord,
        # Option for modifying the default action buttons on each row:
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
    )

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
        # Option for modifying the default action buttons on each row:
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
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
        # Option for modifying the default action buttons on each row:
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
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
        # Option for modifying the default action buttons on each row:
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
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
        # Option for modifying the default action buttons on each row:
        buttons=("changelog", "edit", "delete"),
        # Option for modifying the pk for the action buttons:
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


# =============================================================================
# GUI Rule Builder Tables
# =============================================================================


class DNSRuleTable(BaseTable):
    """Table for DNS Rule list view."""

    pk = ToggleColumn()
    name = tables.Column(linkify=True)
    content_type = tables.Column(verbose_name="Applies To")
    record_type = tables.Column(verbose_name="Creates")
    enabled = tables.BooleanColumn()
    zone_source = tables.Column(verbose_name="Zone Source")
    actions = ButtonsColumn(
        models.DNSRule,
        buttons=("changelog", "edit", "delete"),
    )

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSRule
        fields = (
            "pk",
            "name",
            "description",
            "enabled",
            "content_type",
            "record_type",
            "zone_source",
            "actions",
        )


class DNSRuleRecordTable(BaseTable):
    """Table for DNS Rule Record tracking list view (read-only)."""

    pk = ToggleColumn()
    rule = tables.LinkColumn()
    source_object_name = tables.Column(verbose_name="Source Object")
    dns_record_name = tables.Column(verbose_name="Generated DNS Record")
    created = tables.DateTimeColumn()
    # No actions column - these are read-only tracking records

    class Meta(BaseTable.Meta):
        """Meta attributes."""

        model = models.DNSRuleRecord
        fields = (
            "pk",
            "rule",
            "source_object_name",
            "dns_record_name",
            "created",
        )


class DNSRuleComponentTable(BaseTable):
    """Table for displaying DNS rule components."""
    
    pk = ToggleColumn()
    
    order = tables.Column(
        verbose_name="Order",
        orderable=False
    )
    
    target_field = tables.Column(
        verbose_name="Target Field",
        orderable=False
    )
    
    component_type = tables.Column(
        verbose_name="Component Type",
        accessor="get_component_type_display",
        orderable=False
    )
    
    value = tables.Column(
        verbose_name="Value",
        orderable=False
    )
    
    transform_function = tables.Column(
        verbose_name="Transform",
        accessor="get_transform_display_name",
        default="-",
        orderable=False
    )

    class Meta(BaseTable.Meta):
        """Table metadata."""
        
        model = models.DNSRuleComponent
        fields = (
            "pk",
            "order",
            "target_field", 
            "component_type",
            "value",
            "transform_function",
        )
        default_columns = [
            "order",
            "target_field", 
            "component_type",
            "value",
            "transform_function",
        ]
        # Components should always be displayed in order, not user-sortable
        orderable = False
