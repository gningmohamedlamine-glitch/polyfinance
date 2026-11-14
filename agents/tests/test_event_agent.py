import os
import unittest
from unittest.mock import patch

from agents.event_agent import run_event_agent
from agents.tools import validate_event_args
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

    def test_reject_out_of_window_tool_args(self):
        window = resolve_window("NVDA", date="2024-08-29")
        error = validate_event_args(
            "search_publications",
            {"ticker": "NVDA", "sessions": ["2024-08-28"]},
            window,
        )
        self.assertEqual(error, "sessions invalides")