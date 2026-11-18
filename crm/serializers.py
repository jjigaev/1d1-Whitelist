from datetime import UTC, datetime

from rest_framework import serializers


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
