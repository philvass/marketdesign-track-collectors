"""BSP SouthPool — the Slovenian power exchange (part of ADEX Group).

Discovery: the "BSP News" listing, two pages of server-rendered cards with the
title and a machine-readable date. The site's robots.txt forbids only the
administrative and search paths. The English edition is read because it is the
site's primary one; the Slovenian edition carries a subset.

The exchange announces here the changes that matter for market design in
Slovenia and the region: coupling go-lives (intraday flow-based capacity
calculation, SIDC measures), new market segments, product and tick-size
changes, rule amendments. System notices, membership freezes, workshop
invitations and the results of single auctions are dropped by title.

Many notices are a short paragraph with the full release attached as a PDF;
when the page text is short the first attached PDF is read as well.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "BSP SouthPool"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://www.bsp-southpool.com"
NEWS = f"{BASE}/bsp-news"
PAGES = 2
MAX_ITEMS = 20

_ITEM = re.compile(r"^/(20\d{2})/(\d{2})/(\d{2})/([a-z0-9-]+)/?$")
_DROP = re.compile(
    r"connectivity issues|important notice|maintenance|freeze period|workshop|webinar|"
    r"successfully completed .*auctions?|auctions? for the sale|holiday|trading calendar|"
    r"new member|welcomes|annual report|anniversary|conference|award|general assembly|^meet ", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    links = 0
    for page in range(PAGES):
        url = NEWS if page == 0 else f"{NEWS}?page={page}"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if page == 0:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("h2 a[href]"):
            m = _ITEM.match(a["href"])
            if not m:
                continue
            links += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            if not title or _DROP.search(title):
                continue
            sid = f"bsp-{m.group(1)}{m.group(2)}{m.group(3)}-{slugify(m.group(4), 60)}"
            found.setdefault(sid, Candidate(sid, title, f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                                            urljoin(BASE, a["href"])))
    if not links:
        raise CollectorError("BSP news listing carried no article links: markup changed")
    if not found:
        raise CollectorError("BSP: every listed article was filtered out; check the title filter")
    return NEWS, list(found.values())[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("article") or soup.select_one("main")
    if body is None:
        raise CollectorError(f"BSP article has no body: {candidate.url}")
    pdf = body.select_one('a[href*="/sites/default/files/"][href*=".pdf"]')
    text = html_to_text(body)
    if pdf and len(text) < 1500:
        try:
            attached = extract_pdf_text(
                get_with_retry(session, urljoin(BASE, pdf["href"]), timeout=90).content).strip()
        except Exception:
            attached = ""
        if attached:
            text = f"{text}\n\n[Attached release]\n{attached}"
    if len(text) < 200:
        raise CollectorError(f"BSP article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
