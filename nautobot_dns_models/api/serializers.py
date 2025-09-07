"""API serializers for nautobot_dns_models."""

from nautobot.apps.api import NautobotModelSerializer
from rest_framework import serializers

from nautobot_dns_models import models


class DNSZoneModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """DnsZoneModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnszonemodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSZoneModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class NSRecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """NSRecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:nsrecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.NSRecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class ARecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """ARecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:arecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.ARecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class AAAARecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """AAAARecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:aaaarecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.AAAARecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class CNAMERecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """CNAMERecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:cnamerecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.CNAMERecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class MXRecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """MXRecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:mxrecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.MXRecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class TXTRecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """TXTRecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:txtrecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.TXTRecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class PTRRecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """PTRRecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:ptrrecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.PTRRecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


class SRVRecordModelSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """SRVRecordModel Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:srvrecordmodel-detail")

    class Meta:
        """Meta attributes."""

        model = models.SRVRecordModel
        fields = "__all__"

        # Option for disabling write for certain fields:
        # read_only_fields = []


# =============================================================================
# GUI Rule Builder Serializers
# =============================================================================

class DNSRuleSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """DNSRule Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnsrule-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSRule
        fields = "__all__"


class DNSRuleRecordSerializer(NautobotModelSerializer):  # pylint: disable=too-many-ancestors
    """DNSRuleRecord Serializer."""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:nautobot_dns_models-api:dnsrulerecord-detail")

    class Meta:
        """Meta attributes."""

        model = models.DNSRuleRecord
        fields = "__all__"
