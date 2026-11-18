from datetime import UTC, date, datetime, time, timedelta

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import Company, Manager, Meeting
from .serializers import CallSerializer, CompanySerializer, MeetingSerializer, MeetingUpdateSerializer
from .services import ALMATY, create_company, create_meeting, register_call, update_meeting


@api_view(["POST"])
def post_meeting(request):
    serializer = MeetingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    meeting = create_meeting(**serializer.validated_data)
    return Response(MeetingSerializer(meeting).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
def patch_meeting(request, meeting_id):
    serializer = MeetingUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    meeting = update_meeting(meeting_id=meeting_id, **serializer.validated_data)
    return Response(MeetingSerializer(meeting).data)


@api_view(["POST", "GET"])
def companies(request):
    if request.method == "POST":
        serializer = CompanySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = create_company(**serializer.validated_data)
        return Response(CompanySerializer(company).data, status=status.HTTP_201_CREATED)

    queryset = Company.objects.order_by("id")
    company_status = request.query_params.get("status")
    if company_status is not None:
        if company_status not in Company.Status.values:
            raise ValidationError({"status": ["Choose a valid company status."]})
        queryset = queryset.filter(status=company_status)

    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(CompanySerializer(page, many=True).data)


@api_view(["POST"])
def post_call(request):
    serializer = CallSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    call = register_call(**serializer.validated_data)
    return Response(CallSerializer(call).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def manager_schedule(request, manager_id):
    date_value = request.query_params.get("date", "")
    try:
        day = date.fromisoformat(date_value)
        if day.isoformat() != date_value:
            raise ValueError
        next_day = day + timedelta(days=1)
        starts_at = datetime.combine(day, time.min, tzinfo=ALMATY).astimezone(UTC)
        ends_at = datetime.combine(next_day, time.min, tzinfo=ALMATY).astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValidationError({"date": ["Use a valid date in YYYY-MM-DD format."]}) from exc

    if not Manager.objects.filter(pk=manager_id).exists():
        raise NotFound("Manager not found.")

    meetings = (
        Meeting.objects.filter(manager_id=manager_id, starts_at__gte=starts_at, starts_at__lt=ends_at)
        .exclude(status=Meeting.Status.CANCELLED)
        .order_by("starts_at", "id")
    )
    return Response(MeetingSerializer(meetings, many=True).data)
