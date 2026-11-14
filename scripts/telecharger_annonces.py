"""Télécharge des communiqués depuis SEC EDGAR et les enregistre en texte brut.

Sortie : data/annonces/<TICKER>_<AAAA-MM-JJ>_<description>.txt
En-tête de chaque fichier (2 lignes) :
    source: <url>
    publie: <moment>

Variable d'environnement obligatoire : SEC_USER_AGENT, par exemple
    export SEC_USER_AGENT="Equipe AlphaForge prenom.nom@exemple.com"

Usage : python scripts/telecharger_annonces.py
"""
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# (ticker, date AAAA-MM-JJ, description) -> (moment de publication, url)
# N'ajouter que des URL vérifiées : aucune URL n'est devinée par le script.
DOCUMENTS = {
    ("NVDA", "2023-05-24", "resultats-T1"): (
        "après la clôture",
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581023000087/q1fy24pr.htm",
    ),
}

PAUSE_SECONDES = 0.25  # la SEC limite à 10 requêtes/s ; on reste au-dessus de 0,2 s
TIMEOUT_SECONDES = 30
DOSSIER_SORTIE = Path(__file__).resolve().parent.parent / "data" / "annonces"


def lire_user_agent() -> str:
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        sys.exit(
            "Erreur : la variable d'environnement SEC_USER_AGENT est absente.\n"
            'La SEC exige un User-Agent identifiant l\'équipe, par exemple :\n'
            '  export SEC_USER_AGENT="Equipe AlphaForge prenom.nom@exemple.com"'
        )
    return user_agent


def html_vers_texte(html: str) -> str:
    soupe = BeautifulSoup(html, "html.parser")
    for balise in soupe(["script", "style"]):
        balise.decompose()
    texte = soupe.get_text("\n").replace("\xa0", " ")
    lignes = [re.sub(r"[ \t]+", " ", ligne).strip() for ligne in texte.splitlines()]
    compact = []
    for ligne in lignes:
        if ligne or (compact and compact[-1]):  # une seule ligne vide consécutive
            compact.append(ligne)
    return "\n".join(compact).strip() + "\n"


def nom_fichier(ticker: str, date: str, description: str) -> str:
    return f"{ticker}_{date}_{description}.txt"


def main() -> int:
    user_agent = lire_user_agent()
    DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})

    telecharges, existants, echecs = [], [], []
    derniere_requete = 0.0
    for (ticker, date, description), (publie, url) in DOCUMENTS.items():
        chemin = DOSSIER_SORTIE / nom_fichier(ticker, date, description)
        if chemin.exists():
            existants.append(chemin.name)
            continue
        attente = PAUSE_SECONDES - (time.monotonic() - derniere_requete)
        if attente > 0:
            time.sleep(attente)
        try:
            reponse = session.get(url, timeout=TIMEOUT_SECONDES)
            derniere_requete = time.monotonic()
            reponse.raise_for_status()
        except requests.RequestException as erreur:
            derniere_requete = time.monotonic()
            echecs.append((chemin.name, str(erreur)))
            continue
        corps = html_vers_texte(reponse.text)
        chemin.write_text(f"source: {url}\npublie: {publie}\n{corps}", encoding="utf-8")
        telecharges.append(chemin.name)

    print(f"Téléchargés : {len(telecharges)}")
    for nom in telecharges:
        print(f"  + {nom}")
    print(f"Déjà présents (non réécrits) : {len(existants)}")
    for nom in existants:
        print(f"  = {nom}")
    print(f"Échecs : {len(echecs)}")
    for nom, erreur in echecs:
        print(f"  ! {nom} : {erreur}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
