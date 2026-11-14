import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import events
from agents.event_agent import run_event_agent
from agents.impact_agent import profile_coherence, run_impact_agent
from markets.views import _event_cache
from markets.window import resolve_window, risk_indicators, window_returns

SCENARIO = {"position_cad": 10000, "withdrawal_cad": 9500, "portfolio_cad": 100000, "purchase_cad": 5000}


class CoherenceTests(unittest.TestCase):
    def setUp(self):
        _event_cache.clear()

    def test_risk_uses_no_future_data(self):
        risk = risk_indicators("NVDA", "2024-08-29")
        self.assertEqual(risk["status"], "ok")
        self.assertLessEqual(risk["end_date"], "2024-08-29")

    def test_robert_flags_volatile_title(self):
        coherence = profile_coherence("robert", "NVDA", "2024-08-29")
        self.assertFalse(coherence["coherent"])
        self.assertTrue(coherence["conflicts"])

    def test_amira_concentration_limit(self):
        coherence = profile_coherence("amira", "NVDA", "2024-08-29", weight_after=0.40)
        self.assertTrue(any("concentration" in c for c in coherence["conflicts"]))

    def test_impact_exposes_coherence(self):
        dossier = run_event_agent(resolve_window("NVDA", date="2024-08-29"))
        robert = run_impact_agent(dossier, "robert", SCENARIO)
        self.assertIn("coherence", robert)
        self.assertIn("Incohérence", robert["text"])
        self.assertTrue(any(step["name"] == "profile_coherence" for step in robert["trace"]))


class MarketModelTests(unittest.TestCase):
    def test_cpi_day_is_mostly_explained_by_beta(self):
        returns = window_returns(resolve_window("NVDA", date="2022-09-13"))
        model = returns["market_model"]
        self.assertEqual(model["status"], "ok")
        self.assertGreater(model["beta"], 1)
        raw_gap = returns["benchmarks"]["QQQ"]["gap_pp"]
        self.assertLess(abs(model["residual_pp"]), abs(raw_gap))

    def test_sector_benchmark_when_available(self):
        returns = window_returns(resolve_window("NVDA", date="2024-08-29"))
        if "XLK" in returns["benchmarks"]:
            self.assertEqual(returns["benchmarks"]["XLK"]["kind"], "sector")


class ExcerptTests(unittest.TestCase):
    EVENT = {"source_id": "test_source", "excerpt": "Revenue is expected to be $32.5 billion"}

    def test_statuses(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(events, "SOURCES", Path(tmp)):
            self.assertEqual(events.verify_excerpt(self.EVENT), "source_missing")
            (Path(tmp) / "test_source.txt").write_text("Outlook\nRevenue is expected to be\n$32.5 billion, plus", encoding="utf-8")
            self.assertEqual(events.verify_excerpt(self.EVENT), "verified")
            self.assertEqual(events.verify_excerpt({**self.EVENT, "excerpt": "consensus des analystes"}), "mismatch")
            self.assertEqual(events.verify_excerpt({"source_id": "x"}), "no_excerpt")


if __name__ == "__main__":
    unittest.main()
