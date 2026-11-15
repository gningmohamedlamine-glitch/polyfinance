import unittest
from concurrent.futures import Future
from unittest.mock import Mock, patch

from agents.crypto_context import crypto_context
from agents.esg import emission_history, esg_screen
from agents.event_agent import run_event_agent
from agents.impact_agent import run_impact_agent
from agents.search_quality import rejection_reason, filter_leads
from agents.web_search import find_web_leads, search_agentcore_leads
from markets.window import resolve_window, risk_indicators


class SearchQualityTests(unittest.TestCase):
    def test_exact_noise_categories_are_rejected_but_real_reports_remain(self):
        cases = [
            ('SEC FORM 4', 'https://www.sec.gov/Archives/edgar/data/1045810/123/xslF345X05/form.xml'),
            ('Document', 'https://www.sec.gov/Archives/edgar/data/1045810/123/doc.htm'),
            ('Article', 'https://example.com/news'),
            ('EDGAR Filing Documents', 'https://www.sec.gov/Archives/edgar/data/1045810/123/123-index.htm'),
            ('424B2', 'https://www.sec.gov/Archives/edgar/data/886982/123/doc.htm'),
            ('Assets and Liabilities of Commercial Banks', 'https://www.federalreserve.gov/releases/h8'),
        ]
        for title, url in cases:
            self.assertIsNotNone(rejection_reason({'title': title, 'url': url}, 'NVDA'))
        for title, url in [
            ('NVIDIA Announces Financial Results', 'https://nvidianews.nvidia.com/news/earnings'),
            ('Nvidia drops amid export restrictions', 'https://www.reuters.com/technology/nvidia'),
            ('Beige Book July 2024', 'https://www.federalreserve.gov/monetarypolicy/beigebook.htm'),
        ]:
            self.assertIsNone(rejection_reason({'title': title, 'url': url}, 'NVDA'))

    @patch.dict('os.environ', {'MARKET_WEB_SEARCH_AGENTCORE': '1'}, clear=True)
    @patch('agents.web_search._agentcore_queries', return_value=['official', 'news'])
    @patch('agents.web_search.agentcore_client')
    def test_noise_cannot_exhaust_slots_before_news(self, factory, _queries):
        def fetch(searchQuery, **kwargs):
            if searchQuery == 'official':
                return {'results': [{'url': f'https://www.sec.gov/{i}', 'title': 'Document', 'publishedAt': '2024-07-17T00:00:00Z'} for i in range(10)]}
            return {'results': [{'url': 'https://www.reuters.com/company', 'title': 'NVIDIA shares fall', 'publishedAt': '2024-07-17T00:00:00Z'}]}
        factory.return_value.invoke_web_search.side_effect = fetch
        rejected = []
        rows = search_agentcore_leads('NVDA', 'NVIDIA', {'2024-07-17': ('2024-07-12', '2024-07-22')}, limit=1, rejections=rejected)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rejected), 10)
        self.assertIsNone(rows[0]['published_at'])
        self.assertFalse(rows[0]['eligible_for_explanation'])
        self.assertEqual(rows[0]['temporal_status'], 'same_day_time_unknown')

    @patch.dict('os.environ', {'MARKET_WEB_SEARCH': '1'}, clear=True)
    @patch('agents.web_search.GROUNDING_SOFT_BUDGET', 0)
    @patch('agents.web_search._check_articles', side_effect=lambda rows, **kw: rows)
    @patch('agents.web_search._rank_web')
    @patch('agents.web_search.search_agentcore_leads')
    @patch('agents.web_search._grounding_workers')
    def test_partial_primary_results_survive_pending_nova(self, workers, search, rank, _check):
        pending = Future()
        workers.submit.return_value = pending
        lead = {'url': 'https://news.example/nvidia', 'title': 'NVIDIA shares fall', 'session': '2024-07-17', 'published_date': '2024-07-16'}
        search.return_value = [lead]
        rank.return_value = ([lead], 'found')
        details = {}
        try:
            rows, status = find_web_leads(Mock(), 'NVDA', 'NVIDIA', {'2024-07-17': ('2024-07-12', '2024-07-22')}, details=details)
            self.assertEqual(rows, [lead])
            self.assertEqual(status, 'found')
            self.assertEqual(details['grounding'], 'budget_elapsed')
        finally:
            pending.set_result(([], 'grounding'))


@patch.dict('os.environ', {'BEDROCK_MODEL_ID': '', 'EVENT_MODEL_ID': '', 'IMPACT_MODEL_ID': '', 'MARKET_WEB_SEARCH': '0'}, clear=True)
class ProfileCoverageTests(unittest.TestCase):
    def test_crypto_references_use_daily_calendar_and_no_future_prices(self):
        context = crypto_context('2024-07-17')
        self.assertIsNone(context['portfolio_exposure'])
        for row in context['references']:
            self.assertEqual(row['status'], 'ok')
            self.assertLessEqual(row['end_date'], '2024-07-17')
            self.assertEqual(row['annualization_days'], 365)
            baseline = risk_indicators(row['symbol'], '2024-07-17', 365)
            self.assertAlmostEqual(row['annual_volatility'], baseline['annual_volatility'] * (365 / 252) ** .5)

    def test_amira_high_risk_does_not_override_concentration(self):
        dossier = run_event_agent(resolve_window('NVDA', date='2024-07-17'))
        result = run_impact_agent(dossier, 'amira', {'portfolio_cad': 100000, 'position_cad': 10000, 'purchase_cad': 20000, 'tech_weight': .47})
        self.assertFalse(result['coherence']['coherent'])
        self.assertTrue(any('Poids direct' in text for text in result['coherence']['conflicts']))
        self.assertTrue(any('technologie' in text for text in result['coherence']['conflicts']))
        self.assertEqual(result['coherence']['portfolio_assessment'], 'partial')
        self.assertEqual(len(result['coherence']['crypto_context']['references']), 2)

    def test_microsoft_vintage_and_mateo_uncertainty(self):
        self.assertEqual(emission_history('MSFT', '2025-05-29'), [])
        rows = emission_history('MSFT', '2025-05-30')
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]['value'], 15543000)
        dossier = run_event_agent(resolve_window('MSFT', date='2025-05-30'))
        result = run_impact_agent(dossier, 'mateo', {})
        self.assertNotIn('crypto_context', result['coherence'])
        self.assertEqual(result['esg']['coverage']['emission_observations'], 5)
        self.assertFalse(result['esg']['coverage']['independent_score_available'])
        self.assertEqual(result['esg']['membership']['status'], 'unavailable')
        self.assertTrue(result['esg']['disclosures'])
        self.assertFalse(result['esg']['controversies'])
        self.assertEqual(result['esg']['conclusion'], 'insuffisant')
