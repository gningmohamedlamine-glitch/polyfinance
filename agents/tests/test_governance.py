import unittest
from unittest import mock

from agents.event_agent import run_event_agent
from agents.governance import cited_numbers, run_controls
from agents.impact_agent import run_impact_agent
from markets.window import resolve_window

SCENARIO = {"position_cad": 10000, "withdrawal_cad": 9500, "portfolio_cad": 100000, "purchase_cad": 5000}


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict("os.environ", {"MARKET_WEB_SEARCH": "0", "BEDROCK_MODEL_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        self.dossier = run_event_agent(resolve_window("NVDA", date="2024-08-29"))
        self.event = {"text": self.dossier["synthesis"]["text"], "sources": self.dossier["publications"]}

    def controls(self, impact):
        result = run_controls(self.dossier, self.event, impact, "2024-08-29")
        return result, {c["id"]: c for c in result["controls"]}

    def test_robert_conflict_is_flagged_and_reported(self):
        impact = run_impact_agent(self.dossier, "robert", SCENARIO)
        result, by_id = self.controls(impact)
        self.assertEqual(by_id["profile"]["status"], "warn")
        self.assertEqual(by_id["no_advice"]["status"], "ok")
        self.assertEqual(by_id["no_future"]["status"], "ok")
        self.assertNotEqual(result["verdict"], "fail")

    def test_buy_advice_fails(self):
        impact = run_impact_agent(self.dossier, "robert", SCENARIO)
        impact["text"] = "Achète maintenant, je te recommande ce titre."
        result, by_id = self.controls(impact)
        self.assertEqual(by_id["no_advice"]["status"], "fail")
        self.assertEqual(result["verdict"], "fail")

    def test_invented_number_is_warned(self):
        impact = run_impact_agent(self.dossier, "robert", SCENARIO)
        impact["text"] += " Le titre a perdu 73,4 % en un jour."
        _, by_id = self.controls(impact)
        self.assertEqual(by_id["numbers"]["status"], "warn")
        self.assertIn("73,4 %", by_id["numbers"]["detail"])

    def test_number_parsing(self):
        values = [(raw, value) for raw, value, _ in cited_numbers("baisse de 6,38 % et 9 500 $ et 6 points")]
        self.assertEqual([v for _, v in values], [6.38, 9500.0, 6.0])
