"""Shared per-analysis limits, propagated into concurrent tasks.

The deadline stops waiting and prevents new work; in-flight SDK requests finish
under their own socket timeout. Their worker slot remains occupied until then.
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextvars import ContextVar, copy_context
from threading import BoundedSemaphore, Lock
from time import monotonic

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    pass


class ResearchTimeout(Exception):
    """Optional research ended; the main analysis may still synthesize."""


research_scope = ContextVar('research_scope', default=None)


def setting(name, default, maximum):
    try:
        return max(1, min(maximum, int(os.getenv(name, default))))
    except ValueError:
        return default


class Budget:
    def __init__(self):
        self.seconds = setting('ANALYSIS_TIMEOUT_SECONDS', 90, 150)
        self.max_calls = setting('ANALYSIS_MAX_MODEL_CALLS', 20, 40)
        self.max_output = setting('ANALYSIS_MAX_OUTPUT_TOKENS', 50000, 100000)
        self.max_input_bytes = setting('ANALYSIS_MAX_INPUT_BYTES', 1000000, 4000000)
        self.max_network = setting('ANALYSIS_MAX_NETWORK_CALLS', 40, 80)
        self.started = monotonic()
        self.deadline = self.started + self.seconds
        self.lock = Lock()
        self.cancelled = False
        self.calls = self.reserved_output = self.input_bytes = self.network_calls = 0
        self.input_tokens = self.output_tokens = 0

    def check(self):
        if self.cancelled or monotonic() >= self.deadline:
            raise BudgetExceeded('Durée maximale de l’analyse atteinte.')

    def reserve(self, kwargs):
        size = len(json.dumps(kwargs, ensure_ascii=False, default=str).encode('utf-8'))
        output = kwargs.get('inferenceConfig', {}).get('maxTokens', 0)
        with self.lock:
            self.check()
            if self.calls + 1 > self.max_calls or self.reserved_output + output > self.max_output:
                raise BudgetExceeded('Budget global d’appels ou de tokens de sortie atteint.')
            if self.input_bytes + size > self.max_input_bytes:
                raise BudgetExceeded('Budget global de données envoyées au modèle atteint.')
            self.calls += 1
            self.reserved_output += output
            self.input_bytes += size

    def report(self):
        with self.lock:
            return {'model_calls': self.calls, 'network_calls': self.network_calls,
                    'input_tokens': self.input_tokens, 'output_tokens': self.output_tokens,
                    'reserved_output_tokens': self.reserved_output, 'input_bytes': self.input_bytes,
                    'elapsed_ms': round((monotonic() - self.started) * 1000),
                    'limits': {'seconds': self.seconds, 'model_calls': self.max_calls,
                               'output_tokens': self.max_output, 'input_bytes': self.max_input_bytes,
                               'network_calls': self.max_network}}


current_budget = ContextVar('analysis_budget', default=None)


class ContextExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        return super().submit(copy_context().run, fn, *args, **kwargs)


def checkpoint():
    scope = research_scope.get()
    if scope and (scope['cancelled'] or monotonic() >= scope['deadline']):
        raise ResearchTimeout('Budget de recherche atteint ; synthèse avec les données disponibles.')
    budget = current_budget.get()
    if budget:
        budget.check()


def network_call():
    checkpoint()
    budget = current_budget.get()
    if budget:
        with budget.lock:
            budget.check()
            if budget.network_calls >= budget.max_network:
                raise BudgetExceeded('Budget global de requêtes externes atteint.')
            budget.network_calls += 1


def converse(client, **kwargs):
    checkpoint()
    budget = current_budget.get()
    if budget:
        budget.reserve(kwargs)
    response = client.converse(**kwargs)
    if budget:
        with budget.lock:
            usage = response.get('usage', {})
            budget.input_tokens += usage.get('inputTokens', 0)
            budget.output_tokens += usage.get('outputTokens', 0)
        checkpoint()
    return response


_research_workers = ContextExecutor(max_workers=4, thread_name_prefix='research')
_research_slots = BoundedSemaphore(4)


def bounded_research(fn, *args, **kwargs):
    """Stop waiting for research early enough to leave two synthesis calls time."""
    budget = current_budget.get()
    seconds = setting('ANALYSIS_RESEARCH_SECONDS', 30, 60)
    if budget:
        budget.check()
        seconds = min(seconds, budget.deadline - monotonic() - 55)
    if seconds <= 0 or not _research_slots.acquire(blocking=False):
        raise ResearchTimeout('Temps réservé aux synthèses ; recherche complémentaire interrompue.')
    scope = {'deadline': monotonic() + seconds, 'cancelled': False}
    token = research_scope.set(scope)
    try:
        future = _research_workers.submit(fn, *args, **kwargs)
    except BaseException:
        _research_slots.release()
        raise
    finally:
        research_scope.reset(token)
    future.add_done_callback(lambda _: _research_slots.release())
    try:
        return future.result(timeout=max(0, scope['deadline'] - monotonic()))
    except FutureTimeout as error:
        raise ResearchTimeout('Recherche interrompue pour terminer la synthèse.') from error
    finally:
        scope['cancelled'] = True
        future.cancel()


_workers = ContextExecutor(max_workers=4, thread_name_prefix='analysis')
_slots = BoundedSemaphore(4)


def bounded_analysis(fn, *args, **kwargs):
    if not _slots.acquire(blocking=False):
        raise BudgetExceeded('Quatre analyses sont déjà actives ; réessaie après leur fin.')
    budget = Budget()
    token = current_budget.set(budget)
    try:
        future = _workers.submit(fn, *args, **kwargs)
    except BaseException:
        _slots.release()
        raise
    finally:
        current_budget.reset(token)
    future.add_done_callback(lambda _: _slots.release())
    try:
        result = future.result(timeout=max(0, budget.deadline - monotonic()))
        budget.check()
        result['execution_budget'] = budget.report()
        return result
    except FutureTimeout as error:
        raise BudgetExceeded('Durée maximale de l’analyse atteinte.') from error
    finally:
        budget.cancelled = True
        future.cancel()
        logger.info('analysis_budget %s', budget.report())
