import math
from datetime import date

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from agents.events import catalog_fingerprint
from agents.main import PROFILES, event_agent, impact_agent

from .market import STOCKS, load_prices, stock_history
from .window import movement_legacy, resolve_window, window_returns

_event_cache: dict = {}


def dossier_cache_key(window):
    return (window.ticker, window.requested, window.start_close_date, window.end_close_date, catalog_fingerprint())


def get_dossier(window):
    key = dossier_cache_key(window)
    cached = _event_cache.get(key)
    if cached:
        return cached
    dossier = event_agent(window)
    if dossier["synthesis"].get("mode_reason") not in (None, "model_unconfigured"):
        return dossier
    _event_cache[key] = dossier
    if len(_event_cache) > 64:
        _event_cache.pop(next(iter(_event_cache)))
    return dossier


def dossier_to_event(dossier: dict) -> dict:
    synthesis = dossier["synthesis"]
    sources = [{key: row[key] for key in row if key != "ticker"} for row in dossier["publications"]]
    return {
        "text": synthesis["text"],
        "mode": synthesis["mode"],
        "mode_reason": synthesis.get("mode_reason"),
        "sources": sources,
    }


@require_GET
def health(request):
    ready = all(len(rows) > 1 for rows in load_prices().values())
    return JsonResponse({"status": "ok" if ready else "unavailable"}, status=200 if ready else 503)


@require_GET
def stocks(request):
    return JsonResponse({
        "stocks": [{"ticker": ticker, "name": name} for ticker, name in STOCKS.items()],
        "profiles": PROFILES,
    })


@require_GET
def history(request, ticker):
    if ticker not in STOCKS:
        return JsonResponse({"error": "Action inconnue."}, status=404)
    return JsonResponse({"ticker": ticker, "rows": stock_history(ticker)})


def amount(request, key, default):
    value = float(request.GET.get(key, default))
    if not math.isfinite(value) or not 0 <= value <= 1_000_000_000:
        raise ValueError("Chaque montant doit être compris entre 0 et 1 milliard CAD.")
    return value


def parse_selection(request, ticker: str):
    start = request.GET.get("start_date")
    end = request.GET.get("end_date")
    session = request.GET.get("date")
    if start or end:
        if session:
            raise ValueError("Utilise date ou start_date et end_date, pas les deux.")
        if not start or not end:
            raise ValueError("Fournis start_date et end_date ensemble.")
        return resolve_window(
            ticker,
            start_date=date.fromisoformat(start).isoformat(),
            end_date=date.fromisoformat(end).isoformat(),
        )
    if not session:
        raise ValueError("Sélectionne une date valide.")
    return resolve_window(ticker, date=date.fromisoformat(session).isoformat())


@require_GET
def analysis(request):
    ticker = request.GET.get("ticker")
    profile = request.GET.get("profile", "amira")
    if ticker not in STOCKS or profile not in PROFILES:
        return JsonResponse({"error": "Action ou profil inconnu."}, status=400)
    try:
        window = parse_selection(request, ticker)
        position = amount(request, "position_cad", 10_000)
        withdrawal = amount(request, "withdrawal_cad", 9_500)
        portfolio = amount(request, "portfolio_cad", 100_000)
        purchase = amount(request, "purchase_cad", 5_000)
        if profile == "amira" and (portfolio == 0 or position + purchase > portfolio):
            raise ValueError("La position et l’achat doivent tenir dans le portefeuille existant.")
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)

    returns = window_returns(window)
    move = movement_legacy(window, returns)
    dossier = get_dossier(window)
    scenario = {
        "position_cad": position,
        "withdrawal_cad": withdrawal,
        "portfolio_cad": portfolio,
        "purchase_cad": purchase,
    }
    impact = impact_agent(dossier, profile, scenario)
    event = dossier_to_event(dossier)
    return JsonResponse({
        "movement": move,
        "dossier": dossier,
        "event": event,
        "impact": impact,
        "trace": impact.get("trace", dossier.get("tools_executed", [])),
    })