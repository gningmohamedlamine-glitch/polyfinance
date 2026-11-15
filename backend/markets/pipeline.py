"""Orchestrate the two agents and validate their handoff."""

from copy import deepcopy
from time import monotonic
from agents.runtime import bounded_analysis, BudgetExceeded, checkpoint, setting
from agents.evidence import ensure_explanation

import logging
import os
from agents.runtime import ContextExecutor as ThreadPoolExecutor
from threading import Lock
from time import perf_counter

from agents.dossier import SCHEMA, selection_payload
from agents.agent_loop import model_for
from agents.governance import run_controls
from agents.sensitivity import run_sensitivity
from agents.events import catalog_fingerprint, publication_coverage, session_window
from agents.impact_agent import _fallback_text, prepare_profile, search_profile_esg
from agents.main import event_agent, impact_agent

from .window import movement_legacy, window_returns

_event_cache: dict = {}
_cache_lock = Lock()
logger = logging.getLogger(__name__)


def validate_dossier(window, returns, dossier):
    if dossier["schema"] != SCHEMA or dossier["selection"] != selection_payload(window):
        raise ValueError("Le dossier marché ne correspond pas à la sélection.")
    if dossier["returns"] != {key: value for key, value in returns.items() if key != "benchmarks"}:
        raise ValueError("Les rendements du dossier ne correspondent pas aux cours.")
    if dossier["benchmarks"] != returns["benchmarks"]:
        raise ValueError("Les indices du dossier ne correspondent pas aux cours.")

    sessions = window.measured_sessions
    bounds = {day: session_window(previous, day)
              for previous, day in zip((window.start_close_date, *sessions[:-1]), sessions, strict=True)}
    publications = dossier["publications"]
    for row in publications:
        if row["session"] not in bounds or row["ticker"] not in ("*", window.ticker):
            raise ValueError("Le dossier contient une publication hors fenêtre.")
        start, end = bounds[row["session"]]
        timestamp = row["time_et"]
        timestamp = timestamp + ":00" if len(timestamp) == 16 else timestamp
        if not start + ":00" < timestamp <= end + ":00":
            raise ValueError("Le dossier contient une publication hors fenêtre.")
    expected = publication_coverage(sessions, publications)
    if any(dossier["coverage"][key] != expected[key]
           for key in ("sessions_measured", "sessions_with_evidence", "sessions_unexplained")):
        raise ValueError("La couverture du dossier ne correspond pas à ses publications.")


def get_dossier(window, returns, notify, *, on_evidence=None, deep=False):
    key = (
        window.ticker, window.requested, window.start_close_date, window.end_close_date,
        catalog_fingerprint(), os.getenv("MARKET_WEB_SEARCH"), os.getenv("MARKET_WEB_SEARCH_AGENTCORE"),
        model_for("event"), os.getenv("AWS_REGION"), deep, repr(returns),
    )
    with _cache_lock:
        entry = _event_cache.get(key)
        cached = deepcopy(entry[1]) if entry and entry[0] > monotonic() else None
        if cached is None:
            _event_cache.pop(key, None)
    if cached is not None:
        notify("event", "cached_dossier", "done")
    def handoff(evidence):
        notify("event", "validate_dossier", "running")
        validate_dossier(window, returns, evidence)
        notify("event", "validate_dossier", "done")
        on_evidence(evidence)

    options = {"on_evidence": handoff} if on_evidence is not None else {}
    if deep:
        options["deep"] = True
    dossier = cached if cached is not None else event_agent(window, notify, **options)

    notify("event", "validate_dossier", "running")
    validate_dossier(window, returns, dossier)
    notify("event", "validate_dossier", "done")

    coverage = dossier["coverage"]
    grounding = coverage.get("nova_grounding")
    grounding_complete = grounding in (None, "grounding")
    if (cached is None and dossier["synthesis"]["mode_reason"] in (None, "model_unconfigured")
            and grounding_complete
            and coverage["web_search"] in {"found", "no_relevant_sources", "no_dated_sources", "disabled", "not_needed", "out_of_scope"}
            and coverage["sec_search"] in {"searched", "disabled", "not_needed", "not_requested"}):
        with _cache_lock:
            checkpoint()
            _event_cache[key] = (monotonic() + setting("ANALYSIS_CACHE_TTL_SECONDS", 900, 86400), deepcopy(dossier))
            if len(_event_cache) > 64:
                _event_cache.pop(next(iter(_event_cache)))
    return dossier


class ModelUnavailable(Exception):
    """Le modèle n'a pas répondu : pas de texte de repli, l'analyse s'arrête avec la raison."""


REASONS = {
    "model_unconfigured": "Aucun modèle configuré : définis BEDROCK_MODEL_ID.",
    "ExpiredToken": "Identifiants AWS expirés : renouvelle-les (Workshop Studio ou aws login).",
    "ExpiredTokenException": "Identifiants AWS expirés : renouvelle-les (Workshop Studio ou aws login).",
    "UnrecognizedClientException": "Identifiants AWS invalides : vérifie la clé et le jeton de session.",
    "InvalidSignatureException": "Identifiants AWS invalides : vérifie la clé et le jeton de session.",
    "NoCredentialsError": "Aucun identifiant AWS trouvé : renseigne le .env ou lance aws login.",
    "AccessDeniedException": "Accès refusé au modèle : vérifie les permissions IAM et l’accès au modèle dans Bedrock.",
    "ValidationException": "Requête refusée par Bedrock : vérifie l’identifiant du modèle (BEDROCK_MODEL_ID).",
    "ResourceNotFoundException": "Modèle introuvable : vérifie BEDROCK_MODEL_ID et la région.",
    "ThrottlingException": "Bedrock limite les requêtes : réessaie dans quelques secondes.",
    "ServiceUnavailableException": "Bedrock est momentanément indisponible : réessaie dans quelques secondes.",
    "ReadTimeoutError": "Le modèle a mis trop de temps à répondre : réessaie.",
    "EndpointConnectionError": "Impossible de joindre Bedrock : vérifie la connexion réseau.",
    "bedrock_incomplete": "Le modèle n’a pas terminé sa réponse : réessaie.",
    "bedrock_invalid_response": "Réponse du modèle inexploitable : réessaie.",
}


