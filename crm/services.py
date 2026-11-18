import sqlite3
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, ValidationError

from .models import Call, Company, Manager, Meeting

ALMATY = ZoneInfo("Asia/Almaty")


class MeetingConflict(APIException):
    status_code = status.HTTP_409_CONFLICT


class DatabaseBusy(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The database is busy. Please retry shortly."


def is_sqlite_lock_error(error):
    cause = error.__cause__
    if not isinstance(cause, sqlite3.OperationalError):
        return False
    # The low byte of an extended SQLite result code is the primary code.
    primary_code = getattr(cause, "sqlite_errorcode", 0) & 0xFF
    return primary_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def validate_meeting_time(starts_at, now):
    if starts_at <= now:
        raise ValidationError({"starts_at": ["The start must be in the future."]})

    try:
        ends_at = starts_at + timedelta(hours=1)
        local_start = starts_at.astimezone(ALMATY)
        local_end = ends_at.astimezone(ALMATY)
    except OverflowError as exc:
        raise ValidationError({
            "starts_at": ["The start is outside the supported date range."],
        }) from exc

    if local_start.weekday() >= 5:
        raise ValidationError({"starts_at": ["Choose a day from Monday to Friday in Asia/Almaty."]})

    if (
        local_start.date() != local_end.date()
        or local_start.time() < time(9)
        or local_end.time() > time(18)
    ):
        raise ValidationError({"starts_at": ["The meeting must fit within 09:00–18:00 in Asia/Almaty."]})

    return ends_at


def check_meeting_availability(
    *, company_id, manager_id, starts_at, ends_at, now, exclude_meeting_id=None,
):
    meetings = Meeting.objects.all()
    if exclude_meeting_id is not None:
        meetings = meetings.exclude(pk=exclude_meeting_id)

    overlapping = meetings.filter(
        manager_id=manager_id,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exclude(status=Meeting.Status.CANCELLED)
    if overlapping.exists():
        raise MeetingConflict("The manager already has a meeting in this time slot.")

    active_for_company = meetings.filter(
        company_id=company_id,
        status=Meeting.Status.SCHEDULED,
        ends_at__gt=now,
    )
    if active_for_company.exists():
        raise MeetingConflict("The company already has an active meeting.")


def create_meeting(*, company_id, manager_id, starts_at):
    try:
        with transaction.atomic():
            now = timezone.now()
            ends_at = validate_meeting_time(starts_at, now)
            if not Company.objects.filter(pk=company_id).exists():
                raise NotFound("Company not found.")
            if not Manager.objects.filter(pk=manager_id).exists():
                raise NotFound("Manager not found.")

            check_meeting_availability(
                company_id=company_id,
                manager_id=manager_id,
                starts_at=starts_at,
                ends_at=ends_at,
                now=now,
            )
            return Meeting.objects.create(
                company_id=company_id,
                manager_id=manager_id,
                starts_at=starts_at,
                ends_at=ends_at,
                original_starts_at=starts_at,
                status=Meeting.Status.SCHEDULED,
            )
    except OperationalError as exc:
        if is_sqlite_lock_error(exc):
            raise DatabaseBusy() from exc
        raise


def update_meeting(*, meeting_id, starts_at=None, status=None):
    try:
        with transaction.atomic():
            meeting = Meeting.objects.filter(pk=meeting_id).first()
            if meeting is None:
                raise NotFound("Meeting not found.")

            cancelling = status == Meeting.Status.CANCELLED
            if meeting.status == Meeting.Status.CANCELLED:
                if cancelling:
                    return meeting
                raise MeetingConflict("A cancelled meeting cannot be rescheduled.")

            now = timezone.now()
            if meeting.starts_at <= now:
                raise MeetingConflict("A meeting that has already started cannot be changed.")

            if cancelling:
                meeting.status = Meeting.Status.CANCELLED
                meeting.save(update_fields=["status"])
            else:
                ends_at = validate_meeting_time(starts_at, now)
                check_meeting_availability(
                    company_id=meeting.company_id,
                    manager_id=meeting.manager_id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    now=now,
                    exclude_meeting_id=meeting.pk,
                )
                meeting.starts_at = starts_at
                meeting.ends_at = ends_at
                meeting.save(update_fields=["starts_at", "ends_at"])

            return meeting
    except OperationalError as exc:
        if is_sqlite_lock_error(exc):
            raise DatabaseBusy() from exc
        raise


def create_company(*, name, bin, phone):
    try:
        with transaction.atomic():
            return Company.objects.create(name=name, bin=bin, phone=phone)
    except IntegrityError as exc:
        # Another request can insert the same BIN after serializer validation.
        cause = exc.__cause__
        if (
            isinstance(cause, sqlite3.IntegrityError)
            and getattr(cause, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
            and str(cause) == f"UNIQUE constraint failed: {Company._meta.db_table}.bin"
        ):
            raise ValidationError({"bin": ["A company with this BIN already exists."]}) from exc
        raise


def register_call(*, company_id, result, meeting_id=None):
    try:
        with transaction.atomic():
            company = Company.objects.filter(pk=company_id).first()
            if company is None:
                raise NotFound("Company not found.")

            if result == Call.Result.MEETING_SET:
                if meeting_id is None:
                    raise ValidationError({"meeting_id": ["This field is required for meeting_set."]})
                active_meeting = Meeting.objects.filter(
                    pk=meeting_id,
                    company_id=company_id,
                    status=Meeting.Status.SCHEDULED,
                    ends_at__gt=timezone.now(),
                )
                if not active_meeting.exists():
                    raise ValidationError({
                        "meeting_id": ["Choose an active meeting belonging to this company."],
                    })
            elif meeting_id is not None:
                raise ValidationError({"meeting_id": ["Provide a meeting only for meeting_set."]})

            call = Call.objects.create(company=company, result=result, meeting_id=meeting_id)
            company.status = result
            company.save(update_fields=["status"])
            return call
    except OperationalError as exc:
        if is_sqlite_lock_error(exc):
            raise DatabaseBusy() from exc
        raise
