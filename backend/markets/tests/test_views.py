import json
from threading import Barrier
from unittest.mock import patch

from botocore.exceptions import ReadTimeoutError
from django.test import Client, SimpleTestCase

from agents.event_agent import run_event_agent
from markets.pipeline import _event_cache, run_analysis
from markets.window import resolve_window


class AnalysisViewTests(SimpleTestCase):
    def setUp(self):
        _event_cache.clear()
        self.client = Client()
        # Les tests tournent sans Bedrock : on autorise explicitement le calcul local.
        env = patch.dict("os.environ", {"MARKET_ALLOW_LOCAL": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_strict_mode_refuses_local_text(self):
        with patch.dict("os.environ", {"MARKET_ALLOW_LOCAL": "0", "BEDROCK_MODEL_ID": ""}):
            response = self.client.get("/api/analysis/", {"ticker": "NVDA", "date": "2024-08-29", "profile": "robert"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("BEDROCK_MODEL_ID", response.json()["error"])

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

    def test_analysis_parses_only_the_selected_profiles_fields(self):
        cases = {
            "amira": ({"withdrawal_cad": "invalide"},
                      {"position_cad": 10_000, "portfolio_cad": 100_000, "purchase_cad": 5_000, "tech_weight": 0.47}),
            "robert": ({"purchase_cad": "invalide"}, {"position_cad": 10_000, "withdrawal_cad": 9_500}),
            "mateo": ({"position_cad": "invalide"}, {}),
        }
        for profile, (irrelevant, expected) in cases.items():
            with self.subTest(profile=profile), patch("markets.views.run_analysis", return_value={}) as analyze:
                response = self.client.get("/api/analysis/", {
                    "ticker": "NVDA", "date": "2024-08-29", "profile": profile, **irrelevant,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(analyze.call_args.args[1:], (profile, expected))

    def test_invalid_range(self):
        response = self.client.get(
            "/api/analysis/",
            {"ticker": "NVDA", "start_date": "2024-09-06", "end_date": "2024-08-28", "profile": "amira"},
        )
        self.assertEqual(response.status_code, 400)

    @patch.dict("os.environ", {"MARKET_ALLOW_LOCAL": "1"}, clear=True)
    def test_stream_validates_market_dossier_before_impact(self):
        response = self.client.get("/api/analysis/", {
            "ticker": "NVDA", "date": "2024-08-29", "profile": "amira", "stream": "1",
        })
        messages = [json.loads(chunk) for chunk in response.streaming_content]
        self.assertEqual(messages[0]["kind"], "preview")
        self.assertEqual(messages[0]["movement"], messages[-1]["analysis"]["movement"])
        evidence = next(item for item in messages if item["kind"] == "evidence")
        self.assertEqual(evidence["publications"][0]["excerpt_status"], "verified")
        actions = [(item["agent"], item["action"], item["status"]) for item in messages if item["kind"] == "progress"]
        self.assertLess(
            actions.index(("event", "validate_dossier", "done")),
            actions.index(("impact", "stage", "running")),
        )
        self.assertEqual(messages[-1]["kind"], "result")
        self.assertGreaterEqual(messages[-2]["duration_ms"], 0)

    @patch.dict("os.environ", {"MARKET_ALLOW_LOCAL": "1"}, clear=True)
    def test_invalid_handoff_never_reaches_impact_or_cache(self):
        window = resolve_window("NVDA", date="2024-08-29")
        dossier = run_event_agent(window)
        dossier["publications"][0]["time_et"] = "2024-08-28T16:00:00"
        with (
            patch("markets.pipeline.event_agent", return_value=dossier),
            patch("markets.pipeline.impact_agent") as impact,
            self.assertRaisesRegex(ValueError, "publication hors fenêtre"),
        ):
            run_analysis(window, "amira", {"portfolio_cad": 100000, "position_cad": 10000, "purchase_cad": 5000})
        impact.assert_not_called()
        self.assertFalse(_event_cache)

    @patch.dict("os.environ", {"BEDROCK_MODEL_ID": "test-model"}, clear=True)
    def test_verified_catalogue_allows_both_agents_to_write_concurrently(self):
        writers = Barrier(2, timeout=5)

        def write_event(*args, **kwargs):
            writers.wait()
            return {"text": "Synthèse du mouvement", "mode": "bedrock", "mode_reason": None}

        def write_impact(dossier, profile, scenario, progress, *, prepared, esg_future):
            self.assertEqual(dossier["publications"][0]["excerpt_status"], "verified")
            self.assertEqual(dossier["synthesis"]["text"], "")
            writers.wait()
            return {"text": "Impact", "mode": "bedrock", "trace": list(dossier["tools_executed"])}

        with (
            patch("agents.event_agent.synthesize", side_effect=write_event),
            patch("markets.pipeline.impact_agent", side_effect=write_impact),
            patch("markets.pipeline.run_controls", return_value={"verdict": "ok"}),
        ):
            result = run_analysis(resolve_window("NVDA", date="2024-08-29"), "robert",
                                  {"position_cad": 10000, "withdrawal_cad": 10000})
        self.assertEqual(result["event"]["text"], "Synthèse du mouvement")
        self.assertEqual(result["impact"]["text"], "Impact")

    @patch.dict("os.environ", {"MARKET_WEB_SEARCH": "1", "MARKET_ALLOW_LOCAL": "1"}, clear=True)
    def test_web_timeout_keeps_result_and_allows_retry(self):
        request = {"ticker": "NVDA", "date": "2024-09-06", "profile": "amira", "stream": "1"}
        empty_search = {"output": {"message": {"content": [
            {"toolResult": {"status": "success"}},
            {"text": "[]"},
        ]}}}
        with (
            patch("agents.event_agent.bedrock_client") as client,
            patch("agents.event_agent.search_filings", return_value=([], "searched")),
        ):
            client.return_value.converse.side_effect = [
                ReadTimeoutError(endpoint_url="https://bedrock-runtime.example.com"),
                empty_search,
            ]
            first = self.client.get("/api/analysis/", request)
            messages = [json.loads(chunk) for chunk in first.streaming_content]
            web = next(item for item in messages if item.get("action") == "web_search"
                       and item["status"] == "unavailable")
            self.assertEqual(web["reason"], "timeout")
            result = messages[-1]["analysis"]
            self.assertEqual(result["dossier"]["coverage"]["web_search_reason"], "timeout")
            self.assertTrue(result["impact"]["metrics"])
            self.assertFalse(_event_cache)
            client.assert_called_once_with(read_timeout=40)

            retry = self.client.get("/api/analysis/", request)
            messages = [json.loads(chunk) for chunk in retry.streaming_content]
            self.assertEqual(messages[-1]["analysis"]["dossier"]["coverage"]["web_search"],
                             "no_dated_sources")
