"""Run the real streaming endpoint and save a compact, reproducible quality report.

Uses configured AWS services and may incur their normal charges. Does not print credentials.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]


def summarize(messages, elapsed, request, http_status=200):
    final = messages[-1] if messages else {}
    result = final.get('analysis', {})
    coverage = result.get('dossier', {}).get('coverage', {})
    leads = coverage.get('web_leads', [])
    return {
        'request': request, 'http_status': http_status, 'elapsed_seconds': round(elapsed, 2),
        'final_kind': final.get('kind'), 'error': final.get('message'),
        'web_status': coverage.get('web_search'), 'grounding': coverage.get('nova_grounding'),
        'research_note': coverage.get('web_search_note'),
        'quality_rejected': coverage.get('quality_rejected', []),
        'lead_count': len(leads),
        'verified_excerpts': sum(row.get('excerpt_status') == 'verified' for row in leads),
        'multi_domain_stories': sum(row.get('corroboration', 1) > 1 for row in leads),
        'temporally_eligible': sum(row.get('eligible_for_explanation') is True for row in leads),
        'leads': [{key: row.get(key) for key in (
            'title', 'url', 'published_date', 'published_at', 'session', 'relevance', 'excerpt_status',
            'source_origin', 'page_status', 'temporal_status', 'eligible_for_explanation', 'corroboration')}
            for row in leads],
        'event_text': result.get('event', {}).get('text'), 'impact_text': result.get('impact', {}).get('text'),
        'coherence': result.get('impact', {}).get('coherence'), 'esg': result.get('impact', {}).get('esg'),
        'controls': result.get('controls'), 'execution_budget': result.get('execution_budget'),
        'progress': [{key: item.get(key) for key in ('agent', 'action', 'status', 'duration_ms')}
                     for item in messages if item.get('kind') == 'progress'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--profile', choices=('amira', 'mateo', 'robert'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from manage import load_env
    load_env(ROOT / '.env')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.test import Client
    request = {'ticker': args.ticker, 'date': args.date, 'profile': args.profile, 'stream': '1'}
    started = monotonic()
    response = Client().get('/api/analysis/', request)
    messages = []
    if response.streaming:
        for chunk in response.streaming_content:
            item = json.loads(chunk)
            messages.append(item)
            if item.get('kind') == 'progress' and item.get('status') != 'running':
                print(json.dumps({key: item.get(key) for key in ('agent', 'action', 'status', 'duration_ms')}), flush=True)
    else:
        messages.append({'kind': 'error', 'message': response.json().get('error')})
    report = summarize(messages, monotonic() - started, request, response.status_code)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('elapsed_seconds', 'final_kind', 'web_status', 'lead_count', 'verified_excerpts', 'multi_domain_stories')}), flush=True)
    return 0 if report['final_kind'] == 'result' else 1


if __name__ == '__main__':
    sys.exit(main())
