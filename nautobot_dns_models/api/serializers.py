"""API serializers for nautobot_dns_models."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from drf_spectacular.utils import extend_schema_field
from nautobot.apps.api import ContentTypeField, NautobotModelSerializer, ValidatedModelSerializer
from rest_framework import serializers

from nautobot_dns_models import models


class DNSZoneSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """DNSZone Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnszone-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSZone
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class DNSRecordSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """DNSRecord Serializer."""

    ttl = serializers.SerializerMethodField(read_only=True)
    _ttl = serializers.IntegerField(
        required=False, allow_null=True, min_value=300, max_value=2147483647, help_text="Record-specific TTL."
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSRecord
        fields = "__all__"

    @extend_schema_field(serializers.IntegerField)
    def get_ttl(self, instance):
        """Expose TTL property."""
        return instance.ttl

    def validate(self, attrs):
        """Map "ttl" in the payload to "_ttl"."""
        if "ttl" in self.initial_data:
            attrs["_ttl"] = self.initial_data["ttl"]
        return super().validate(attrs)


class NSRecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """NSRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:nsrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.NSRecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class ARecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """ARecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:arecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.ARecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class AAAARecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """AAAARecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:aaaarecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.AAAARecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class CNAMERecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """CNAMERecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:cnamerecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.CNAMERecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class MXRecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """MXRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:mxrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.MXRecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class TXTRecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """TXTRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:txtrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.TXTRecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class PTRRecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """PTRRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:ptrrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.PTRRecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class SRVRecordSerializer(DNSRecordSerializer):  # pylint: disable=too-many-ancestors
    """SRVRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:srvrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.SRVRecord
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class DNSRuleSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """DNSRule Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnsrule-detail")
    content_type = ContentTypeField(
        queryset=ContentType.objects.filter(
            Q(app_label="dcim", model__in=["device", "interface"])
            | Q(app_label="virtualization", model__in=["virtualmachine", "vminterface"])
            | Q(app_label="extras", model="service")
        ).order_by("app_label", "model")
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSRule
        fields = "__all__"

    def to_internal_value(self, data):
        """Ensure enabled field is present for constraint validation during partial updates."""
        if "enabled" not in data and self.partial:
            data["enabled"] = self.instance.enabled

        return super().to_internal_value(data)


class DNSRuleRecordSerializer(ValidatedModelSerializer):
    """DNSRuleRecord Serializer - Following BaseModel pattern like ComputedField."""

    content_type = ContentTypeField(
        queryset=ContentType.objects.filter(
            Q(app_label="dcim", model__in=["device", "interface"])
            | Q(app_label="virtualization", model__in=["virtualmachine", "vminterface"])
            | Q(app_label="extras", model="service")
        ).order_by("app_label", "model")
    )
    dns_record_content_type = ContentTypeField(
        queryset=ContentType.objects.filter(
            app_label="nautobot_dns_models",
            model__in=[
                "arecord",
                "aaaarecord",
                "cnamerecord",
                "mxrecord",
                "nsrecord",
                "ptrrecord",
                "srvrecord",
                "txtrecord",
            ],
        ).order_by("model")
    )

    class Meta:
        """Meta attributes."""

        model = models.DNSRuleRecord
        fields = "__all__"
