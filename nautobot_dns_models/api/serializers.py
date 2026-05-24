"""API serializers for nautobot_dns_models."""

from drf_spectacular.utils import extend_schema_field
from nautobot.apps.api import NautobotModelSerializer, ValidatedModelSerializer
from nautobot.tenancy.models import Tenant
from rest_framework import serializers

from nautobot_dns_models import models


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


class DNSRegistrarSerializer(NautobotModelSerializer):
    """DNSRegistrar Serializer."""

    class Meta:
        """Meta attributes."""

        model = models.DNSRegistrar
        fields = "__all__"


class DNSRegistrationSerializer(NautobotModelSerializer):
    """DNSRegistration Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnsregistration-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSRegistration
        fields = "__all__"


class DNSZoneSerializer(NautobotModelSerializer):
    """DNSZone Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnszone-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSZone
        fields = "__all__"


class CatalogZoneSerializer(NautobotModelSerializer):
    """CatalogZone Serializer."""

    id = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:catalogzone-detail")
    name = serializers.CharField()
    filename = serializers.CharField()
    dns_view = serializers.PrimaryKeyRelatedField(queryset=models.DNSView.objects.all())
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.all(), required=False, allow_null=True)
    soa_refresh = serializers.IntegerField(min_value=300, max_value=2147483647)
    soa_retry = serializers.IntegerField(min_value=300, max_value=2147483647)
    soa_expire = serializers.IntegerField(min_value=300, max_value=2147483647)
    soa_minimum = serializers.IntegerField(min_value=300, max_value=2147483647)
    # These API inputs represent backing DNSZone attributes, not concrete writable fields on
    # CatalogZone itself. validate() removes them from attrs and stores them under
    # "_wrapper_payload" so NautobotModelSerializer doesn't try model-level assignment/validation
    # against CatalogZone proxy properties (for example "name"). create() and update() then
    # consume that payload via CatalogZone orchestration methods to write the backing DNSZone.
    _wrapper_payload_fields = (
        "name",
        "filename",
        "dns_view",
        "tenant",
        "soa_refresh",
        "soa_retry",
        "soa_expire",
        "soa_minimum",
        "description",
    )

    class Meta:
        """Meta attributes."""

        model = models.CatalogZone
        exclude = ("dns_zone",)
        read_only_fields = ("created", "last_updated")

    def validate(self, attrs):
        """Capture curated payload and remove proxy attrs before model validation."""
        wrapper_payload = {}
        for field_name in self._wrapper_payload_fields:
            if field_name in attrs:
                wrapper_payload[field_name] = attrs.pop(field_name)

        attrs["_wrapper_payload"] = wrapper_payload
        return attrs

    def create(self, validated_data):
        """Create wrapper + backing DNS zone from curated payload."""
        payload = validated_data.pop("_wrapper_payload", {})
        if validated_data.get("id"):
            payload["id"] = validated_data.pop("id")
        return models.CatalogZone.create_with_backing_zone_payload(**payload)

    def update(self, instance, validated_data):
        """Update curated backing DNS zone payload through wrapper model."""
        payload = validated_data.pop("_wrapper_payload", {})
        instance.update_backing_zone_payload(
            name=payload.get("name", instance.name),
            filename=payload.get("filename", instance.dns_zone.filename),
            dns_view=payload.get("dns_view", instance.dns_view),
            tenant=payload.get("tenant", instance.tenant),
            soa_refresh=payload.get("soa_refresh", instance.soa_refresh),
            soa_retry=payload.get("soa_retry", instance.soa_retry),
            soa_expire=payload.get("soa_expire", instance.soa_expire),
            soa_minimum=payload.get("soa_minimum", instance.soa_minimum),
            description=payload.get("description", instance.description),
        )
        return instance


class CatalogZoneMembershipSerializer(NautobotModelSerializer):
    """CatalogZoneMembership Serializer."""

    class Meta:
        """Meta attributes."""

        model = models.CatalogZoneMembership
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
