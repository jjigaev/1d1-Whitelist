from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.db import OperationalError, connection
from rest_framework.test import APITestCase

from .models import Call, Company, Manager, Meeting


class CallTests(APITestCase):
    now = datetime(2026, 11, 18, 5, tzinfo=UTC)

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="First company", bin="000000000001")
        cls.other_company = Company.objects.create(name="Second company", bin="000000000002")
        cls.manager = Manager.objects.create(name="First manager")

    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def make_meeting(self, company, starts_at, status=Meeting.Status.SCHEDULED):
        return Meeting.objects.create(
            company=company,
            manager=self.manager,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            original_starts_at=starts_at,
            status=status,
        )

    def post_call(self, **fields):
        return self.client.post(
            "/calls", {"company_id": self.company.pk, "result": "meeting_set", **fields}, format="json",
        )

    def test_meeting_set_links_own_active_meeting_and_updates_company(self):
        meeting = self.make_meeting(self.company, self.now + timedelta(days=1))
        response = self.post_call(meeting_id=meeting.pk)

        self.assertEqual(response.status_code, 201)
        call = Call.objects.get(pk=response.json()["id"])
        self.assertEqual(call.meeting_id, meeting.pk)
        self.assertEqual(response.json(), {
            "id": call.pk,
            "company_id": self.company.pk,
            "result": "meeting_set",
            "meeting_id": meeting.pk,
            "created_at": "2026-11-18T05:00:00Z",
        })
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, Company.Status.MEETING_SET)

    def test_invalid_meeting_references_do_not_create_call_or_change_status(self):
        future = self.now + timedelta(days=1)
        foreign_meeting = self.make_meeting(self.other_company, future)
        cancelled = self.make_meeting(self.company, future, Meeting.Status.CANCELLED)
        ended = self.make_meeting(self.company, self.now - timedelta(hours=1))

        for fields in (
            {}, {"meeting_id": None}, {"meeting_id": 9999},
            {"meeting_id": foreign_meeting.pk}, {"meeting_id": cancelled.pk}, {"meeting_id": ended.pk},
        ):
            with self.subTest(fields=fields):
                response = self.post_call(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn("meeting_id", response.json())
                self.assertFalse(Call.objects.exists())
                self.company.refresh_from_db()
                self.assertEqual(self.company.status, Company.Status.NEW)

    def test_other_results_accept_missing_or_null_meeting_and_latest_result_sets_status(self):
        first = self.post_call(result="no_answer")
        second = self.post_call(result="refused", meeting_id=None)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(list(Call.objects.order_by("id").values_list("result", "meeting_id")), [
            ("no_answer", None), ("refused", None),
        ])
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, Company.Status.REFUSED)

    def test_other_results_reject_meeting_reference(self):
        meeting = self.make_meeting(self.company, self.now + timedelta(days=1))
        for result in ("no_answer", "refused"):
            with self.subTest(result=result):
                response = self.post_call(result=result, meeting_id=meeting.pk)
                self.assertEqual(response.status_code, 400)
                self.assertIn("meeting_id", response.json())
        self.assertFalse(Call.objects.exists())
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, Company.Status.NEW)

    def test_unknown_company_returns_not_found(self):
        response = self.post_call(company_id=9999, result="no_answer")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Call.objects.exists())

    def test_failed_company_update_rolls_back_call_insert(self):
        def fail_company_update(execute, sql, params, many, context):
            if sql.startswith('UPDATE "crm_company"'):
                raise OperationalError("Simulated company update failure")
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_company_update), self.assertRaises(OperationalError):
            self.post_call(result="no_answer")

        self.assertFalse(Call.objects.exists())
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, Company.Status.NEW)
