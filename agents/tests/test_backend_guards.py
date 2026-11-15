import csv
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from agents.cache import ttl_cache
from agents.evidence import explain, ensure_explanation, index_evidence
from agents.esg import emission_history, esgv_membership, esg_screen
from agents.runtime import Budget, BudgetExceeded, ContextExecutor, bounded_analysis, converse, current_budget, network_call
from agents.temporal import availability
from agents.source_quality import PageText, SourceText, check_source


class EvidenceTests(unittest.TestCase):
    def test_exact_calculation_is_cited_and_not_exposed_in_prose(self):
        index = index_evidence({'returns': {'usd_return': -.0638}, 'metrics': [{'label': 'Poids', 'value': .1, 'unit': '%'}]})
        result = explain('- Variation −6,38 % [ref:/returns/usd_return]\n\n- Poids 10 % [ref:/metrics/0/value]', index)
        self.assertNotIn('[ref:', result['text'])
        self.assertTrue(all(c['status'] == 'linked' for c in result['claims']))
        self.assertTrue(all(c['numeric_check']['status'] == 'matched' for c in result['claims']))
        ensure_explanation(result, {})
        self.assertEqual(result['claims'][0]['evidence_ids'], ['/returns/usd_return'])

    def test_wrong_sign_and_wrong_field_cannot_match_a_number_elsewhere(self):
        index = index_evidence({'returns': {'usd_return': -.0638, 'cad_return': .12}})
        for text in ('+6,38 %', '12 %'):
            result = explain(text + ' [ref:/returns/usd_return]', index)
            self.assertEqual(result['claims'][0]['numeric_check']['status'], 'review')

    def test_invented_references_and_changed_text(self):
        result = explain('Fait [ref:/invented]', {})
        self.assertEqual(result['claims'][0]['status'], 'invalid_reference')
        result['text'] = 'Texte de garde'
        ensure_explanation(result, {})
        self.assertEqual(result['claims'][0]['status'], 'unlinked')
        self.assertEqual(result['claims'][0]['text'], result['text'])

    def test_source_preserves_provenance_and_emissions_scope(self):
        row = {'url': 'https://www.apple.com/report', 'value': 15, 'unit': 'tCO2e', 'scope': 'scope1',
               'published_date': '2025-04-16', 'excerpt_status': 'not_checked'}
        result = index_evidence({'emissions': [row]})['/emissions/0']
        self.assertEqual(result['scope'], 'scope1')
        self.assertEqual(result['value'], 15)
        self.assertEqual(result['kind'], 'source')


class TemporalTests(unittest.TestCase):
    def test_same_day_without_hour_is_unknown(self):
        self.assertFalse(availability({'published_date': '2024-08-29'}, '2024-08-29')['eligible_for_explanation'])
        self.assertTrue(availability({'published_date': '2024-08-28'}, '2024-08-29')['eligible_for_explanation'])

    def test_timestamp_timezone_and_early_close(self):
        self.assertTrue(availability({'published_at': '2024-11-29T17:59:00Z'}, '2024-11-29')['eligible_for_explanation'])
        self.assertFalse(availability({'published_at': '2024-11-29T18:01:00Z'}, '2024-11-29')['eligible_for_explanation'])
        self.assertTrue(availability({'time_et': '2024-08-29T15:59'}, '2024-08-29')['eligible_for_explanation'])
        self.assertFalse(availability({'published_at': '2024-08-29T15:59'}, '2024-08-29')['eligible_for_explanation'])

    def test_publisher_time_overrides_search_date_and_modified_date_is_ignored(self):
        parser = PageText()
        parser.feed('<meta property="article:modified_time" content="2025-01-01T00:00:00Z">')
        self.assertIsNone(parser.published_at)
        parser.feed('<meta property="article:published_time" content="2024-08-29T21:00:00Z">')
        page = SourceText('Company report text')
        page.published_at = parser.published_at
        with patch('agents.source_quality.read_official_page', return_value=page):
            row = check_source({'url': 'https://www.sec.gov/a', 'session': '2024-08-29', 'published_date': '2024-08-28'})
        self.assertEqual(row['publication_date_status'], 'publisher_metadata')
        self.assertEqual(row['search_published_date'], '2024-08-28')
        self.assertFalse(row['eligible_for_explanation'])


