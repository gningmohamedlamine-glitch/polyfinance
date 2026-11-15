import json
import unittest
from deploy.check_analysis import validate_stream


class SmokeTests(unittest.TestCase):
    def result(self, status='found'):
        return {'event': {'mode': 'bedrock'}, 'impact': {'mode': 'bedrock', 'esg': {'conclusion': 'insuffisant'}},
                'dossier': {'coverage': {'web_search': status}}, 'controls': {'controls': [{'status': 'warn'}]}}

    def test_success_and_empty_search(self):
        for status in ('found', 'no_dated_sources', 'no_relevant_sources'):
            lines = [json.dumps({'kind': 'progress'}), json.dumps({'kind': 'result', 'analysis': self.result(status)})]
            self.assertEqual(validate_stream(lines), self.result(status))

    def test_unavailable_web_fails(self):
        for status in ('disabled', 'timeout', 'unavailable', None):
            with self.assertRaises(ValueError):
                validate_stream([json.dumps({'kind': 'result', 'analysis': self.result(status)})])

    def test_error_missing_result_and_local_fallback_fail(self):
        for lines in ([], [json.dumps({'kind': 'error', 'message': 'Denied'})]):
            with self.assertRaises(ValueError):
                validate_stream(lines)
        result = self.result()
        result['event']['mode'] = 'local'
        with self.assertRaises(ValueError):
            validate_stream([json.dumps({'kind': 'result', 'analysis': result})])
