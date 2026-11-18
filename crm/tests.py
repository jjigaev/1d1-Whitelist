import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.db import OperationalError, connection
from rest_framework.test import APITestCase

from .models import Call, Company, Manager, Meeting


class CreateMeetingTests(APITestCase):
    now = datetime(2026, 11, 18, 5, tzinfo=UTC)

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="First company", bin="000000000001", phone="+7 700 000 00 01",
        )
        cls.other_company = Company.objects.create(
            name="Second company", bin="000000000002", phone="+7 700 000 00 02",
        )
        cls.manager = Manager.objects.create(name="First manager")
        cls.other_manager = Manager.objects.create(name="Second manager")

    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def post_meeting(self, starts_at="2026-11-20T05:00:00Z", **fields):
        return self.client.post(
            "/meetings",
            {
                "company_id": self.company.pk,
                "manager_id": self.manager.pk,
                "starts_at": starts_at,
                **fields,
            },
            format="json",
        )

    def test_creates_meeting_and_returns_server_fields_in_utc(self):
        response = self.post_meeting(
            "2026-11-20T05:00:00+00:00",
            ends_at="2026-11-21T06:00:00Z",
            original_starts_at="2026-11-19T05:00:00Z",
            status="cancelled",
            created_at="2026-11-01T05:00:00Z",
        )

        self.assertEqual(response.status_code, 201)
        meeting = Meeting.objects.get()
        self.assertEqual(response.json(), {
            "id": meeting.pk,
            "company_id": self.company.pk,
            "manager_id": self.manager.pk,
            "starts_at": "2026-11-20T05:00:00Z",
            "ends_at": "2026-11-20T06:00:00Z",
            "original_starts_at": "2026-11-20T05:00:00Z",
            "status": "scheduled",
            "created_at": "2026-11-18T05:00:00Z",
        })
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, Company.Status.NEW)
        self.assertFalse(Call.objects.exists())

    def test_first_and_last_working_slots_are_allowed(self):
        for starts_at, company in (
            ("2026-11-20T04:00:00Z", self.company),  # 09:00 in Almaty
            ("2026-11-20T12:00:00Z", self.other_company),  # 17:00 in Almaty
        ):
            with self.subTest(starts_at=starts_at):
                self.assertEqual(self.post_meeting(starts_at, company_id=company.pk).status_code, 201)

    def test_entire_meeting_must_fit_in_working_hours(self):
        for starts_at in ("2026-11-20T03:59:00Z", "2026-11-20T12:30:00Z"):
            with self.subTest(starts_at=starts_at):
                response = self.post_meeting(starts_at)
                self.assertEqual(response.status_code, 400)
                self.assertIn("starts_at", response.json())
        self.assertFalse(Meeting.objects.exists())

    def test_weekend_and_working_hours_use_the_almaty_calendar_date(self):
        for starts_at, error_text in (
            ("2026-11-21T05:00:00Z", "Monday to Friday"),  # Saturday 10:00 local
            ("2026-11-20T20:00:00Z", "Monday to Friday"),  # Friday UTC, Saturday local
            ("2026-11-22T23:00:00Z", "09:00"),  # Sunday UTC, Monday 04:00 local
        ):
            with self.subTest(starts_at=starts_at):
                response = self.post_meeting(starts_at)
                self.assertEqual(response.status_code, 400)
                self.assertIn(error_text, response.json()["starts_at"][0])
        self.assertFalse(Meeting.objects.exists())

    def test_start_must_be_in_the_future_and_explicitly_utc(self):
        for starts_at in (
            "2026-11-17T05:00:00Z",
            "2026-11-18T05:00:00Z",  # Exactly now, within working hours
            "2026-11-20T05:00:00",
            "2026-11-20T11:00:00+06:00",  # Would be valid if normalized before validation
            "2026-11-20+00:00",  # Suffix alone does not make this an aware datetime
            "2026-02-30T05:00:00Z",
            "9999-12-31T23:59:00Z",
        ):
            with self.subTest(starts_at=starts_at):
                response = self.post_meeting(starts_at)
                self.assertEqual(response.status_code, 400)
                self.assertIn("starts_at", response.json())
        self.assertFalse(Meeting.objects.exists())

    def test_input_fields_are_required_and_ids_must_be_positive(self):
        response = self.client.post("/meetings", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"company_id", "manager_id", "starts_at"})

        response = self.post_meeting(company_id=0, manager_id="invalid")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"company_id", "manager_id"})

    def test_missing_company_or_manager_returns_not_found(self):
        for field in ("company_id", "manager_id"):
            with self.subTest(field=field):
                response = self.post_meeting(**{field: 9999})
                self.assertEqual(response.status_code, 404)
                self.assertIn("detail", response.json())
        self.assertFalse(Meeting.objects.exists())

    def test_manager_cannot_have_overlapping_meetings(self):
        self.assertEqual(self.post_meeting().status_code, 201)

        for starts_at in ("2026-11-20T04:30:00Z", "2026-11-20T05:30:00Z"):
            with self.subTest(starts_at=starts_at):
                response = self.post_meeting(starts_at, company_id=self.other_company.pk)
                self.assertEqual(response.status_code, 409)
                self.assertIn("detail", response.json())
                self.assertEqual(Meeting.objects.count(), 1)

    def test_adjacent_meetings_for_the_same_manager_are_allowed(self):
        self.assertEqual(self.post_meeting().status_code, 201)
        response = self.post_meeting("2026-11-20T06:00:00Z", company_id=self.other_company.pk)
        self.assertEqual(response.status_code, 201)

    def test_company_cannot_have_another_active_meeting(self):
        self.assertEqual(self.post_meeting().status_code, 201)
        response = self.post_meeting("2026-11-23T05:00:00Z", manager_id=self.other_manager.pk)

        self.assertEqual(response.status_code, 409)
        self.assertIn("detail", response.json())
        self.assertEqual(Meeting.objects.count(), 1)

    def test_cancelled_meeting_for_same_company_and_manager_does_not_block_slot(self):
        starts_at = datetime(2026, 11, 20, 5, tzinfo=UTC)
        Meeting.objects.create(
            company=self.company,
            manager=self.manager,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            original_starts_at=starts_at,
            status=Meeting.Status.CANCELLED,
        )

        self.assertEqual(self.post_meeting().status_code, 201)
        self.assertEqual(Meeting.objects.count(), 2)

    def test_meeting_ending_at_now_does_not_block_company(self):
        starts_at = self.now - timedelta(hours=1)
        Meeting.objects.create(
            company=self.company,
            manager=self.manager,
            starts_at=starts_at,
            ends_at=self.now,
            original_starts_at=starts_at,
        )

        self.assertEqual(self.post_meeting().status_code, 201)
        self.assertEqual(Meeting.objects.count(), 2)

    def test_different_companies_and_managers_can_share_a_time(self):
        self.assertEqual(self.post_meeting().status_code, 201)
        response = self.post_meeting(company_id=self.other_company.pk, manager_id=self.other_manager.pk)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Meeting.objects.count(), 2)

    def test_only_sqlite_lock_errors_return_service_unavailable(self):
        def fail_meeting_insert(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "crm_meeting"'):
                error = sqlite3.OperationalError("Simulated SQLite error")
                error.sqlite_errorcode = error_code
                raise OperationalError(str(error)) from error
            return execute(sql, params, many, context)

        for error_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED_SHAREDCACHE, sqlite3.SQLITE_ERROR):
            with self.subTest(error_code=error_code), connection.execute_wrapper(fail_meeting_insert):
                if error_code == sqlite3.SQLITE_ERROR:
                    with self.assertRaises(OperationalError):
                        self.post_meeting()
                else:
                    response = self.post_meeting()
                    self.assertEqual(response.status_code, 503)
                    self.assertIn("detail", response.json())

        self.assertFalse(Meeting.objects.exists())
        self.assertEqual(self.post_meeting().status_code, 201)
