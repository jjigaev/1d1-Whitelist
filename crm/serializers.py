from datetime import UTC, datetime

from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Call, Company, Meeting


class UTCDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value):
        # Check the input before DRF can normalize its time zone.
        if (
            not isinstance(value, str)
            or "T" not in value
            or not value.endswith(("Z", "+00:00"))
        ):
            raise serializers.ValidationError("Use an ISO 8601 datetime with Z or +00:00.")

        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise serializers.ValidationError("Enter a valid ISO 8601 datetime.") from exc


class MeetingSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    company_id = serializers.IntegerField(min_value=1)
    manager_id = serializers.IntegerField(min_value=1)
    starts_at = UTCDateTimeField(default_timezone=UTC)
    ends_at = serializers.DateTimeField(read_only=True, default_timezone=UTC)
    original_starts_at = serializers.DateTimeField(read_only=True, default_timezone=UTC)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True, default_timezone=UTC)


class MeetingUpdateSerializer(serializers.Serializer):
    starts_at = UTCDateTimeField(required=False, default_timezone=UTC)
    status = serializers.ChoiceField(choices=[Meeting.Status.CANCELLED], required=False)

    def validate(self, attrs):
        if set(self.initial_data) not in ({"starts_at"}, {"status"}):
            raise serializers.ValidationError("Send either starts_at or status=cancelled by itself.")
        return attrs


class BinField(serializers.CharField):
    def to_internal_value(self, value):
        if not isinstance(value, str):
            raise serializers.ValidationError("BIN must be a string.")
        return super().to_internal_value(value)


class CompanySerializer(serializers.ModelSerializer):
    bin = BinField(
        trim_whitespace=False,
        validators=[
            *Company._meta.get_field("bin").validators,
            UniqueValidator(queryset=Company.objects.all()),
        ],
    )
    created_at = serializers.DateTimeField(read_only=True, default_timezone=UTC)

    class Meta:
        model = Company
        fields = ("id", "name", "bin", "phone", "status", "created_at")
        read_only_fields = ("id", "status")


class CallSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    company_id = serializers.IntegerField(min_value=1)
    result = serializers.ChoiceField(choices=Call.Result.choices)
    meeting_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True, default_timezone=UTC)
