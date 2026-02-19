"""API serializers for nautobot_dns_models."""

from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import extend_schema_field
from nautobot.apps.api import ContentTypeField, NautobotModelSerializer, ValidatedModelSerializer
from rest_framework import serializers

from nautobot_dns_models import models
from nautobot_dns_models.queries import DNSRuleContentTypeQuery


class DNSViewSerializer(NautobotModelSerializer):
    """DNSView Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnsview-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSView
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class DNSViewPrefixAssignmentSerializer(ValidatedModelSerializer):
    """DNSViewPrefixAssignment Serializer."""

    class Meta:
        """Meta attributes."""

        model = models.DNSViewPrefixAssignment
        fields = "__all__"


class DNSZoneSerializer(NautobotModelSerializer):
    """DNSZone Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnszone-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSZone
        fields = "__all__"


class DNSRecordSerializer(NautobotModelSerializer):
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


class NSRecordSerializer(DNSRecordSerializer):
    """NSRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:nsrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.NSRecord
        fields = "__all__"


class ARecordSerializer(DNSRecordSerializer):
    """ARecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:arecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.ARecord
        fields = "__all__"


class AAAARecordSerializer(DNSRecordSerializer):
    """AAAARecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:aaaarecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.AAAARecord
        fields = "__all__"


class CNAMERecordSerializer(DNSRecordSerializer):
    """CNAMERecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:cnamerecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.CNAMERecord
        fields = "__all__"


class MXRecordSerializer(DNSRecordSerializer):
    """MXRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:mxrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.MXRecord
        fields = "__all__"


class TXTRecordSerializer(DNSRecordSerializer):
    """TXTRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:txtrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.TXTRecord
        fields = "__all__"


class PTRRecordSerializer(DNSRecordSerializer):
    """PTRRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:ptrrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.PTRRecord
        fields = "__all__"


class SRVRecordSerializer(DNSRecordSerializer):
    """SRVRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:srvrecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.SRVRecord
        fields = "__all__"


class DNSRuleSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """DNSRule Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnsrule-detail")
    content_type = ContentTypeField(queryset=DNSRuleContentTypeQuery.as_queryset())

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

    content_type = ContentTypeField(queryset=DNSRuleContentTypeQuery.as_queryset())
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
