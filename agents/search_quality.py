"""Deterministic exclusions before model ranking; official does not mean relevant."""
import re
from urllib.parse import urlsplit

CIKS = {'NVDA': 1045810, 'AAPL': 320193, 'MSFT': 789019, 'GOOGL': 1652044, 'AMZN': 1018724, 'TSLA': 1318605}
GENERIC = {'', 'article', 'document', 'untitled', 'home', 'homepage', 'sec form 4'}


def rejection_reason(lead, ticker):
    title = str(lead.get('title') or '').strip()
    if title.lower() in GENERIC:
        return 'generic_title'
    url = str(lead.get('url') or '')
    path = urlsplit(url).path.lower()
    text = title + ' ' + str(lead.get('summary') or '')
    if re.search(r'\b(?:SEC\s+)?FORM\s+(?:[345]|144)(?:/A)?\b', text, re.I) or re.search(r'xslf345|xsl144|ownership\.xml|form[345]\.xml', path):
        return 'ownership_filing'
    if re.search(r'\b424B[23578]\b|autocallable|equity.linked notes|contingent coupon', text, re.I):
        return 'structured_product_prospectus'
    match = re.search(r'/archives/edgar/data/(\d+)/', path)
    if match and ticker in CIKS and int(match[1]) != CIKS[ticker]:
        return 'other_issuer_filing'
    if '-index.' in path and '/edgar/' in path:
        return 'filing_index_without_document'
    if re.search(r'announces upcoming event for financial community', title, re.I):
        return 'routine_event_invitation'
    if re.search(r'stock price (?:&|and) news|stock quote', title, re.I):
        return 'rolling_quote_page'
    if re.search(r'assets and liabilities of commercial banks|selected assets and liabilities', title, re.I):
        return 'routine_banking_statistics'
    if re.search(r'closed board meeting', title, re.I):
        return 'routine_meeting_notice'
    return None


def filter_leads(leads, ticker):
    kept, rejected = [], []
    for lead in leads:
        reason = rejection_reason(lead, ticker)
        if reason:
            rejected.append({'url': lead.get('url'), 'title': lead.get('title'), 'reason': reason})
        else:
            kept.append(lead)
    return kept, rejected