def require_model() -> bool:
    """Par défaut, aucun texte de repli : seuls les tests et la CI autorisent le calcul local."""
    return os.getenv("MARKET_ALLOW_LOCAL") != "1"


def explain(agent: str, reason: str | None) -> str:
    code = (reason or "").split(":", 1)[-1]
    return f"{agent} : {REASONS.get(code) or REASONS.get(reason or '') or f'le modèle n’a pas répondu ({reason}).'}"


def run_analysis(window, profile, scenario, progress=None, *, preview=None, evidence_preview=None, deep=False):
    try:
        return bounded_analysis(_run_analysis, window, profile, scenario, progress,
                                preview=preview, evidence_preview=evidence_preview, deep=deep)
    except BudgetExceeded as error:
        raise ModelUnavailable(str(error)) from error


def _run_analysis(window, profile, scenario, progress=None, *, preview=None, evidence_preview=None, deep=False):
    started = {}
    progress_lock = Lock()

    def notify(agent, action, status, count=None, mode=None, *, reason=None):
        checkpoint()
        key = (agent, action)
        elapsed = None
        with progress_lock:
            if status == "running":
                started[key] = perf_counter()
            elif key in started:
                elapsed = round((perf_counter() - started.pop(key)) * 1000)
        if status != "running":
            logger.info("analysis agent=%s action=%s status=%s duration_ms=%s count=%s mode=%s reason=%s",
                        agent, action, status, elapsed, count, mode, reason)
        if progress:
            progress(agent, action, status, count, mode, elapsed, reason)

    returns = window_returns(window)
    movement = movement_legacy(window, returns)
    prepared = prepare_profile(window, returns, profile, scenario)
    coherence = prepared["verify_profile_coherence"][3]
    if preview:
        preview({"movement": movement, "coherence": coherence})
    sensitivity = run_sensitivity(window, returns, profile, scenario, coherence)

    with ThreadPoolExecutor(max_workers=2) as workers:
        esg_future = (workers.submit(search_profile_esg, window)
                      if profile == "mateo" and model_for("impact") and os.getenv("MARKET_WEB_SEARCH") == "1" else None)
        advisor = None
        trace_size = 0

        def advise(evidence):
            impact = impact_agent(evidence, profile, scenario, notify, prepared=prepared, esg_future=esg_future)
            available = impact["mode"] == "bedrock" or not require_model()
            notify("impact", "stage", "done" if available else "unavailable", mode=impact["mode"],
                   reason=None if available else impact.get("mode_reason"))
            return impact

        def start_advisor(evidence):
            nonlocal advisor, trace_size
            if evidence_preview:
                evidence_preview({"publications": evidence["publications"],
                                  "web_leads": evidence["coverage"].get("web_leads", [])})
            trace_size = len(evidence["tools_executed"])
            notify("impact", "stage", "running")
            advisor = workers.submit(advise, evidence)

        notify("event", "stage", "running")
        parallel = model_for("event") and model_for("impact")
        dossier = get_dossier(window, returns, notify, on_evidence=start_advisor if parallel else None, deep=deep)
        event = {
            **dossier["synthesis"],
            "sources": [{key: value for key, value in row.items() if key != "ticker"}
                        for row in dossier["publications"]],
        }
        if require_model() and event["mode"] != "bedrock":
            notify("event", "stage", "unavailable", mode="local", reason=event.get("mode_reason"))
            raise ModelUnavailable(explain("Enquêteur", event.get("mode_reason")))
        notify("event", "stage", "done", mode=event["mode"])
        if advisor is None:
            start_advisor(dossier)
        impact = advisor.result()
        impact["trace"] = [*dossier["tools_executed"], *impact["trace"][trace_size:]]
    if require_model() and impact["mode"] != "bedrock":
        raise ModelUnavailable(explain("Conseiller", impact.get("mode_reason")))
    notify("governance", "stage", "running")
    ensure_explanation(event, dossier)
    ensure_explanation(impact, {"metrics": impact.get("metrics", []), "coherence": impact.get("coherence", {}), "esg": impact.get("esg")})
    controls = run_controls(dossier, event, impact, window.end_close_date, sensitivity)
    if controls["verdict"] == "fail":
        event["text"] = "La cause du mouvement reste indéterminée. Consulte les rendements calculés et les sources du dossier."
        impact["text"] = _fallback_text(profile, impact["metrics"], impact["assumptions"], impact["coherence"])
        event["text_mode"] = impact["text_mode"] = "guard"
        ensure_explanation(event, dossier)
        ensure_explanation(impact, {"metrics": impact["metrics"], "coherence": impact["coherence"]})
        # Copie pour préserver le dossier conservé en cache.
        dossier = {**dossier, "synthesis": {**dossier["synthesis"], **{key: event[key] for key in ("text", "claims", "evidence")}, "text_mode": "guard"}}
    notify("governance", "stage", "done", mode="local")
    return {
        "controls": controls,
        "sensitivity": sensitivity,
        "movement": movement,
        "dossier": dossier,
        "event": event,
        "impact": impact,
        "trace": impact["trace"],
    }
