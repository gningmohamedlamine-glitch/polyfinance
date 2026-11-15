"""Orchestrate the two agents and validate their handoff."""

import logging
import os
from threading import Lock
from time import perf_counter

from agents.dossier import SCHEMA, selection_payload
from agents.governance import run_controls
from agents.sensitivity import run_sensitivity
from agents.events import catalog_fingerprint, publication_coverage, session_window
from agents.impact_agent import _fallback_text
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


def get_dossier(window, returns, notify):
    key = (
        window.ticker, window.requested, window.start_close_date, window.end_close_date,
        catalog_fingerprint(), os.getenv("MARKET_WEB_SEARCH"), os.getenv("BEDROCK_MODEL_ID"),
    )
    with _cache_lock:
        cached = _event_cache.get(key)
    if cached is not None:
        notify("event", "cached_dossier", "done")
    dossier = cached if cached is not None else event_agent(window, notify)

    notify("event", "validate_dossier", "running")
    validate_dossier(window, returns, dossier)
    notify("event", "validate_dossier", "done")

    if cached is None and dossier["synthesis"]["mode_reason"] in (None, "model_unconfigured") and (
        "unavailable" not in (dossier["coverage"]["web_search"], dossier["coverage"]["sec_search"])
    ):
        with _cache_lock:
            _event_cache[key] = dossier
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


def run_analysis(window, profile, scenario, progress=None):
    started = {}

    def notify(agent, action, status, count=None, mode=None, *, reason=None):
        key = (agent, action)
        elapsed = None
        if status == "running":
            started[key] = perf_counter()
        elif key in started:
            elapsed = round((perf_counter() - started.pop(key)) * 1000)
        if status != "running":
            logger.info("analysis agent=%s action=%s status=%s duration_ms=%s count=%s mode=%s reason=%s",
                        agent, action, status, elapsed, count, mode, reason)
        if progress:
            progress(agent, action, status, count, mode, elapsed, reason)

    notify("event", "stage", "running")
    returns = window_returns(window)
    dossier = get_dossier(window, returns, notify)
    event = {
        **dossier["synthesis"],
        "sources": [{key: value for key, value in row.items() if key != "ticker"}
                    for row in dossier["publications"]],
    }
    if require_model() and event["mode"] != "bedrock":
        notify("event", "stage", "unavailable", mode="local", reason=event.get("mode_reason"))
        raise ModelUnavailable(explain("Enquêteur", event.get("mode_reason")))
    notify("event", "stage", "done", mode=event["mode"])
    notify("impact", "stage", "running")
    impact = impact_agent(dossier, profile, scenario, notify)
    if require_model() and impact["mode"] != "bedrock":
        notify("impact", "stage", "unavailable", mode="local", reason=impact.get("mode_reason"))
        raise ModelUnavailable(explain("Conseiller", impact.get("mode_reason")))
    notify("impact", "stage", "done", mode=impact["mode"])
    notify("governance", "stage", "running")
    sensitivity = run_sensitivity(window, returns, profile, scenario, impact.get("coherence") or {})
    controls = run_controls(dossier, event, impact, window.end_close_date, sensitivity)
    if controls["verdict"] == "fail":
        event["text"] = "La cause du mouvement reste indéterminée. Consulte les rendements calculés et les sources du dossier."
        impact["text"] = _fallback_text(profile, impact["metrics"], impact["assumptions"], impact["coherence"])
        event["text_mode"] = impact["text_mode"] = "guard"
        # Copie pour préserver le dossier conservé en cache.
        dossier = {**dossier, "synthesis": {**dossier["synthesis"], "text": event["text"], "text_mode": "guard"}}
    notify("governance", "stage", "done", mode="local")
    return {
        "controls": controls,
        "sensitivity": sensitivity,
        "movement": movement_legacy(window, returns),
        "dossier": dossier,
        "event": event,
        "impact": impact,
        "trace": impact["trace"],
    }
