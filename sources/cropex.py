"""CROPEX — the Croatian power exchange.

Discovery: the "Obavijesti" listing on cropex.hr, three pages of six
server-rendered entries each, with the headline and a machine-readable date.
The site's robots.txt forbids only the Joomla system folders. Croatian is
read because it is the complete edition.

CROPEX announces here its market changes: new markets and bidding zones it
operates in, product and rule changes, the SDAC/SIDC procedures it applies,
guarantee-of-origin auctions. Monthly reports, trading records, auction
results and holiday notices are dropped by title.

Not read: "Obavijesti o tržištu", the stream of operational messages about
maintenance windows and trading sessions.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "CROPEX"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://www.cropex.hr"
LISTING = f"{BASE}/hr/obavijesti.html"
PAGE_SIZE = 6
PAGES = 3

_ITEM = re.compile(r"^/hr/obavijesti/([^/?#]+)\.html$")
_DROP = re.compile(
    r"rekord|mjesečno izvješće|godišnje izvješće|rezultati dražb|blagdan|praznik|"
    r"radno vrijeme|novi član|čestit|konferencij|radionic|održavanj", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    entries = 0
    for page in range(PAGES):
        url = LISTING if page == 0 else f"{LISTING}?start={page * PAGE_SIZE}"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if page == 0:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".item-content"):
            a = item.select_one("h3 a[href]")
            m = _ITEM.match(a["href"]) if a else None
            if not m:
                continue
            entries += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            if not title or _DROP.search(title):
                continue
            when = item.select_one("time[datetime]")
            date = when["datetime"][:10] if when else None
            sid = f"cropex-{slugify(m.group(1))}"
            found.setdefault(sid, Candidate(sid, title, date, urljoin(BASE, a["href"])))
    if not entries:
        raise CollectorError("CROPEX notices listing carried no entries: markup changed")
    if not found:
        raise CollectorError("CROPEX: every notice was filtered out; check the title filter")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("article.com-content-article") or soup.select_one("main")
    if body is None:
        raise CollectorError(f"CROPEX notice has no body: {candidate.url}")
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"CROPEX notice yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
