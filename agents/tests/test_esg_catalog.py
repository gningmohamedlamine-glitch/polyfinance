import unittest
from unittest.mock import patch
from agents.esg import catalog_publications, esg_screen
from agents.event_agent import run_event_agent
from markets.window import resolve_window


class EsgCatalogTests(unittest.TestCase):
    def test_no_future_or_stale_publication(self):
        self.assertEqual(catalog_publications("AMZN", "2024-12-18"), [])
        self.assertEqual(catalog_publications("AMZN", "2024-12-19"), [])
        self.assertEqual(catalog_publications("AMZN", "2026-10-28"), [])
        self.assertEqual(len(catalog_publications("AMZN", "2024-12-20")), 1)

    @patch.dict("os.environ", {}, clear=True)
    def test_all_six_examples_produce_sourced_results_offline(self):
        cases = {"AMZN": "2024-12-20", "AAPL": "2024-10-24",
                 "MSFT": "2023-06-06", "TSLA": "2023-09-29",
                 "NVDA": "2022-05-09", "GOOGL": "2024-07-03"}
        for ticker, day in cases.items():
            with self.subTest(ticker=ticker):
                result = esg_screen(run_event_agent(resolve_window(ticker, date=day)))
                self.assertEqual(result["conclusion"], "points_attention")
                self.assertTrue(any(c["kind"] == "publication officielle cataloguée"
                                    for c in result["controversies"]))
                self.assertTrue(all(c["published_date"] < day for c in result["controversies"]))