class RuntimeTests(unittest.TestCase):
    def test_model_calls_are_shared_across_threads(self):
        with patch.dict('os.environ', {'ANALYSIS_MAX_MODEL_CALLS': '1'}):
            budget = Budget()
        token = current_budget.set(budget)
        self.addCleanup(current_budget.reset, token)
        client = Mock()
        client.converse.return_value = {'usage': {'inputTokens': 30, 'outputTokens': 4}}
        with ContextExecutor(max_workers=2) as workers:
            workers.submit(converse, client, inferenceConfig={'maxTokens': 10}).result()
            with self.assertRaises(BudgetExceeded):
                workers.submit(converse, client, inferenceConfig={'maxTokens': 10}).result()
        client.converse.assert_called_once()
        self.assertEqual(budget.report()['output_tokens'], 4)

    def test_output_and_input_budget_reject_before_dispatch(self):
        for key, value in [('ANALYSIS_MAX_OUTPUT_TOKENS', '5'), ('ANALYSIS_MAX_INPUT_BYTES', '1')]:
            with self.subTest(key=key), patch.dict('os.environ', {key: value}):
                token = current_budget.set(Budget())
                try:
                    client = Mock()
                    with self.assertRaises(BudgetExceeded):
                        converse(client, inferenceConfig={'maxTokens': 10})
                    client.converse.assert_not_called()
                finally:
                    current_budget.reset(token)

    def test_network_budget_and_expired_deadline(self):
        with patch.dict('os.environ', {'ANALYSIS_MAX_NETWORK_CALLS': '1'}):
            budget = Budget()
        token = current_budget.set(budget)
        self.addCleanup(current_budget.reset, token)
        network_call()
        with self.assertRaises(BudgetExceeded):
            network_call()
        budget.deadline = 0
        with self.assertRaises(BudgetExceeded):
            converse(Mock(), inferenceConfig={'maxTokens': 1})

    def test_deadline_releases_caller_but_no_further_work(self):
        release, finished = Event(), Event()
        observed = []
        def slow():
            release.wait(3)
            try:
                network_call()
            except BudgetExceeded:
                observed.append('cancelled')
            finally:
                finished.set()
            return {}
        with patch.dict('os.environ', {'ANALYSIS_TIMEOUT_SECONDS': '1'}):
            try:
                with self.assertRaisesRegex(BudgetExceeded, 'Durée'):
                    bounded_analysis(slow)
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
        self.assertEqual(observed, ['cancelled'])

    def test_cache_expiry_detachment_and_failure_not_cached(self):
        calls = []
        @ttl_cache(seconds=10, maxsize=1)
        def read(key):
            calls.append(key)
            if key == 'failure':
                raise ValueError('unavailable')
            return {'data': [1]}
        with patch('agents.cache.monotonic', return_value=100):
            read('ok')['data'].append(9)
            self.assertEqual(read('ok'), {'data': [1]})
            self.assertEqual(calls, ['ok'])
        with patch('agents.cache.monotonic', return_value=111):
            read('ok')
        self.assertEqual(len(calls), 2)
        for _ in range(2):
            with self.assertRaises(ValueError):
                read('failure')
        self.assertEqual(calls.count('failure'), 2)


