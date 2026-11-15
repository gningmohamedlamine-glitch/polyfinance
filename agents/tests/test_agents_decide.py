"""L'Enquêteur et le Conseiller décident ; le code valide, borne et garantit."""
import os
import unittest
from unittest.mock import Mock, patch

from agents.event_agent import run_event_agent
from agents.impact_agent import run_impact_agent
from markets.window import resolve_window

SCENARIO = {"position_cad": 10000, "withdrawal_cad": 9500, "portfolio_cad": 100000, "purchase_cad": 5000}


def tool_use(name, args, reason="", uid="t1"):
    content = ([{"text": reason}] if reason else []) + [{"toolUse": {"toolUseId": uid, "name": name, "input": args}}]
    return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": content}}}


def final(text):
    return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}


def scripted(*responses):
    client = Mock()
    client.converse.side_effect = list(responses)
    return client


class InvestigatorTests(unittest.TestCase):
    @patch.dict(os.environ, {"BEDROCK_MODEL_ID": "gpt-6-astra"}, clear=True)
    def test_market_day_agent_chooses_catalog_and_concludes(self):
        client = scripted(
            tool_use("search_catalog", {"sessions": ["2022-09-13"]}, "Part propre au titre faible : je cherche une publication macro."),
            final("- Choc de marché après l’IPC.\n- NVDA a baissé autant qu’attendu."),
        )
        with patch("agents.agent_loop.bedrock_client", return_value=client):
            dossier = run_event_agent(resolve_window("NVDA", date="2022-09-13"))
        self.assertEqual(dossier["synthesis"]["mode"], "bedrock")
        self.assertTrue(any("IPC" in row["title"] for row in dossier["publications"]))
        decision = dossier["agent_decisions"][0]
        self.assertEqual((decision["tool"], decision["accepted"]), ("search_catalog", True))
        self.assertIn("macro", decision["reason"])
        self.assertTrue(any(step["source"] == "model" for step in dossier["tools_executed"]))

    @patch.dict(os.environ, {"BEDROCK_MODEL_ID": "gpt-6-astra"}, clear=True)
    def test_out_of_window_and_network_calls_are_refused(self):
        client = scripted(
            tool_use("search_catalog", {"sessions": ["2020-01-02"]}, uid="a"),
            tool_use("search_sec_filings", {"sessions": ["2024-08-29"]}, uid="b"),
            final("- Cause indéterminée."),
        )
        with patch("agents.agent_loop.bedrock_client", return_value=client):
            dossier = run_event_agent(resolve_window("NVDA", date="2024-08-29"))
        self.assertEqual([d["accepted"] for d in dossier["agent_decisions"]], [False, False])
        self.assertEqual(dossier["publications"], [])
        self.assertEqual(dossier["coverage"]["sec_search"], "disabled")

    @patch.dict(os.environ, {"BEDROCK_MODEL_ID": "gpt-6-astra"}, clear=True)
    def test_decision_budget_is_enforced(self):
        calls = [tool_use("search_catalog", {"sessions": ["2024-08-29"]}, uid=str(i)) for i in range(6)]
        client = scripted(*calls, final("- Fin."))
        with patch("agents.agent_loop.bedrock_client", return_value=client):
            dossier = run_event_agent(resolve_window("NVDA", date="2024-08-29"))
        accepted = [d for d in dossier["agent_decisions"] if d["accepted"]]
        self.assertEqual(len(accepted), 1)  # doublon refusé, puis limite atteinte
        self.assertLessEqual(len(dossier["agent_decisions"]), 6)


class AdvisorTests(unittest.TestCase):
    def dossier(self):
        with patch.dict(os.environ, {}, clear=True):
            return run_event_agent(resolve_window("NVDA", date="2024-08-29"))

    def test_guard_runs_coherence_when_model_skips_it(self):
        dossier = self.dossier()
        client = scripted(tool_use("position_value_cad", {}, "Robert a un retrait : je chiffre la position."),
                          final("- Variation simulée en CAD."))
        with patch.dict(os.environ, {"BEDROCK_MODEL_ID": "gpt-6-astra"}, clear=True), \
                patch("agents.agent_loop.bedrock_client", return_value=client):
            robert = run_impact_agent(dossier, "robert", SCENARIO)
        self.assertEqual(robert["mode"], "bedrock")
        self.assertFalse(robert["coherence"]["coherent"])
        self.assertEqual(robert["metrics"][0]["label"], "Volatilité annuelle (12 mois)")
        self.assertTrue(any(step["name"] == "profile_coherence" and step["source"] == "guard" for step in robert["trace"]))

    def test_profile_specific_tools_only(self):
        dossier = self.dossier()
        client = scripted(tool_use("direct_weight", {}, uid="a"), tool_use("verify_profile_coherence", {}, uid="b"),
                          final("- Incohérence avec le profil."))
        with patch.dict(os.environ, {"BEDROCK_MODEL_ID": "gpt-6-astra"}, clear=True), \
                patch("agents.agent_loop.bedrock_client", return_value=client):
            robert = run_impact_agent(dossier, "robert", SCENARIO)
        self.assertEqual([d["accepted"] for d in robert["decisions"]], [False, True])

    def test_bedrock_failure_falls_back_to_python_text(self):
        from botocore.exceptions import ClientError
        dossier = self.dossier()
        client = Mock()
        client.converse.side_effect = ClientError({"Error": {"Code": "x", "Message": "x"}}, "Converse")
        with patch.dict(os.environ, {"BEDROCK_MODEL_ID": "gpt-6-astra"}, clear=True), \
                patch("agents.agent_loop.bedrock_client", return_value=client):
            amira = run_impact_agent(dossier, "amira", SCENARIO)
        self.assertEqual((amira["mode"], amira["mode_reason"]), ("local", "bedrock_error"))
        self.assertTrue(amira["text"])


if __name__ == "__main__":
    unittest.main()


class WebGuardTests(unittest.TestCase):
    @patch.dict(os.environ, {"BEDROCK_MODEL_ID": "gpt-6-astra", "MARKET_WEB_SEARCH": "1"}, clear=True)
    def test_no_source_forces_web_search_and_rewrite(self):
        # 2024-08-15 : rien au catalogue ; l'Enquêteur conclut sans chercher sur le web.
        agent = scripted(
            tool_use("search_catalog", {"sessions": ["2024-08-15"]}, "Part propre faible : je cherche une publication macro."),
            final("- Cause indéterminée."),
        )
        writer = scripted(final("- Le marché a monté après des ventes au détail solides (piste web non vérifiée)."))
        lead = {"url": "https://example.com/a", "title": "Stocks rally on retail sales", "published_date": "2024-08-15",
                "session": "2024-08-15", "summary": "Hausse des marchés.", "after_session": False}
        with patch("agents.agent_loop.bedrock_client", return_value=agent), \
             patch("agents.model_text.bedrock_client", return_value=writer), \
             patch("agents.event_agent.bedrock_client", return_value=Mock()), \
             patch("agents.event_agent.find_web_leads", return_value=([lead], "found")) as web:
            dossier = run_event_agent(resolve_window("NVDA", date="2024-08-15"))
        web.assert_called_once()
        self.assertEqual(dossier["coverage"]["web_search"], "found")
        self.assertEqual(len(dossier["coverage"]["web_leads"]), 1)
        self.assertIn("ventes au détail", dossier["synthesis"]["text"])
        self.assertTrue(any(t["name"] == "web_search" and t["source"] == "guard" for t in dossier["tools_executed"]))
