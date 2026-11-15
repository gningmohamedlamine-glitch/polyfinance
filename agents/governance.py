"""Contrôleur (agent de gouvernance déterministe) : vérifie le résultat des deux agents avant affichage.

Aucun modèle ici : chaque contrôle est une règle en Python, donc reproductible et vérifiable.
Il regroupe les garde-fous existants et en ajoute : pas de conseil d'achat ou de vente, chiffres
cités présents dans les données, sources vérifiées, aucune donnée postérieure à la séance,
informations manquantes. Statuts : ok, warn (à signaler), fail (règle enfreinte), info.
"""

from __future__ import annotations

import re

ADVICE = re.compile(
    r"\b(ach[eè]te[zs]?|achetons|vends|vendez|vendons|je (?:te |vous )?recommande|nous recommandons|"
    r"recommandation d[’']achat|tu devrais (?:acheter|vendre|investir)|il faut (?:acheter|vendre)|"
    r"buy|sell|strong buy)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?\s*(%|pts?\b|points?\b|\$)")
ANY_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _floats(value, out):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(abs(float(value)))
        out.add(abs(float(value)) * 100)
    elif isinstance(value, dict):
        for item in value.values():
            _floats(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _floats(item, out)


def _known_numbers(dossier: dict, impact: dict) -> set[float]:
    known: set[float] = set()
    _floats(dossier.get("returns"), known)
    _floats(dossier.get("benchmarks"), known)
    for key in ("metrics", "scenario", "coherence", "esg"):
        _floats(impact.get(key), known)
    # Chiffres présents dans les sources elles-mêmes (communiqués, résumés, extraits).
    for item in [*dossier.get("publications", []), *dossier.get("coverage", {}).get("web_leads", [])]:
        for field in ("summary", "excerpt", "title"):
            for match in ANY_NUMBER.findall(str(item.get(field) or "")):
                known.add(float(match.replace(",", ".")))
    return known


def cited_numbers(text: str) -> list[tuple[str, float, float]]:
    """(texte, valeur, tolérance d'arrondi) pour chaque chiffre suivi de %, pts ou $."""
    found = []
    for match in NUMBER.finditer(text):
        whole, decimals, _unit = match.groups()
        value = float(re.sub(r"[   ]", "", whole) + ("." + decimals if decimals else ""))
        tolerance = 0.5 * 10 ** -(len(decimals) if decimals else 0) + 1e-9
        found.append((match.group(0).strip(), value, tolerance))
    return found


def run_controls(dossier: dict, event: dict, impact: dict, selection_end: str) -> dict:
    controls = []

    def add(control_id, label, status, detail):
        controls.append({"id": control_id, "label": label, "status": status, "detail": detail})

    texts = {"Enquêteur": event.get("text") or "", "Conseiller": impact.get("text") or ""}

    # 1. Contraintes du profil : calculées par le code, et signalées dans le texte si enfreintes.
    coherence = impact.get("coherence") or {}
    conflicts = coherence.get("conflicts") or []
    if not coherence:
        add("profile", "Contraintes du profil", "fail", "La cohérence avec le profil n’a pas été calculée.")
    elif conflicts:
        mentioned = any(word in texts["Conseiller"].lower() for word in ("profil", "limite", "dépasse", "incohér"))
        add("profile", "Contraintes du profil", "warn" if mentioned else "fail",
            f"{len(conflicts)} limite(s) dépassée(s), "
            + ("signalée(s) à l’utilisateur." if mentioned else "mais absente(s) du texte du Conseiller."))
    else:
        add("profile", "Contraintes du profil", "ok", "Le risque observé respecte les limites du profil.")

    # 2. Cadre du défi : aucune recommandation d'achat ou de vente.
    advice = [f"{agent} : « {m.group(0)} »" for agent, text in texts.items() for m in ADVICE.finditer(text)]
    add("no_advice", "Aucun conseil d’achat ou de vente", "fail" if advice else "ok",
        "Formulation interdite : " + ", ".join(advice) if advice else "Aucune formulation de transaction.")

    # 3. Fidélité : chaque chiffre cité existe dans les données ou les sources.
    known = _known_numbers(dossier, impact)
    unmatched = []
    total = 0
    for agent, text in texts.items():
        for raw, value, tolerance in cited_numbers(text):
            total += 1
            if not any(abs(value - k) <= tolerance for k in known):
                unmatched.append(f"{agent} : {raw}")
    if total == 0:
        add("numbers", "Chiffres cités conformes aux données", "info", "Aucun chiffre cité dans les textes.")
    else:
        add("numbers", "Chiffres cités conformes aux données", "warn" if unmatched else "ok",
            f"Introuvable(s) dans les données : {', '.join(unmatched)}." if unmatched
            else f"{total} chiffre(s) cité(s), tous retrouvés dans les données ou les sources.")

    # 4. Sources : datées, extraits vérifiés contre le texte source.
    sources = event.get("sources") or []
    verified = sum(1 for s in sources if s.get("excerpt_status") == "verified")
    if not sources:
        add("sources", "Sources datées", "info", "Aucune source datée : la cause doit rester indéterminée.")
    elif verified:
        add("sources", "Sources datées", "ok", f"{len(sources)} source(s), {verified} extrait(s) vérifié(s) dans le texte source.")
    else:
        add("sources", "Sources datées", "warn", f"{len(sources)} source(s), aucun extrait vérifié (texte source non téléchargé).")

    # 5. Pistes web : présentées comme non vérifiées.
    leads = dossier.get("coverage", {}).get("web_leads") or []
    if leads:
        labelled = all("non vérifi" in text.lower() or "web" not in text.lower() for text in texts.values())
        add("web", "Pistes web signalées comme non vérifiées", "ok" if labelled else "warn",
            f"{len(leads)} piste(s) web, affichées comme non vérifiées.")

    # 6. Aucune donnée postérieure à la séance analysée.
    late = []
    risk = coherence.get("risk") or {}
    if risk.get("end_date") and risk["end_date"] > selection_end:
        late.append("mesure du risque")
    esg = impact.get("esg") or {}
    for snap in (esg.get("comparison") or {}).values():
        if snap and snap.get("end_date", "") > selection_end:
            late.append("comparaison ESG")
    add("no_future", "Aucune donnée postérieure à la séance", "fail" if late else "ok",
        "Données futures utilisées : " + ", ".join(late) if late else
        "Risque, bêta et comparaisons calculés uniquement avec des données antérieures.")

    # 7. Garde-fous en cours d'exécution : appels refusés par le code.
    decisions = [*(dossier.get("agent_decisions") or []), *(impact.get("decisions") or [])]
    refused = sum(1 for d in decisions if not d.get("accepted"))
    if decisions:
        add("tools", "Appels d’outils validés par le code", "info",
            f"{len(decisions)} décision(s) des agents, {refused} refusée(s) par les garde-fous.")

    # 8. Informations manquantes, déclarées plutôt que comblées.
    missing = [*(coherence.get("missing") or []), *(esg.get("missing") or [])]
    add("missing", "Informations manquantes déclarées", "info" if missing else "ok",
        " ".join(missing) if missing else "Aucune information manquante signalée.")

    statuses = {c["status"] for c in controls}
    verdict = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "ok"
    return {"verdict": verdict, "controls": controls,
            "notice": "Contrôles automatiques en code, sans modèle : ils vérifient, ils ne décident pas."}
