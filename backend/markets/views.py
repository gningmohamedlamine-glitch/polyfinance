import math
from datetime import date

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from agents.main import PROFILES, event_agent, impact_agent

from .market import STOCKS, load_prices, movement, stock_history


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


@require_GET
def analysis(request):
    ticker = request.GET.get("ticker")
    profile = request.GET.get("profile", "amira")
    if ticker not in STOCKS or profile not in PROFILES:
        return JsonResponse({"error": "Action ou profil inconnu."}, status=400)
    try:
        session = date.fromisoformat(request.GET.get("date", "")).isoformat()
    except ValueError:
        return JsonResponse({"error": "Sélectionne une date valide."}, status=400)
    try:
        move = movement(ticker, session)
        position = amount(request, "position_cad", 10_000)
        withdrawal = amount(request, "withdrawal_cad", 9_500)
        portfolio = amount(request, "portfolio_cad", 100_000)
        purchase = amount(request, "purchase_cad", 5_000)
        if profile == "amira" and (portfolio == 0 or position + purchase > portfolio):
            raise ValueError("La position et l’achat doivent tenir dans le portefeuille existant.")
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)

    event = event_agent(move)
    impact = impact_agent(move, event["sources"], profile, position, withdrawal, portfolio, purchase)
    return JsonResponse({"movement": move, "event": event, "impact": impact})
