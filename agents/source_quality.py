"""Source provenance and literal excerpt checks; never a causal certification."""
import os
import re
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .events import _normalize

OFFICIAL_HOSTS = {
    'sec.gov', 'www.sec.gov', 'www.federalreserve.gov', 'www.bls.gov',
    'www.ftc.gov', 'www.eeoc.gov', 'www.dol.gov', 'www.consumerfinance.gov',
    'investor.nvidia.com', 'nvidianews.nvidia.com', 'www.apple.com',
    'www.microsoft.com', 'blogs.microsoft.com', 'abc.xyz', 'blog.google',
    'ir.aboutamazon.com', 'sustainability.aboutamazon.com', 'ir.tesla.com',
}
COMPANY_HOSTS = {
    'NVDA': 'nvidianews.nvidia.com', 'AAPL': 'apple.com',
    'MSFT': 'microsoft.com', 'GOOGL': 'abc.xyz',
    'AMZN': 'ir.aboutamazon.com', 'TSLA': 'ir.tesla.com',
}


def is_official(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname in OFFICIAL_HOSTS
                and parsed.port in (None, 443) and not parsed.username)
    except ValueError:
        return False


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@lru_cache(maxsize=128)
def read_official_page(url):
    # An exact host allowlist and no redirects keep model-supplied URLs bounded.
    if not is_official(url):
        raise ValueError('unsupported_url')
    agent = os.getenv('SEC_USER_AGENT') or 'AlphaForge research source checker/1.0'
    request = Request(url, headers={'User-Agent': agent})
    with build_opener(NoRedirect()).open(request, timeout=4) as response:
        if response.headers.get_content_type() not in ('text/html', 'text/plain'):
            raise ValueError('unsupported_content')
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('page_too_large')
        parser = PageText()
        parser.feed(raw.decode(response.headers.get_content_charset() or 'utf-8', 'replace'))
    text = re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()
    if len(text) < 200:
        raise ValueError('empty_page')
    return text


def check_source(lead):
    out = {**lead, 'source_origin': 'official' if is_official(lead['url']) else 'other',
           'page_status': 'not_checked', 'excerpt_status': 'no_excerpt'}
    if out['source_origin'] != 'official':
        return out
    try:
        text = read_official_page(lead['url'])
    except (OSError, ValueError):
        out['page_status'] = 'unavailable'
        return out
    out['page_status'] = 'retrieved'
    # Check only an explicitly quoted original-language passage, not a paraphrase.
    excerpt = lead.get('original_excerpt', '')
    if isinstance(excerpt, str) and len(excerpt.split()) >= 6:
        out['excerpt_status'] = 'verified' if _normalize(excerpt) in _normalize(text) else 'mismatch'
    return out
