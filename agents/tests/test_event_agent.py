import json
import os
import unittest
from unittest.mock import Mock, patch

from agents.event_agent import run_event_agent
from agents.web_search import find_web_leads, web_windows
from markets.window import resolve_window


class EventAgentTests(unittest.TestCase):
    def test_local_mode_without_model(self):
        window = resolve_window("NVDA", date="2024-08-29")
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("BEDROCK_MODEL_ID", None)
            dossier = run_event_agent(window)
        self.assertEqual(dossier["schema"], "alphaforge.market_dossier.v1")
        self.assertEqual(dossier["synthesis"]["mode"], "local")
        self.assertTrue(dossier["publications"])

    def test_web_search_runs_before_synthesis_and_survives_model_failure(self):
        window = resolve_window("NVDA", start_date="2024-09-18", end_date="2024-10-08")
        events = []
        with (
            patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1"}, clear=True),
            patch("agents.event_agent.bedrock_client"),
            patch("agents.event_agent.search_filings", return_value=([], "searched")),
            patch("agents.event_agent.find_web_leads", return_value=([{"title": "Piste"}], "found")) as web,
            patch("agents.event_agent.synthesize", return_value={
                "text": "", "mode": "local", "mode_reason": "bedrock_error",
            }) as synthesis,
        ):
            dossier = run_event_agent(window, lambda *args: events.append(args))
        windows = web.call_args.args[-1]
        self.assertEqual(windows["2024-10-08"], ("2024-09-18", "2024-10-11"))
        self.assertIn(("event", "web_search", "done", 1, None), events)
        self.assertEqual(synthesis.call_args.args[2]["web_leads"], [{"title": "Piste"}])
        self.assertEqual(dossier["coverage"]["web_search"], "found")
        self.assertEqual(dossier["synthesis"]["mode_reason"], "bedrock_error")

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1"}, clear=True)
    def test_grounded_week_includes_followup_but_rejects_uncited_and_outside_dates(self):
        session = "2024-08-19"
        window = resolve_window("NVDA", date=session)
        windows = web_windows([session], window)
        self.assertEqual(windows, {session: ("2024-08-16", "2024-08-22")})
        articles = [
            {"url": f"https://example.com/{day}", "published_date": day,
             "session": session, "title": "Nvidia", "summary": "Contexte du marché."}
            for day in ("2024-08-16", "2024-08-20", "2024-08-23", "2024-08-19")
        ]
        client = Mock()
        client.converse.return_value = {"output": {"message": {"content": [{
            "citationsContent": {
                "content": [{"text": json.dumps(articles)}],
                "citations": [{"location": {"web": {"url": row["url"]}}} for row in articles[:3]],
            },
        }]}}}

        leads, status = find_web_leads(client, "NVDA", "NVIDIA", windows)

        self.assertEqual(status, "found")
        self.assertEqual([(row["published_date"], row["after_session"]) for row in leads],
                         [("2024-08-16", False), ("2024-08-20", True)])
