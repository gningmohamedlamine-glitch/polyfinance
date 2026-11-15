"""Per-statement provenance. A valid reference is not a semantic or causal certification."""
import re

REFERENCE = re.compile(r'\[ref:([^\]\s]+)\]')
MEASURE = re.compile(r'(?<![\w.,])([+−-]?\d{1,3}(?:[ \u00a0\u202f]\d{3})+|[+−-]?\d+)(?:[.,](\d+))?\s*(%|pts?\b|points?\b|CAD\b|USD\b|\$|tCO2e\b)')
INSTRUCTIONS = (
    '\nPour chaque puce finale, cite au moins un identifiant exact de evidence_index sous la forme '
    '[ref:/chemin]. Les références sont séparées du texte par le serveur. Ne crée aucun identifiant. '
    'Cite le champ du calcul concerné ou la publication précise, pas un chiffre similaire ailleurs. '
    'Une référence valide ne prouve ni causalité ni véracité. Signale toute conclusion sans preuve. '
    'Respecte excerpt_status et temporal_status : extrait retrouvé ne signifie pas résumé vérifié ; '
    'same_day_time_unknown ne permet pas d’expliquer une séance par la publication. '
)


def index_evidence(value, prefix=''):
    index = {}
    def walk(item, path, context=None):
        if isinstance(item, dict):
            if item.get('url'):
                index[path] = {'kind': 'source', **{key: item[key] for key in
                    ('url', 'title', 'publisher', 'session', 'source_origin', 'page_status', 'original_excerpt', 'published_date', 'published_at', 'time_et', 'excerpt_status',
                     'temporal_status', 'eligible_for_explanation', 'summary', 'excerpt', 'value', 'unit',
                     'scope', 'methodology', 'metric', 'period_end', 'evidence_type', 'publication_date_status') if key in item}}
                return
            for key, val in item.items():
                if key not in {'evidence_index', 'trace', 'tools_executed', 'usage', 'reason',
                               'synthesis', 'claims', 'evidence', 'decisions', 'agent_decisions'}:
                    walk(val, path + '/' + str(key).replace('~', '~0').replace('/', '~1'), item)
        elif isinstance(item, (list, tuple)):
            for i, val in enumerate(item):
                walk(val, path + '/' + str(i))
        elif item is not None:
            index[path] = {'kind': 'calculation' if isinstance(item, (int, float)) and not isinstance(item, bool) else 'context',
                           'value': item}
            if context:
                for key in ('label', 'unit', 'symbol', 'start_date', 'end_date'):
                    if key in context and not isinstance(context[key], (dict, list)):
                        index[path][key] = context[key]
    walk(value, prefix)
    return index


def explain(text, index):
    claims = []
    for line in text.splitlines():
        if not line.strip():
            continue
        refs = list(dict.fromkeys(REFERENCE.findall(line)))
        unknown = [ref for ref in refs if ref not in index]
        clean = REFERENCE.sub('', line).strip()
        claims.append({'text': clean, 'evidence_ids': [r for r in refs if r in index],
                       'invalid_evidence_ids': unknown,
                       'status': 'invalid_reference' if unknown else 'linked' if refs else 'unlinked',
                       'numeric_check': check_claim_numbers(clean, [index[r] | {'path': r} for r in refs if r in index]),
                       'semantic_verification': 'not_performed'})
    return {'text': '\n'.join(c['text'] for c in claims), 'claims': claims, 'evidence': index}


def check_claim_numbers(text, cited):
    """Check signed, unit-bearing figures only against explicitly cited calculation fields.

    Source prose and implied direction ('a perdu 6 %') require interpretation,
    so this check warns rather than asserting semantic correctness.
    """
    figures = list(MEASURE.finditer(text))
    if not figures:
        return {'status': 'not_applicable', 'unmatched': []}
    values = []
    for item in cited:
        if item.get('kind') != 'calculation':
            continue
        value, unit = item['value'], item.get('unit')
        field = item['path'].rsplit('/', 1)[-1]
        if field.endswith('_pp'):
            values.append((value, 'points'))
        elif unit == '%' or field.endswith('_return') or field in {'return', 'annual_volatility', 'max_drawdown', 'return_12m'}:
            values.append((value * 100, '%'))
        elif unit in {'CAD', 'USD', 'tCO2e'}:
            values.append((value, unit))
    if not values:
        return {'status': 'not_checked', 'unmatched': []}
    unmatched = []
    for match in figures:
        whole, decimals, unit = match.groups()
        value = float(re.sub(r'[ \u00a0\u202f]', '', whole).replace('−', '-') + ('.' + decimals if decimals else ''))
        tolerance = 0.5 * 10 ** -len(decimals or '') + 1e-9
        units = {'CAD', 'USD'} if unit == '$' else {'points'} if unit.startswith(('pt', 'point')) else {unit}
        if not any(known_unit in units and abs(value - known_value) <= tolerance for known_value, known_unit in values):
            unmatched.append(match.group(0))
    return {'status': 'review' if unmatched else 'matched', 'unmatched': unmatched}


def ensure_explanation(result, evidence):
    if not result.get('claims') or [c['text'] for c in result['claims']] != [line.strip() for line in result.get('text', '').splitlines() if line.strip()]:
        result.update(explain(result.get('text', ''), index_evidence(evidence)))
    return result
