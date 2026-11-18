import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.db import connection, connections
from rest_framework.test import APIClient, APITransactionTestCase

from .models import Call, Company, Manager, Meeting


class SQLiteWriteTests(APITransactionTestCase):
    now = datetime(2026, 11, 18, 5, tzinfo=UTC)

    def setUp(self):
        self.database = Path(connection.settings_dict["NAME"])
        self.assertTrue(self.database.is_file())
        self.assertNotEqual(self.database.name, "db.sqlite3")
        self.company = Company.objects.create(name="First company", bin="000000000001")

    def assert_parallel_conflict(self, first, second, conflict_message):
        start = Barrier(2)

        def post(payload):
            db = connections["default"]
            try:
                db.ensure_connection()
                sqlite_connection = db.connection
                start.wait(timeout=10)
                response = APIClient().post("/meetings", payload, format="json")
                return sqlite_connection, response
            finally:
                db.close()

        with patch("django.utils.timezone.now", return_value=self.now):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(post, payload) for payload in (first, second)]
                first_result, second_result = (future.result(timeout=15) for future in futures)

        self.assertIsNot(first_result[0], second_result[0])
        created, rejected = sorted(
            (first_result[1], second_result[1]), key=lambda response: response.status_code,
        )
        self.assertEqual((created.status_code, rejected.status_code), (201, 409))
        self.assertEqual(rejected.json()["detail"], conflict_message)
        self.assertEqual(list(Meeting.objects.values_list("id", flat=True)), [created.json()["id"]])

    def test_parallel_requests_cannot_book_same_manager_slot(self):
        other = Company.objects.create(name="Second company", bin="000000000002")
        manager = Manager.objects.create(name="Manager")
        slot = {"manager_id": manager.pk, "starts_at": "2026-11-20T05:00:00Z"}

        self.assert_parallel_conflict(
            {**slot, "company_id": self.company.pk},
            {**slot, "company_id": other.pk},
            "The manager already has a meeting in this time slot.",
        )

    def test_parallel_requests_cannot_book_two_active_meetings_for_one_company(self):
        first = Manager.objects.create(name="First manager")
        second = Manager.objects.create(name="Second manager")

        self.assert_parallel_conflict(
            {"company_id": self.company.pk, "manager_id": first.pk, "starts_at": "2026-11-20T05:00:00Z"},
            {"company_id": self.company.pk, "manager_id": second.pk, "starts_at": "2026-11-23T05:00:00Z"},
            "The company already has an active meeting.",
        )

    def test_locked_database_returns_503_without_creating_calls_or_companies(self):
        payload = {"name": "New company", "bin": "000000000002", "phone": "+7 700 000 00 02"}
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA busy_timeout")
            original_timeout = cursor.fetchone()[0]
            cursor.execute("PRAGMA busy_timeout = 25")

        try:
            for mode in ("IMMEDIATE", "EXCLUSIVE"):
                with self.subTest(mode=mode), closing(sqlite3.connect(self.database)) as writer:
                    writer.execute(f"BEGIN {mode}")
                    call = self.client.post(
                        "/calls", {"company_id": self.company.pk, "result": "no_answer"}, format="json",
                    )
                    self.assertEqual(call.status_code, 503)
                    company = self.client.post("/companies", payload, format="json")
                    self.assertEqual(company.status_code, 503)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"PRAGMA busy_timeout = {original_timeout}")

        self.assertFalse(Call.objects.exists())
        self.assertEqual(Company.objects.count(), 1)
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, Company.Status.NEW)
