import json
import os
import unittest
from concurrent.futures import Future
from threading import Barrier
from time import monotonic, sleep
from unittest.mock import Mock, patch

from agents.event_agent import run_event_agent
from agents.web_search import (
    RELEVANCE_UNEVALUATED,
    _clean_snippet,
    _simple_dedupe_leads,
    find_web_leads,
    search_agentcore_leads,
    web_windows,
)
from markets.window import resolve_window


def _grounding_message(articles, *, cite=3):
    return {"output": {"message": {"content": [{
        "citationsContent": {
            "content": [{"text": json.dumps(articles)}],
            "citations": [{"location": {"web": {"url": row["url"]}}} for row in articles[:cite]],
        },
    }]}}}


def _judge_message(verdicts):
    return {"output": {"message": {"content": [{"text": json.dumps(verdicts)}]}}}


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
        self.assertEqual(windows["2024-10-08"], ("2024-09-18", "2024-10-13"))
        self.assertIn(("event", "web_search", "done", 1, None), events)
        self.assertEqual(synthesis.call_args.args[2]["web_leads"], [])  # Undated leads cannot explain a session.
        self.assertEqual(dossier["coverage"]["web_leads"], [{"title": "Piste"}])
        self.assertEqual(dossier["coverage"]["web_search"], "found")
        self.assertEqual(dossier["synthesis"]["mode_reason"], "bedrock_error")

    def test_clean_snippet_strips_pipe_metadata(self):
        raw = "| event_date | 2026-11-12 | | event_title | Nvidia Shares Plunge | | source_domain | …"
        self.assertEqual(_clean_snippet(raw), "Nvidia Shares Plunge")

    def test_simple_dedupe_merges_duplicate_headlines(self):
        leads = [
            {"url": "https://example.com/a", "title": "NVDA CEO resigns", "summary": "Démission annoncée."},
            {"url": "https://example.com/b", "title": "NVDA CEO resigns", "summary": "Démission annoncée. Kress intérim."},
        ]
        merged = _simple_dedupe_leads(leads)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["related_count"], 2)

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1"}, clear=True)
    @patch("agents.web_search._cluster_leads", side_effect=lambda _c, _t, _n, leads, **_: leads)
    @patch("agents.web_search.search_agentcore_leads", return_value=[])
    def test_grounded_week_includes_followup_but_rejects_uncited_and_outside_dates(self, _agentcore, _cluster):
        session = "2024-08-19"
        window = resolve_window("NVDA", date=session)
        windows = web_windows([session], window)
        self.assertEqual(windows, {session: ("2024-08-14", "2024-08-24")})
        articles = [
            {"url": f"https://example.com/{day}", "published_date": day,
             "session": session, "title": "Nvidia", "summary": "Contexte du marché."}
            for day in ("2024-08-16", "2024-08-20", "2024-08-23", "2024-08-19")
        ]
        kept_urls = [articles[0]["url"], articles[1]["url"]]
        client = Mock()
        client.converse.side_effect = [
            _grounding_message(articles),
            _judge_message([
                {"url": url, "relevant": True, "relevance": "Lié au titre et à la séance."}
                for url in kept_urls
            ]),
        ]

        leads, status = find_web_leads(
            client, "NVDA", "NVIDIA", windows, moves={session: 0.05},
        )

        self.assertEqual(status, "found")
        self.assertEqual([(row["published_date"], row["after_session"]) for row in leads],
                         [("2024-08-16", False), ("2024-08-20", True)])
        self.assertTrue(all(row["relevance"] for row in leads))
        self.assertEqual(client.converse.call_count, 2)

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1"}, clear=True)
    @patch("agents.web_search._cluster_leads", side_effect=lambda _c, _t, _n, leads, **_: leads)
    @patch("agents.web_search.search_agentcore_leads", return_value=[])
    def test_judge_drops_irrelevant_cited_leads(self, _agentcore, _cluster):
        session = "2024-08-19"
        window = resolve_window("NVDA", date=session)
        windows = web_windows([session], window)
        article = {
            "url": "https://example.com/unrelated",
            "published_date": "2024-08-18",
            "session": session,
            "title": "Autre titre",
            "summary": "Marché général.",
            "source_type": "news",
        }
        client = Mock()
        client.converse.side_effect = [
            _grounding_message([article], cite=1),
            _judge_message([{
                "url": article["url"],
                "relevant": False,
                "relevance": "Ne concerne pas NVIDIA.",
            }]),
        ]

        leads, status = find_web_leads(client, "NVDA", "NVIDIA", windows, moves={session: -0.02})

        self.assertEqual(status, "no_relevant_sources")
        self.assertEqual(leads, [])

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1"}, clear=True)
    @patch("agents.web_search._cluster_leads", side_effect=lambda _c, _t, _n, leads, **_: leads)
    @patch("agents.web_search.search_agentcore_leads", return_value=[])
    def test_judge_failure_keeps_dated_leads(self, _agentcore, _cluster):
        session = "2024-08-19"
        window = resolve_window("NVDA", date=session)
        windows = web_windows([session], window)
        article = {
            "url": "https://example.com/nvda",
            "published_date": "2024-08-18",
            "session": session,
            "title": "Nvidia",
            "summary": "Résultats.",
        }
        client = Mock()
        client.converse.side_effect = [
            _grounding_message([article], cite=1),
            {"output": {"message": {"content": [{"text": "prose sans JSON"}]}}},
        ]

        leads, status = find_web_leads(client, "NVDA", "NVIDIA", windows, moves={session: 0.03})

        self.assertEqual(status, "found")
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["relevance"], RELEVANCE_UNEVALUATED)

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1"}, clear=True)
    @patch("agents.web_search._cluster_leads", side_effect=lambda _c, _t, _n, leads, **_: leads)
    @patch("agents.web_search._grounding_leads", return_value=([], "not_executed"))
    @patch("agents.web_search.search_agentcore_leads")
    def test_agentcore_leads_survive_unavailable_grounding(self, agentcore, grounding, _cluster):
        session = "2024-08-19"
        window = resolve_window("NVDA", date=session)
        windows = web_windows([session], window)
        agentcore.return_value = [{
            "url": "https://www.reuters.com/nvda-story",
            "title": "Nvidia rises",
            "published_date": "2024-08-19",
            "session": session,
            "summary": "Hausse après résultats.",
            "source_type": "news",
            "after_session": False,
        }]
        providers = Barrier(2, timeout=5)

        def collect(result):
            providers.wait()
            return result

        agentcore.side_effect = lambda *_args, **_kwargs: collect(agentcore.return_value)
        grounding.side_effect = lambda *_args, **_kwargs: collect(grounding.return_value)
        client = Mock()
        client.converse.return_value = _judge_message([{
            "url": "https://www.reuters.com/nvda-story",
            "relevant": True,
            "relevance": "Couvre NVIDIA.",
        }])

        leads, status = find_web_leads(client, "NVDA", "NVIDIA", windows, moves={session: 0.05})

        self.assertEqual(status, "found")
        self.assertEqual(len(leads), 1)
        client.converse.assert_called_once()
        agentcore.assert_called_once()
        grounding.assert_called_once()

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1"}, clear=True)
    @patch("agents.web_search.GROUNDING_SOFT_BUDGET", 0)
    @patch("agents.web_search._rank_web")
    @patch("agents.web_search.search_agentcore_leads")
    @patch("agents.web_search._grounding_workers")
    def test_fast_search_can_finish_with_ranked_coverage_while_nova_is_pending(self, workers, agentcore, rank):
        nova = Future()
        workers.submit.return_value = nova
        session = "2024-09-03"
        windows = {session: ("2024-08-30", "2024-09-09")}
        sources = [
            {"url": f"https://{host}/story", "session": session, "title": "NVIDIA market news",
             "published_date": session, "summary": "News", "relevance": "Couvre NVIDIA."}
            for host in ("news-one.example", "news-two.example")
        ]
        agentcore.return_value = sources
        rank.return_value = (sources, "found")
        details = {}
        try:
            leads, status = find_web_leads(Mock(), "NVDA", "NVIDIA", windows, details=details)
            self.assertEqual(status, "found")
            self.assertEqual(len(leads), 2)
            self.assertEqual(details["grounding"], "budget_elapsed")
            self.assertFalse(nova.done())
            rank.assert_called_once()
        finally:
            nova.set_result(([], "grounding"))


