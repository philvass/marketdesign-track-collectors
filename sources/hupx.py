"""HUPX — the Hungarian power exchange and the country's nominated electricity
market operator.

HUPX runs the Hungarian day-ahead and intraday markets and takes part in the
European coupling projects, so its news covers go-lives of capacity
calculation and coupling changes, new products and markets (including the
ADEX regional intraday market it operates with its Adriatic partners), and
rule changes for members.

Discovery: the server-rendered news list at /hupx-news, nine items a page
with the date in each link (/YYYY/MM/DD/slug); the first two pages are read.
robots.txt closes only the Drupal system and search paths. The site publishes
its news in English, which is the complete edition.

Dropped by title: membership freeze periods, technical incidents, maintenance
windows, workshops and holiday calendars. Not read: the "OMM messages"
ticker, which is operational.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text, slugify,
                  MAX_CONTENT_CHARS)

INSTITUTION = "HUPX"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://hupx.hu"
NEWS = f"{BASE}/hupx-news"
PAGES = (NEWS, f"{NEWS}?page=1")

_ITEM = re.compile(r"^/(20\d{2})/(\d{2})/(\d{2})/([a-z0-9-]+)/?$")
_ROUTINE = re.compile(
    r"freeze period|Outlook|outage|maintenance|technical (?:issue|problem|difficult)|workshop|"
    r"webinar|holiday|trading calendar|certificate|season'?s greetings|award|conference|"
    r"annual report|financial statement", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    links = 0
    for url in PAGES:
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if url == NEWS:
                raise
            break                                   # the second page is a bonus
        soup = BeautifulSoup(r.text, "html.parser")
        for a in (soup.find("main") or soup).find_all("a", href=True):
            m = _ITEM.match(a["href"])
            title = " ".join(a.get_text(" ", strip=True).split())
            if not m or not title:
                continue
            links += 1
            if _ROUTINE.search(title):
                continue
            sid = f"hupx-{m.group(1)}{m.group(2)}{m.group(3)}-{slugify(m.group(4), 120)}"
            found.setdefault(sid, Candidate(sid, title, f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                                            urljoin(BASE, a["href"])))
    if not links:
        raise CollectorError("HUPX news list showed no dated links: markup changed")
    if not found:
        raise CollectorError("HUPX news: every item was filtered out, check the title filter")
    return NEWS, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.find("article") or soup.find("main") or soup)
    if len(text) < 200:
        raise CollectorError(f"HUPX article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
