"""Mise à l'épreuve des conclusions : chaque conclusion clé est recalculée avec une hypothèse différente.

L'énoncé demande d'étudier la sensibilité des résultats à des hypothèses différentes. Trois tests,
tous en Python (aucun modèle) :
1. indice de référence du bêta : Nasdaq-100 (QQQ) contre S&P 500 (SPY) ;
2. fenêtre de risque : 12 mois contre 6 mois pour la cohérence avec le profil ;
3. pour Amira, part de technologie initiale du portefeuille fictif : ±10 points.
Une conclusion « tient » si elle reste la même avec l'autre hypothèse.
"""

from __future__ import annotations

from markets.window import market_model

from .impact_agent import profile_coherence, sector_exposure


def _driver(model: dict) -> str | None:
    if model.get("status") != "ok":
        return None
    return "propre au titre" if abs(model["residual"]) > abs(model["expected_return"]) else "porté par le marché"


def _num(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _pp(value: float) -> str:
    return f"{value * 100:+.2f} pts".replace(".", ",")


def run_sensitivity(window, returns: dict, profile: str, scenario: dict, coherence: dict) -> dict:
    checks = []

    # 1. Référence du bêta.
    base = returns.get("market_model") or {}
    alt = market_model(window, returns["usd_return"], returns["benchmarks"], reference="SPY")
    if _driver(base) and _driver(alt):
        holds = _driver(base) == _driver(alt)
        checks.append({
            "id": "beta_reference",
            "question": "Le mouvement est-il propre au titre ou porté par le marché ?",
            "base": f"Face au Nasdaq-100 : part propre {_pp(base['residual'])} (bêta {_num(base['beta'])}) → {_driver(base)}",
            "alternative": f"Face au S&P 500 : part propre {_pp(alt['residual'])} (bêta {_num(alt['beta'])}) → {_driver(alt)}",
            "holds": holds,
        })

    # 2. Fenêtre de mesure du risque.
    ticker, end = window.ticker, window.end_close_date
    sector = sector_exposure(profile, ticker, scenario)
    # Seules les limites de risque (volatilité, pire baisse) dépendent de la fenêtre de mesure.
    long_risk = profile_coherence(profile, ticker, end)
    short = profile_coherence(profile, ticker, end, risk_sessions=126)
    if long_risk["risk"].get("status") == "ok" and short["risk"].get("status") == "ok":
        def verdict(c):
            return "incohérent avec le profil" if c["conflicts"] else "dans les limites du profil"
        checks.append({
            "id": "risk_window",
            "question": "Le risque du titre respecte-t-il les limites du profil ?",
            "base": (f"Sur 12 mois : volatilité {long_risk['risk']['annual_volatility']:.0%}, "
                     f"pire baisse {long_risk['risk']['max_drawdown']:.0%} → {verdict(long_risk)}"),
            "alternative": (f"Sur 6 mois : volatilité {short['risk']['annual_volatility']:.0%}, "
                            f"pire baisse {short['risk']['max_drawdown']:.0%} → {verdict(short)}"),
            "holds": bool(long_risk["conflicts"]) == bool(short["conflicts"]),
        })

    # 3. Amira : hypothèse sur la part de technologie du portefeuille fictif.
    if sector and sector["is_tech"]:
        limit = coherence["limits"].get("max_sector_weight")
        outcomes = []
        for delta in (-0.10, 0.10):
            shifted = {**scenario, "tech_weight": min(max(scenario["tech_weight"] + delta, 0.0), 1.0)}
            exposure = sector_exposure(profile, ticker, shifted)
            outcomes.append((shifted["tech_weight"], exposure["after"], exposure["after"] > limit))
        base_breach = sector["after"] > limit
        checks.append({
            "id": "tech_weight",
            "question": "L’achat pousse-t-il la part de technologie au-delà de la limite ?",
            "base": f"Part techno initiale {sector['before']:.0%} → {sector['after']:.0%} après l’achat "
                    f"({'au-delà' if base_breach else 'en deçà'} de {limit:.0%})",
            "alternative": " ; ".join(f"initiale {b:.0%} → {a:.0%} ({'au-delà' if breach else 'en deçà'})"
                                      for b, a, breach in outcomes),
            "holds": all(breach == base_breach for _, _, breach in outcomes),
        })

    robust = all(check["holds"] for check in checks)
    return {
        "checks": checks,
        "robust": robust,
        "summary": ("Les conclusions tiennent avec les hypothèses alternatives testées." if robust else
                    "Au moins une conclusion dépend d’une hypothèse : elle doit être lue avec prudence."),
    }