class SearchBenchmarkTests(unittest.TestCase):
    """Compares the overlapped search with the previous sequential wait."""

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH": "1", "MARKET_WEB_SEARCH_AGENTCORE": "1"}, clear=True)
    @patch("agents.web_search._check_articles", side_effect=lambda leads, **_: leads)
    @patch("agents.web_search._rank_web")
    @patch("agents.web_search._grounding_leads")
    @patch("agents.web_search.search_agentcore_leads")
    def test_ranking_overlaps_the_nova_wait(self, agentcore, grounding, rank, _check):
        session = "2024-08-15"
        windows = {session: ("2024-08-10", "2024-08-20")}
        lead = {
            "url": "https://news.example/nvda", "title": "NVIDIA slides", "session": session,
            "published_date": session, "summary": "Baisse.", "after_session": False,
        }
        nova_s, rank_s = 0.6, 0.45

        def slow_agentcore(*_args, **_kwargs):
            return [lead]

        def slow_nova(*_args, **_kwargs):
            sleep(nova_s)
            return [], "timeout"

        def slow_rank(*_args, **_kwargs):
            sleep(rank_s)
            return ([{**lead, "relevance": "Lié au titre."}], "found")

        agentcore.side_effect = slow_agentcore
        grounding.side_effect = slow_nova
        rank.side_effect = slow_rank

        started = monotonic()
        leads, status = find_web_leads(Mock(), "NVDA", "NVIDIA", windows, moves={session: -0.04})
        elapsed = monotonic() - started

        self.assertEqual(status, "found")
        self.assertEqual(len(leads), 1)
        sequential = nova_s + rank_s
        self.assertLess(elapsed, sequential - 0.15, f"overlapped {elapsed:.2f}s, sequential would be {sequential:.2f}s")
        self.assertGreaterEqual(elapsed, nova_s - 0.05)

    @patch.dict(os.environ, {"MARKET_WEB_SEARCH_AGENTCORE": "1"}, clear=True)
    @patch("agents.web_search.agentcore_client")
    @patch("agents.web_search._agentcore_queries")
    def test_broad_queries_wait_until_official_results_miss_a_session(self, queries, factory):
        queries.return_value = [f"q{i}" for i in range(10)]
        session = "2024-08-15"

        def fetch(searchQuery, **_kwargs):
            host = "one.example" if searchQuery == "q0" else "two.example"
            if searchQuery in {"q0", "q1"}:
                return {"results": [{
                    "url": f"https://{host}/{searchQuery}",
                    "title": "NVIDIA shares drop",
                    "publishedAt": session,
                    "text": "NVIDIA shares drop after the session.",
                }]}
            return {"results": []}

        factory.return_value.invoke_web_search.side_effect = fetch
        leads = search_agentcore_leads(
            "NVDA", "NVIDIA", {session: ("2024-08-10", "2024-08-20")},
            moves={session: -0.04},
        )
        called = [call.kwargs["searchQuery"] for call in factory.return_value.invoke_web_search.call_args_list]
        self.assertEqual(sorted(called), [f"q{i}" for i in range(8)])
        self.assertEqual(len(leads), 2)
