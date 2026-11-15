"""Valide le résultat NDJSON réel après déploiement, avec erreurs explicites."""
import json
import sys


def validate_stream(lines):
    result = None
    for line in lines:
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get('kind') == 'error':
            raise ValueError('Échec API : ' + str(message.get('message', 'erreur inconnue')))
        if message.get('kind') == 'result':
            result = message.get('analysis')
    if not result:
        raise ValueError('Aucun résultat final dans le flux.')
    if any(result.get(agent, {}).get('mode') != 'bedrock' for agent in ('event', 'impact')):
        raise ValueError('Les deux agents doivent répondre via Bedrock.')
    status = result.get('dossier', {}).get('coverage', {}).get('web_search')
    if status not in {'found', 'no_relevant_sources', 'no_dated_sources'}:
        raise ValueError(f'Recherche web non opérationnelle : {status!r}')
    if not result.get('impact', {}).get('esg'):
        raise ValueError('Analyse ESG absente pour Mateo.')
    if not result.get('controls', {}).get('controls'):
        raise ValueError('Contrôles absents.')
    return result


if __name__ == '__main__':
    try:
        validate_stream(sys.stdin)
    except (ValueError, KeyError, TypeError) as error:
        sys.exit(str(error))
    print('Analyse Bedrock, recherche web, ESG et contrôles : OK')
