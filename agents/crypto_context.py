"""Dated crypto reference risks for Amira, without inventing portfolio holdings."""
from markets.market import CRYPTO_REFERENCE
from markets.window import risk_indicators, period_return


def crypto_context(end_date):
    references = []
    for symbol, name in CRYPTO_REFERENCE.items():
        try:
            risk = risk_indicators(symbol, end_date, 365, annualization=365)
        except ValueError:
            risk = {'status': 'missing'}
        row = {'symbol': symbol, 'name': name, **risk, 'annualization_days': 365,
               'source': 'data/prices_daily.csv', 'role': 'reference_only'}
        if risk['status'] == 'ok':
            row['period_return'] = period_return(symbol, end_date, 365)
            row['coverage'] = 'full' if risk['sessions'] == 365 else 'partial'
        references.append(row)
    return {'references': references, 'portfolio_exposure': None,
            'notice': 'BTC et ETH : repères de risque historiques, sans recommandation ni achat simulé. '
                      'Marché quotidien : annualisation sur 365 jours. Les montants crypto du portefeuille sont inconnus.',
            'missing': ['Exposition crypto et corrélations du portefeuille non mesurées faute de positions détaillées.']}
