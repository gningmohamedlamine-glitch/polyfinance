import unittest

from django.test import SimpleTestCase

from markets.market import load_prices
from markets.window import _benchmark, notable_sessions, resolve_window, window_returns


class WindowTests(SimpleTestCase):
    def setUp(self):
        load_prices.cache_clear()

    def test_nvda_session_2024_08_29(self):
        window = resolve_window("NVDA", date="2024-08-29")
        returns = window_returns(window)
        self.assertAlmostEqual(returns["usd_return"], -0.06384855, places=8)
        spy = returns["benchmarks"]["SPY"]
        self.assertEqual(spy["status"], "ok")
        self.assertAlmostEqual(spy["gap_pp"], -6.393808, places=5)

    def test_nvda_period_clustered(self):
        window = resolve_window("NVDA", start_date="2024-08-28", end_date="2024-09-06")
        notable = notable_sessions(window)
        self.assertEqual(window.applied, "period")
        self.assertEqual(len(notable["sessions"]), 3)
        self.assertEqual(notable["concentration"], "clustered")
        returns = window_returns(window)
        self.assertAlmostEqual(returns["usd_return"], -0.18135514, places=8)

    def test_missing_benchmark(self):
        spy = _benchmark("SPY", "2024-08-28", "9999-01-01", -0.1)
        self.assertEqual(spy["status"], "missing")
        self.assertIsNone(spy["gap_pp"])