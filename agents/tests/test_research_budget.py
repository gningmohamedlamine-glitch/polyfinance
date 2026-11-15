import unittest
from threading import Event
from unittest.mock import Mock, patch

from agents.runtime import Budget, ResearchTimeout, bounded_research, current_budget, network_call
from agents.event_agent import run_event_agent
from agents.web_search import search_agentcore_leads
from markets.window import resolve_window


class ResearchBudgetTests(unittest.TestCase):
    def test_reserved_time_skips_research_without_cancelling_analysis(self):
        budget = Budget()
        budget.deadline = budget.started + 20
        token = current_budget.set(budget)
        try:
            fn = Mock()
            with self.assertRaises(ResearchTimeout):
                bounded_research(fn)
            fn.assert_not_called()
            network_call()  # Main context still works.
            self.assertFalse(budget.cancelled)
        finally:
            current_budget.reset(token)

    def test_slow_research_returns_and_cannot_launch_more_calls(self):
        release, finished = Event(), Event()
        observed = []
        def slow():
            release.wait(3)
            try:
                network_call()
            except ResearchTimeout:
                observed.append('stopped')
            finally:
                finished.set()
        with patch.dict('os.environ', {'ANALYSIS_RESEARCH_SECONDS': '1'}):
            try:
                with self.assertRaises(ResearchTimeout):
                    bounded_research(slow)
                network_call()
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
        self.assertEqual(observed, ['stopped'])

    @patch.dict('os.environ', {'MARKET_WEB_SEARCH': '1'}, clear=True)
    def test_long_period_research_timeout_still_reaches_synthesis(self):
        window = resolve_window('NVDA', start_date='2024-07-29', end_date='2026-10-29')
        with (patch('agents.event_agent.bedrock_client'),
              patch('agents.event_agent.search_filings', return_value=([], 'searched')),
              patch('agents.event_agent.bounded_research', side_effect=ResearchTimeout()),
              patch('agents.event_agent.synthesize', return_value={
                  'text': 'Recherche incomplète ; calculs disponibles.', 'mode': 'bedrock', 'mode_reason': None}) as synthesize):
            result = run_event_agent(window)
        synthesize.assert_called_once()
        self.assertEqual(result['synthesis']['mode'], 'bedrock')
        self.assertEqual(result['coverage']['web_search_reason'], 'budget_elapsed')
        self.assertIn('incomplète', result['coverage']['web_search_note'])
        self.assertLessEqual(len(result['coverage']['web_sessions_targeted']), 4)

    @patch.dict('os.environ', {'MARKET_WEB_SEARCH_AGENTCORE': '1'})
    @patch('agents.web_search.agentcore_client')
    def test_empty_results_cannot_trigger_unbounded_queries(self, factory):
        search = factory.return_value.invoke_web_search
        search.return_value = {'results': []}
        windows = {f'2024-08-{day:02}': ('2024-08-01', '2024-08-31') for day in range(1, 25)}
        self.assertEqual(search_agentcore_leads('NVDA', 'NVIDIA', windows), [])
        self.assertEqual(search.call_count, 12)
