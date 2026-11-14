import unittest

from agents.event_agent import run_event_agent
from agents.impact_agent import run_impact_agent
from markets.window import resolve_window


class ImpactAgentTests(unittest.TestCase):
    def test_robert_and_amira_differ_on_period(self):
        window = resolve_window("NVDA", start_date="2024-08-28", end_date="2024-09-06")
        dossier = run_event_agent(window)
        robert = run_impact_agent(
            dossier,
            "robert",
            {"position_cad": 10000, "withdrawal_cad": 9500, "portfolio_cad": 100000, "purchase_cad": 5000},
        )
        amira = run_impact_agent(
            dossier,
            "amira",
            {"position_cad": 10000, "withdrawal_cad": 9500, "portfolio_cad": 100000, "purchase_cad": 5000},
        )
        self.assertNotEqual(robert["metrics"], amira["metrics"])
        self.assertTrue(any(metric["label"].startswith("Baisse maximale") for metric in robert["metrics"]))
        self.assertTrue(any("Poids" in metric["label"] for metric in amira["metrics"]))
