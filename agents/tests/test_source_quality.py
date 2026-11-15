import unittest
from threading import Barrier
from unittest.mock import Mock, patch

from botocore.exceptions import ReadTimeoutError

from agents.source_quality import check_source, is_official
from agents.web_search import _host_blocked, _agentcore_queries, search_agentcore_leads, _cluster_leads


class SourceQualityTests(unittest.TestCase):
    def test_official_hosts_are_exact_and_sec_allowed(self):
        self.assertFalse(_host_blocked('https://www.sec.gov/newsroom/a'))
        self.assertTrue(is_official('https://www.sec.gov/newsroom/a'))
        for url in ('http://www.sec.gov/a', 'https://www.sec.gov.evil.com/a',
                    'https://127.0.0.1/a', 'https://www.sec.gov:8080/a'):
            self.assertFalse(is_official(url))
        self.assertIn('site:nvidianews.nvidia.com', _agentcore_queries('NVDA', 'NVIDIA', '2022-05-04', '2022-05-09')[0])

    @patch('agents.source_quality.read_official_page')
    def test_only_literal_excerpt_is_verified(self, read):
        lead = {'url': 'https://www.sec.gov/a', 'original_excerpt': 'The company announced a new quarterly report.'}
        read.return_value = 'The company announced a new quarterly report. Other text.'
        self.assertEqual(check_source(lead)['excerpt_status'], 'verified')
        read.return_value = 'This is a different document.'
        self.assertEqual(check_source(lead)['excerpt_status'], 'mismatch')
        read.side_effect = OSError('blocked')
        self.assertEqual(check_source(lead)['page_status'], 'unavailable')

    @patch('agents.web_search.agentcore_client')
    def test_no_date_is_not_replaced_by_session(self, factory):
        factory.return_value.invoke_web_search.return_value = {'results': [{
            'url': 'https://www.sec.gov/a', 'title': 'News', 'text': 'Example news'}]}
        self.assertEqual(search_agentcore_leads('NVDA', 'NVIDIA', {'2022-05-09': ('2022-05-04', '2022-05-14')}), [])

    @patch('agents.web_search._agentcore_queries', return_value=['official', 'slow', 'press', 'extra'])
    @patch('agents.web_search.agentcore_client')
    def test_parallel_batch_preserves_query_priority_and_stops_at_limit(self, factory, _queries):
        started = Barrier(3, timeout=5)

        def fetch(searchQuery, **_):
            started.wait()
            if searchQuery == 'slow':
                raise ReadTimeoutError(endpoint_url='https://agentcore.example')
            return {'results': [
                {'url': f'https://example.com/{searchQuery}', 'title': 'Company earnings report', 'publishedAt': '2022-05-09'},
                {'url': 'https://example.com/shared', 'title': 'Company earnings outlook', 'publishedAt': '2022-05-09'},
            ]}

        search = factory.return_value.invoke_web_search
        search.side_effect = fetch
        leads = search_agentcore_leads('NVDA', 'NVIDIA', {'2022-05-09': ('2022-05-04', '2022-05-14')}, limit=3)

        self.assertEqual([lead['url'] for lead in leads], [
            'https://example.com/official', 'https://example.com/shared', 'https://example.com/press',
        ])
        self.assertEqual(search.call_count, 3)

    def test_cluster_cannot_invent_url_or_date(self):
        import json
        lead = {'url': 'https://www.sec.gov/a', 'title': 'News', 'summary': 'Facts',
                'published_date': '2022-05-06', 'session': '2022-05-09'}
        client = Mock()
        client.converse.return_value = {'output': {'message': {'content': [{'text': json.dumps({'stories': [
            {**lead, 'published_date': '2022-05-09', 'also_urls': ['https://invented.example/a']},
            {**lead, 'url': 'https://invented.example/b'}]})}]}}}
        rows = _cluster_leads(client, 'NVDA', 'NVIDIA', [lead, {**lead, 'url': 'https://www.sec.gov/b'}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['published_date'], '2022-05-06')
        self.assertEqual(rows[0]['corroboration'], 1)