class EsgHistoryTests(unittest.TestCase):
    @patch('agents.esg.risk_indicators', return_value={'status': 'insufficient'})
    def test_same_day_timestamped_controversy_is_eligible_but_date_only_is_not(self, _risk):
        dossier = {'selection': {'ticker': 'NVDA', 'end_close_date': '2024-08-29'},
                   'publications': [{'title': 'Regulatory investigation', 'url': 'https://www.sec.gov/a',
                                     'time_et': '2024-08-29T10:00'}]}
        result = esg_screen(dossier)
        self.assertEqual(len(result['controversies']), 1)
        del dossier['publications'][0]['time_et']
        dossier['publications'][0]['published_date'] = '2024-08-29'
        self.assertEqual(esg_screen(dossier)['controversies'], [])

    def test_report_vintage_is_not_backdated(self):
        self.assertEqual(emission_history('AAPL', '2024-12-31'), [])
        self.assertEqual(emission_history('AAPL', '2025-04-16'), [])
        rows = emission_history('AAPL', '2025-04-17')
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]['value'], 15300000)
        self.assertTrue(all(row['published_date'] == '2025-04-16' for row in rows))
        self.assertEqual(emission_history('NVDA', '2025-04-17'), [])

    def test_partial_holdings_cannot_prove_absence_and_need_publication_date(self):
        with tempfile.TemporaryDirectory() as folder, patch('agents.esg.DATA', Path(folder)):
            path = Path(folder) / 'esgv_holdings.csv'
            fields = ['as_of', 'published_date', 'ticker', 'url', 'snapshot_complete']
            def write(published='2024-02-15', complete='false'):
                with path.open('w', newline='') as source:
                    writer = csv.DictWriter(source, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow(dict(zip(fields, ['2024-01-31', published, 'AAPL', 'https://www.sec.gov/report', complete])))
            write('')
            self.assertEqual(esgv_membership('AAPL', '2024-02-20')['status'], 'unavailable')
            write()
            self.assertEqual(esgv_membership('AAPL', '2024-02-15')['status'], 'unavailable')
            self.assertTrue(esgv_membership('AAPL', '2024-02-20')['member'])
            self.assertIsNone(esgv_membership('NVDA', '2024-02-20')['member'])
            self.assertEqual(esgv_membership('AAPL', '2024-07-01')['status'], 'stale')
            write(complete='true')
            self.assertFalse(esgv_membership('NVDA', '2024-02-20')['member'])


class PipelineCacheTests(unittest.TestCase):
    @patch.dict('os.environ', {'MARKET_WEB_SEARCH': '0', 'BEDROCK_MODEL_ID': '', 'ANALYSIS_CACHE_TTL_SECONDS': '10'}, clear=True)
    def test_dossier_expires_and_is_detached_from_caller(self):
        from agents.event_agent import run_event_agent
        from markets.pipeline import _event_cache, get_dossier
        from markets.window import resolve_window, window_returns
        _event_cache.clear()
        self.addCleanup(_event_cache.clear)
        window = resolve_window('NVDA', date='2024-08-29')
        dossier = run_event_agent(window)
        returns = window_returns(window)
        with patch('markets.pipeline.event_agent', return_value=dossier) as agent:
            with patch('markets.pipeline.monotonic', return_value=100):
                first = get_dossier(window, returns, Mock())
                original = first['publications'][0]['summary']
                first['publications'][0]['summary'] = 'Changed by caller'
                second = get_dossier(window, returns, Mock())
                self.assertEqual(second['publications'][0]['summary'], original)
                self.assertEqual(agent.call_count, 1)
            with patch('markets.pipeline.monotonic', return_value=111):
                get_dossier(window, returns, Mock())
                self.assertEqual(agent.call_count, 2)

    @patch.dict('os.environ', {'MARKET_WEB_SEARCH': '0', 'BEDROCK_MODEL_ID': ''}, clear=True)
    def test_partial_network_result_is_not_cached(self):
        from agents.event_agent import run_event_agent
        from markets.pipeline import _event_cache, get_dossier
        from markets.window import resolve_window, window_returns
        _event_cache.clear()
        self.addCleanup(_event_cache.clear)
        window = resolve_window('NVDA', date='2024-08-29')
        dossier = run_event_agent(window)
        dossier['coverage']['web_search'] = 'timeout'
        with patch('markets.pipeline.event_agent', return_value=dossier):
            get_dossier(window, window_returns(window), Mock())
        self.assertFalse(_event_cache)
