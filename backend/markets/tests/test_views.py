from django.test import Client, SimpleTestCase

from markets.views import _event_cache


class AnalysisViewTests(SimpleTestCase):
    def setUp(self):
        _event_cache.clear()
        self.client = Client()

    def test_session_click_compatible(self):
        response = self.client.get(
            "/api/analysis/",
            {"ticker": "NVDA", "date": "2024-08-29", "profile": "amira"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("movement", payload)
        self.assertIn("dossier", payload)
        self.assertEqual(payload["movement"]["date"], "2024-08-29")

    def test_period_request(self):
        response = self.client.get(
            "/api/analysis/",
            {
                "ticker": "NVDA",
                "start_date": "2024-08-28",
                "end_date": "2024-09-06",
                "profile": "robert",
            },
        )
        self.assertEqual(response.status_code, 200)
        dossier = response.json()["dossier"]
        self.assertEqual(dossier["selection"]["applied"], "period")

    def test_invalid_range(self):
        response = self.client.get(
            "/api/analysis/",
            {"ticker": "NVDA", "start_date": "2024-09-06", "end_date": "2024-08-28", "profile": "amira"},
        )
        self.assertEqual(response.status_code, 400)