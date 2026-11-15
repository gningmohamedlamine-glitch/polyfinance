import unittest

from agents.events import find_events, publication_coverage, search_publications
from markets.market import stock_history


class EventsTests(unittest.TestCase):
    def test_nvda_8k_associated_to_session(self):
        pubs = find_events("NVDA", "2024-08-28", "2024-08-29")
        self.assertEqual(len(pubs), 1)
        self.assertEqual(pubs[0]["time_et"], "2024-08-28T16:21")

    def test_cpi_associated_to_macro_session(self):
        pubs = find_events("NVDA", "2022-09-12", "2022-09-13")
        self.assertEqual(len(pubs), 1)
        self.assertEqual(pubs[0]["publisher"], "U.S. Bureau of Labor Statistics")

    def test_period_coverage_and_dedupe(self):
        sessions = ("2024-08-29", "2024-08-30", "2024-09-03")
        rows = stock_history("NVDA")
        pubs = search_publications("NVDA", sessions, rows)
        coverage = publication_coverage(sessions, pubs)
        self.assertEqual(coverage["sessions_with_evidence"], ["2024-08-29"])
        urls = [row["url"] for row in pubs]
        self.assertEqual(len(urls), len(set(urls)))

class CorroborationTests(unittest.TestCase):
    def test_counts_independent_domains_only(self):
        from agents.web_search import corroborate
        lead = corroborate({"url": "https://www.reuters.com/a"}, ["https://reuters.com/b", "https://apnews.com/c"])
        self.assertEqual((lead["corroboration"], lead["verification"]), (2, "corroborated"))
        self.assertEqual(lead["domains"], ["apnews.com", "reuters.com"])
        single = corroborate({"url": "https://example.com/x"}, [])
        self.assertEqual(single["verification"], "single_source")
