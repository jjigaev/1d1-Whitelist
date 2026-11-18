from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from rest_framework.test import APITestCase

from .models import Call, Company, Manager, Meeting


class UpdateMeetingTests(APITestCase):
    now = datetime(2026, 11, 18, 5, tzinfo=UTC)

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="First company", bin="000000000001")
        cls.manager = Manager.objects.create(name="First manager")
        cls.meeting = cls.make_meeting(cls.company, datetime(2026, 11, 20, 5, tzinfo=UTC))

    @classmethod
    def make_meeting(cls, company, starts_at):
        return Meeting.objects.create(
            company=company,
            manager=cls.manager,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            original_starts_at=starts_at,
        )

    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.url = f"/meetings/{self.meeting.pk}"

    def test_rescheduling_preserves_original_start_and_creation_time(self):
        response = self.client.patch(
            self.url, {"starts_at": "2026-11-20T05:30:00+00:00"}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "id": self.meeting.pk,
            "company_id": self.company.pk,
            "manager_id": self.manager.pk,
            "starts_at": "2026-11-20T05:30:00Z",
            "ends_at": "2026-11-20T06:30:00Z",
            "original_starts_at": "2026-11-20T05:00:00Z",
            "status": "scheduled",
            "created_at": self.meeting.created_at.isoformat().replace("+00:00", "Z"),
        })
        updated = Meeting.objects.get(pk=self.meeting.pk)
        self.assertEqual(updated.starts_at, datetime(2026, 11, 20, 5, 30, tzinfo=UTC))
        self.assertEqual(updated.ends_at, datetime(2026, 11, 20, 6, 30, tzinfo=UTC))
        self.assertEqual(updated.original_starts_at, self.meeting.original_starts_at)
        self.assertEqual(updated.created_at, self.meeting.created_at)

    def test_conflict_leaves_old_slot_in_place(self):
        other = Company.objects.create(name="Other company", bin="000000000002")
        self.make_meeting(other, datetime(2026, 11, 20, 6, tzinfo=UTC))

        response = self.client.patch(
            self.url, {"starts_at": "2026-11-20T06:30:00Z"}, format="json",
        )

        self.assertEqual(response.status_code, 409)
        unchanged = Meeting.objects.get(pk=self.meeting.pk)
        self.assertEqual(unchanged.starts_at, self.meeting.starts_at)
        self.assertEqual(unchanged.ends_at, self.meeting.ends_at)

    def test_cancellation_releases_slot_and_preserves_call_history(self):
        self.company.status = Company.Status.MEETING_SET
        self.company.save(update_fields=["status"])
        call = Call.objects.create(company=self.company, result=Call.Result.MEETING_SET, meeting=self.meeting)

        response = self.client.patch(self.url, {"status": "cancelled"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(response.json()["id"], self.meeting.pk)
        self.company.refresh_from_db()
        call.refresh_from_db()
        self.assertEqual(self.company.status, Company.Status.MEETING_SET)
        self.assertEqual(call.meeting_id, self.meeting.pk)
        self.assertEqual(call.result, Call.Result.MEETING_SET)
        self.assertEqual(Call.objects.count(), 1)

        replacement = self.client.post("/meetings", {
            "company_id": self.company.pk,
            "manager_id": self.manager.pk,
            "starts_at": "2026-11-20T05:00:00Z",
        }, format="json")
        self.assertEqual(replacement.status_code, 201)
        self.assertNotEqual(replacement.json()["id"], self.meeting.pk)
        self.assertEqual(Meeting.objects.get(pk=self.meeting.pk).status, Meeting.Status.CANCELLED)

    def test_repeat_cancellation_succeeds_but_rescheduling_cancelled_meeting_conflicts(self):
        self.assertEqual(self.client.patch(self.url, {"status": "cancelled"}, format="json").status_code, 200)
        response = self.client.patch(self.url, {"starts_at": "2026-11-20T06:00:00Z"}, format="json")
        self.assertEqual(response.status_code, 409)

        with patch("django.utils.timezone.now", return_value=self.meeting.ends_at):
            response = self.client.patch(self.url, {"status": "cancelled"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

    def test_already_started_meeting_cannot_be_changed(self):
        with patch("django.utils.timezone.now", return_value=self.meeting.starts_at):
            for payload in ({"status": "cancelled"}, {"starts_at": "2026-11-20T07:00:00Z"}):
                with self.subTest(payload=payload):
                    self.assertEqual(self.client.patch(self.url, payload, format="json").status_code, 409)
        unchanged = Meeting.objects.get(pk=self.meeting.pk)
        self.assertEqual(unchanged.status, Meeting.Status.SCHEDULED)
        self.assertEqual(unchanged.starts_at, self.meeting.starts_at)

    def test_patch_requires_exactly_one_valid_action(self):
        starts_at = "2026-11-20T06:00:00Z"
        for payload in (
            {}, {"starts_at": starts_at, "status": "cancelled"},
            {"starts_at": starts_at, "manager_id": self.manager.pk},
            {"status": "cancelled", "company_id": self.company.pk},
            {"status": "scheduled"}, {"starts_at": "2026-11-20T06:00:00"},
            {"starts_at": "2026-11-20T12:00:00+06:00"}, {"starts_at": "2026-11-21T06:00:00Z"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch(self.url, payload, format="json").status_code, 400)
        unchanged = Meeting.objects.get(pk=self.meeting.pk)
        self.assertEqual(unchanged.status, Meeting.Status.SCHEDULED)
        self.assertEqual(unchanged.starts_at, self.meeting.starts_at)

    def test_unknown_meeting_returns_not_found(self):
        response = self.client.patch("/meetings/9999", {"status": "cancelled"}, format="json")
        self.assertEqual(response.status_code, 404)
