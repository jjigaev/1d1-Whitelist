from django.db import connection
from rest_framework.test import APITestCase

from .models import Company


class CompanyTests(APITestCase):
    company_data = {"name": "Example", "bin": "000000000001", "phone": "+7 700 000 00 01"}

    def test_creates_company_with_leading_zeros_and_new_status(self):
        response = self.client.post(
            "/companies", {**self.company_data, "status": "meeting_set"}, format="json",
        )

        self.assertEqual(response.status_code, 201)
        company = Company.objects.get(pk=response.json()["id"])
        self.assertEqual(company.bin, "000000000001")
        self.assertEqual(company.status, Company.Status.NEW)
        for field, value in {**self.company_data, "status": "new"}.items():
            with self.subTest(field=field):
                self.assertEqual(response.json()[field], value)

    def test_rejects_invalid_bin_without_coercing_numbers_or_trimming(self):
        for bin_value in (123456789012, "01234567890", "１２３４５６７８９０１２", " 000000000001 "):
            with self.subTest(bin_value=bin_value):
                response = self.client.post(
                    "/companies", {**self.company_data, "bin": bin_value}, format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("bin", response.json())
        self.assertFalse(Company.objects.exists())

    def test_duplicate_bin_returns_field_error(self):
        Company.objects.create(**self.company_data)
        response = self.client.post("/companies", self.company_data, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("bin", response.json())
        self.assertEqual(Company.objects.count(), 1)

    def test_database_unique_constraint_still_returns_bin_error(self):
        Company.objects.create(**self.company_data)

        def simulate_stale_bin_check(execute, sql, params, many, context):
            if sql.startswith("SELECT") and '"crm_company"."bin" = %s' in sql:
                return execute("SELECT 1 WHERE 0", (), many, context)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(simulate_stale_bin_check):
            response = self.client.post("/companies", self.company_data, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("bin", response.json())
        self.assertEqual(Company.objects.count(), 1)

    def test_list_filters_before_paginating_and_sorts_by_id(self):
        matching_ids = []
        for index in range(23):
            company = Company.objects.create(
                name=f"Company {23 - index}",
                bin=f"{index:012}",
                status=Company.Status.NEW if index in (0, 11) else Company.Status.NO_ANSWER,
            )
            if company.status == Company.Status.NO_ANSWER:
                matching_ids.append(company.pk)

        first = self.client.get("/companies", {"status": "no_answer"}).json()
        second = self.client.get("/companies", {"status": "no_answer", "page": 2}).json()
        self.assertEqual(first["count"], 21)
        self.assertIsNone(first["previous"])
        self.assertIsNotNone(first["next"])
        self.assertEqual([company["id"] for company in first["results"]], matching_ids[:20])
        self.assertEqual([company["id"] for company in second["results"]], matching_ids[20:])
        self.assertIsNone(second["next"])
        self.assertIsNotNone(second["previous"])
        self.assertEqual(self.client.get("/companies").json()["count"], 23)

    def test_unknown_or_empty_status_returns_bad_request(self):
        for value in ("unknown", ""):
            with self.subTest(value=value):
                response = self.client.get("/companies", {"status": value})
                self.assertEqual(response.status_code, 400)
                self.assertIn("status", response.json())
