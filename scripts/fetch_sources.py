"""Télécharge le texte des sources du catalogue pour vérifier les extraits cités.

Usage (depuis la racine) :
    SEC_USER_AGENT="Equipe AlphaForge courriel@exemple.com" python scripts/fetch_sources.py

Pour chaque ligne de data/market_events.csv ayant un source_id, le script télécharge source_url (sinon url),
convertit le HTML en texte brut et l'enregistre dans data/sources/<source_id>.txt.
Il indique ensuite si l'extrait (colonne excerpt) figure mot pour mot dans la source.
Un fichier déjà présent n'est pas réécrit (supprimez-le pour le retélécharger).
"""
from __future__ import annotations

import csv
import os
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.events import EVENTS, SOURCES, verify_excerpt  # noqa: E402


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    return "".join(parser.parts)


def main() -> int:
    agent = os.getenv("SEC_USER_AGENT")
    if not agent:
        print("Définis SEC_USER_AGENT (nom de l'équipe et courriel), exigé par la SEC.")
        return 1
    SOURCES.mkdir(parents=True, exist_ok=True)
    with EVENTS.open(newline="", encoding="utf-8-sig") as f:
        events = list(csv.DictReader(f))
    for event in events:
        source_id = (event.get("source_id") or "").strip()
        if not source_id:
            continue
        target = SOURCES / f"{source_id}.txt"
        if not target.exists():
            url = (event.get("source_url") or event["url"]).strip()
            request = urllib.request.Request(url, headers={"User-Agent": agent})
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")
            target.write_text(f"source: {url}\n\n{html_to_text(html)}", encoding="utf-8")
            time.sleep(0.5)  # limite de fréquence de la SEC
        print(f"{source_id}: {verify_excerpt(event)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
