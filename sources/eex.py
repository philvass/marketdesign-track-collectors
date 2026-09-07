"""EEX (eex.com) — European Energy Exchange.

Discovery: the newsroom, read through a rendered fetch. EEX runs the EU ETS
primary auctions and the guarantee-of-origin and power derivatives markets, so
its customer information and market notices are where product and calendar
changes are announced first.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, html_to_text, render_html,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "EEX"
DOCUMENT_TYPE = "MARKET_OPERATOR"
NEEDS_BROWSER = True

BASE = "https://www.eex.com"
LISTING = f"{BASE}/en/newsroom"
_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})")


def _news_uid(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    for key, value in q.items():
        if "news" in key and value and value[0].isdigit():
            return value[0]
    return slugify(urlparse(url).path.rstrip("/").split("/")[-1] or url)


def discover(session):
    soup = BeautifulSoup(render_html(LISTING, timeout=90, virtual_time_ms=15000), "html.parser")

    found: dict[str, Candidate] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/newsroom/detail" not in href:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        # Cards concatenate headline, date and teaser; the headline ends where
        # the date begins.
        cut = _DATE.search(title)
        if cut:
            title = title[:cut.start()].strip(" -–—|")
        title = title.split(" Read more")[0].strip()
        if len(title) < 20:
            continue
        url = urljoin(BASE, href)
        sid = f"eex-{_news_uid(url)}"
        found.setdefault(sid, Candidate(sid, title, None, url))

    if not found:
        raise CollectorError("EEX newsroom carried no items")
    return LISTING, list(found.values())


DATE_REFINED_ON_FETCH = True


def fetch_content(session, candidate: Candidate) -> str:
    soup = BeautifulSoup(render_html(candidate.url, timeout=90, virtual_time_ms=12000),
                         "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.find("main") or soup.find("article") or soup
    text = html_to_text(body)

    if not candidate.publication_date:
        m = _DATE.search(text[:2500])
        if m:
            try:
                candidate.publication_date = datetime(
                    int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
            except ValueError:
                pass
    if len(text.strip()) < 300:
        raise CollectorError(f"EEX article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
