import json
import logging
import math
from datetime import date
from queue import Queue
from threading import Thread

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET

from agents.main import PROFILES

from .market import STOCKS, load_prices, stock_history
from .pipeline import ModelUnavailable, run_analysis
from .window import resolve_window

logger = logging.getLogger(__name__)


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
        # Hypothèse du scénario : portefeuille fictif d’Amira déjà très exposé à la techno (intérêt pour l’IA).
        tech_weight = float(request.GET.get("tech_weight", 0.47))
        if not 0 <= tech_weight <= 1:
            raise ValueError("La part de technologie doit être comprise entre 0 et 1.")
        if profile == "amira" and (portfolio == 0 or position + purchase > portfolio):
            raise ValueError("La position et l’achat doivent tenir dans le portefeuille existant.")
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)

    scenario = {
        "position_cad": position,
        "withdrawal_cad": withdrawal,
        "portfolio_cad": portfolio,
        "purchase_cad": purchase,
        "tech_weight": tech_weight,
    }
    if request.GET.get("stream") == "1":
        response = StreamingHttpResponse(
            analysis_stream(window, profile, scenario), content_type="application/x-ndjson",
        )
        response["Cache-Control"] = "no-store"
        response["X-Accel-Buffering"] = "no"
        return response
    try:
        return JsonResponse(run_analysis(window, profile, scenario))
    except ModelUnavailable as error:
        return JsonResponse({"error": str(error)}, status=503)


def analysis_stream(window, profile, scenario):
    messages = Queue()

    def progress(agent, action, status, count, mode, duration_ms, reason):
        messages.put({"kind": "progress", "agent": agent, "action": action,
                      "status": status, "count": count, "mode": mode, "duration_ms": duration_ms,
                      "reason": reason})

    def run():
        try:
            result = run_analysis(window, profile, scenario, progress)
            messages.put({"kind": "result", "analysis": result})
        except ModelUnavailable as error:
            logger.warning("Model unavailable: %s", error)
            messages.put({"kind": "error", "message": str(error)})
        except Exception:
            logger.exception("Analysis failed while streaming")
            messages.put({"kind": "error", "message": "L’analyse a échoué. Réessaie dans un instant."})

    Thread(target=run, daemon=True).start()
    while True:
        message = messages.get()
        yield json.dumps(message, ensure_ascii=False) + "\n"
        if message["kind"] != "progress":
            return
