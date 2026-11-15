"""Import idempotent des communiqués FOMC officiels, sans clé API.

Usage: python scripts/import_fomc.py --years 2022 2023 2024 2025
Seules les pages indiquant explicitement 2:00 p.m. ET sont importées.
"""
import argparse
import csv
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.source_quality import read_official_page
from agents.events import EVENTS, SOURCES, verify_excerpt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--years', nargs='+', type=int, default=[2022, 2023, 2024, 2025])
    args = parser.parse_args()
    with EVENTS.open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        fields, rows = reader.fieldnames, list(reader)
    seen = {r['url'] for r in rows}
    added = 0
    SOURCES.mkdir(exist_ok=True)
    for year in args.years:
        url = f'https://www.federalreserve.gov/newsevents/pressreleases/{year}-press-fomc.htm'
        try:
            with urlopen(Request(url, headers={'User-Agent': 'AlphaForge research/1.0'}), timeout=15) as response:
                html = response.read(2_000_000).decode('utf-8', 'replace')
        except OSError as error:
            print(f'{year}: archive indisponible ({type(error).__name__})', flush=True)
            continue
        links = sorted(set(re.findall(r'/newsevents/pressreleases/monetary' + str(year) + r'\d{4}a\.htm', html)))
        for path in links:
            url = 'https://www.federalreserve.gov' + path
            if url in seen:
                continue
            try:
                text = read_official_page(url)
                if 'Federal Reserve issues FOMC statement' not in text or not re.search(r'For release at 2:00 p\.m\. E[DS]T', text):
                    continue
                match = re.search(r'(?:the Committee decided to|The Committee decided to)[^.]*target range[^.]*\.', text)
                if not match:
                    continue
                # Small literal passage: the local full text preserves the full context.
                excerpt = ' '.join(match.group().split()[:24])
                stamp = re.search(r'monetary(\d{4})(\d{2})(\d{2})a', path)
                day = '-'.join(stamp.groups())
                sid = f'fed_fomc_{day}'
                (SOURCES / f'{sid}.txt').write_text(f'source: {url}\n\n{text}', encoding='utf-8')
                row = dict(ticker='*', time_et=day+'T14:00', publisher='Réserve fédérale',
                           title=f'Décision du FOMC du {day}', url=url,
                           summary='Communiqué de politique monétaire : décision sur la fourchette du taux directeur. Consulter le texte pour la décision et son contexte.',
                           source_id=sid, source_url=url, excerpt=excerpt)
                assert verify_excerpt(row) == 'verified'
                rows.append(row)
                seen.add(url)
                added += 1
                print(f'{day}: extrait vérifié', flush=True)
            except (OSError, ValueError) as error:
                print(f'{path}: indisponible ({type(error).__name__})', flush=True)
            time.sleep(0.3)
    if added:
        with EVENTS.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print(f'{added} publications ajoutées ; {len(rows)} au total.')


if __name__ == '__main__':
    main()
