from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from rest_framework.test import APITestCase

from .models import Company, Manager, Meeting


class ScheduleTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="First company", bin="000000000001")
        cls.manager = Manager.objects.create(name="First manager")
        cls.other_manager = Manager.objects.create(name="Second manager")

    def make_meeting(self, starts_at, *, manager=None, status=Meeting.Status.SCHEDULED):
        return Meeting.objects.create(
            company=self.company,
            manager=manager or self.manager,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            original_starts_at=starts_at,
            status=status,
        )

    def test_schedule_uses_local_day_orders_ties_and_keeps_finished_meetings(self):
        last = self.make_meeting(datetime(2026, 11, 20, 18, 59, tzinfo=UTC))
        first = self.make_meeting(datetime(2026, 11, 19, 19, tzinfo=UTC))
        second = self.make_meeting(first.starts_at)
        self.make_meeting(datetime(2026, 11, 19, 18, 59, tzinfo=UTC))
        self.make_meeting(datetime(2026, 11, 20, 19, tzinfo=UTC))
        self.make_meeting(first.starts_at, manager=self.other_manager)
        self.make_meeting(first.starts_at, status=Meeting.Status.CANCELLED)

        now = datetime(2026, 11, 20, 8, tzinfo=UTC)
        with patch("django.utils.timezone.now", return_value=now):
            response = self.client.get(f"/managers/{self.manager.pk}/schedule", {"date": "2026-11-20"})

        self.assertEqual(response.status_code, 200)
        meetings = response.json()
        self.assertEqual([meeting["id"] for meeting in meetings], [first.pk, second.pk, last.pk])
        self.assertEqual([meeting["starts_at"] for meeting in meetings], [
            "2026-11-19T19:00:00Z", "2026-11-19T19:00:00Z", "2026-11-20T18:59:00Z",
        ])
        self.assertEqual(meetings[0]["ends_at"], "2026-11-19T20:00:00Z")

    def test_manager_without_meetings_has_empty_schedule(self):
        response = self.client.get(f"/managers/{self.manager.pk}/schedule", {"date": "2026-11-20"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_invalid_or_missing_date_returns_bad_request(self):
        for params in (
            {}, {"date": ""}, {"date": "2026-2-01"}, {"date": "20261120"},
            {"date": "2026-02-30"}, {"date": "9999-12-31"},
        ):
            with self.subTest(params=params):
                response = self.client.get(f"/managers/{self.manager.pk}/schedule", params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("date", response.json())

    def test_unknown_manager_returns_not_found(self):
        response = self.client.get("/managers/9999/schedule", {"date": "2026-11-20"})
        self.assertEqual(response.status_code, 404)
