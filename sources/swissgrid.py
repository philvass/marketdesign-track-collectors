"""Swissgrid — the Swiss transmission system operator.

Discovery: the newsroom feed page, which lists news and media releases as
server-rendered cards with the date, the kind of item and the title. The site's
robots.txt allows every agent.

Switzerland sits outside the EU market-coupling arrangements but inside the
continental grid, so Swissgrid's decisions on control energy, imbalance pricing,
congestion and its relationship with the European platforms are market design
with cross-border consequences. Corporate items (appointments, annual results,
sustainability ratings) are dropped by title before anything is fetched.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Swissgrid"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.swissgrid.ch"
NEWS = f"{BASE}/en/home/newsroom/newsfeed.html"
MAX_ITEMS = 20

_ITEM = re.compile(r"/newsroom/newsfeed/(\d{4})(\d{2})(\d{2})-(\d+)\.html")
_CORPORATE = re.compile(
    r"board of directors|executive board|becomes a member|general meeting|financial year|"
    r"half-year results|annual results|sustainability rating|appointed|elected|bond|rating agency",
    re.I)


def discover(session):
    r = get_with_retry(session, NEWS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for a in soup.select('a[href*="/newsroom/newsfeed/"]'):
        m = _ITEM.search(a.get("href", ""))
        if not m:
            continue
        head = a.select_one(".teaser-list-item__title")
        title = " ".join((head.get_text(" ", strip=True) if head else a.get("title", "")).split())
        if not title or _CORPORATE.search(title):
            continue
        sid = f"swissgrid-{m.group(1)}{m.group(2)}{m.group(3)}-{m.group(4)}"
        found.setdefault(sid, Candidate(sid, title, f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                                        urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise CollectorError("Swissgrid newsfeed listed no items: markup changed")
    return NEWS, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    return html_to_text(body)[:MAX_CONTENT_CHARS]
