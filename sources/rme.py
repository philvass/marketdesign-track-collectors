"""RME — Reguleringsmyndigheten for energi, the Norwegian energy regulator at NVE.

Discovery: "Nytt fra RME", the regulator's own news list on nve.no, server
rendered with title, date and lead, thirty items a page; the first page is
read. RME announces there its decisions on Statnett's terms and methodologies,
revenue-cap and tariff regulation, connection rules, consultations on
regulation changes and enforcement under the market-conduct rules. Norwegian
is read; there is no English edition of the list.

robots.txt forbids nothing but asks for a crawl delay of 20 seconds, so the
adapter waits that long between its own requests to the site. A run that has
several new items to fetch is therefore slow by design.

Not read: the rest of NVE (licensing of power plants, hydrology, the weekly
power situation), and the lists of individual decisions and complaints, whose
significant entries are announced in this news list anyway.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text, slugify,
                  MAX_CONTENT_CHARS)

INSTITUTION = "RME (Reguleringsmyndigheten for energi)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.nve.no"
LISTING = f"{BASE}/reguleringsmyndigheten/nytt-fra-rme/"
MAX_ITEMS = 25
CRAWL_DELAY = 20          # seconds, from nve.no/robots.txt

_ITEM = re.compile(r"/reguleringsmyndigheten/nytt-fra-rme/[^/]+/([^/?#]+)/?$")
_DATE = re.compile(r"(\d{2})\.(\d{2})\.(20\d{2})")
_last_request = 0.0


def _get(session, url):
    """One request to nve.no, no sooner than the crawl delay after the last."""
    global _last_request
    wait = CRAWL_DELAY - (time.monotonic() - _last_request)
    if _last_request and wait > 0:
        time.sleep(wait)
    try:
        return get_with_retry(session, url, timeout=45)
    finally:
        _last_request = time.monotonic()


def discover(session):
    r = _get(session, LISTING)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for a in soup.select('a[href*="/nytt-fra-rme/"]'):
        m = _ITEM.search(a["href"])
        head = a.select_one("h3")
        if not m or not head:
            continue
        title = " ".join(head.get_text(" ", strip=True).split())
        meta = a.select_one(".n-pagelist-item-content-meta")
        d = _DATE.search(meta.get_text() if meta else "")
        if not title:
            continue
        sid = f"rme-{slugify(m.group(1), max_len=140)}"
        found.setdefault(sid, Candidate(sid, title, f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
                                        urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise CollectorError("RME news list yielded no items: markup changed")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = _get(session, candidate.url)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    # "Les også" lists the other recent news, which changes with every new item.
    text = html_to_text(body).split("\nLes også\n")[0]
    if len(text.strip()) < 200:
        raise CollectorError(f"RME page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
