from django.core.validators import RegexValidator
from django.db import models


class Company(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        NO_ANSWER = "no_answer", "No answer"
        REFUSED = "refused", "Refused"
        MEETING_SET = "meeting_set", "Meeting set"

    name = models.CharField(max_length=255)
    bin = models.CharField(
        max_length=12,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"\A[0-9]{12}\Z",
                message="BIN must contain exactly 12 ASCII digits.",
            ),
        ],
    )
    phone = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    created_at = models.DateTimeField(auto_now_add=True)


class Manager(models.Model):
    name = models.CharField(max_length=255)


class Meeting(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CANCELLED = "cancelled", "Cancelled"

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="meetings",
    )
    manager = models.ForeignKey(
        Manager,
        on_delete=models.PROTECT,
        related_name="meetings",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    original_starts_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="meeting_ends_after_start",
            ),
        ]


class Call(models.Model):
    class Result(models.TextChoices):
        NO_ANSWER = "no_answer", "No answer"
        REFUSED = "refused", "Refused"
        MEETING_SET = "meeting_set", "Meeting set"

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="calls",
    )
    result = models.CharField(max_length=20, choices=Result.choices)
    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.PROTECT,
        related_name="calls",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
