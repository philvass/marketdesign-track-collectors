"""Utility Regulator (UR) — the regulator of electricity, gas and water in
Northern Ireland, and one of the two regulators behind the SEM Committee.

Discovery: the server-rendered news list on uregni.gov.uk, first two pages,
newest first, each row with its title and date. The regulator announces every
consultation, decision, determination and licence modification as a news
item, and the item page carries the summary and links the papers. robots.txt
allows the list and the item pages (it closes only the filtered views of the
list, which are not used, and names a dozen SEO crawlers).

A title filter keeps electricity items: SONI and NIE Networks price controls
and licences, network tariffs and their structure, connection and firm access
arrangements, flexibility, generation and supply licences, renewables and
retail market rules. Gas network and water items, newsletters and consumer
campaigns are dropped.

Not read: the publications and consultations libraries, which repeat the same
items as bare file lists. All-island wholesale market decisions are published
by the SEM Committee and read by the `sem_committee` adapter.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, UpstreamUnavailable, MAX_CONTENT_CHARS)

INSTITUTION = "Utility Regulator (Northern Ireland)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.uregni.gov.uk"
LISTING = f"{BASE}/news"
MAX_ITEMS = 20
# Twenty rows a page, about half of them gas, water or consumer items.
PAGES = 2

_ITEM = re.compile(r"^/news-centre/([^/?#]+)$")
_ELECTRICITY = re.compile(
    r"electricity|\bSONI\b|NIE Networks|\bNIE\b|Power NI|generation licen|supply licen|"
    r"transmission|distribution (network|code|licen)|grid code|\bSEM\b|single electricity market|"
    r"capacity (market|auction)|system services|synchronous condenser|flexibility|firm access|"
    r"connection|tariff|price control|\bRP7\b|\bRP8\b|renewable|wind|solar|storage|interconnector|"
    r"Moyle|demand side|smart meter|energy strategy|retail energy market|energy (supplier|market)|"
    r"security of supply|generation", re.I)
_OFF_TOPIC = re.compile(
    r"newsletter|charter|extra support|lived experience|\bgas\b|firmus|Phoenix|SGN|Evolve|GNI|"
    r"NI Water|\bwater\b|sewerage|recruit|board member|appoint|annual report|forward work programme|"
    r"corporate strategy", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    rows = 0
    for page in range(PAGES):
        try:
            r = get_with_retry(session, LISTING if page == 0 else f"{LISTING}?page={page}", timeout=45)
        except CollectorError:
            if page == 0:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("article.search-result"):
            a = row.select_one("h3 a[href]")
            m = _ITEM.match(a["href"]) if a else None
            if not m:
                continue
            rows += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            if (_OFF_TOPIC.search(title) and not re.search(r"electricity", title, re.I)) \
                    or not _ELECTRICITY.search(title):
                continue
            stamp = row.select_one("time[datetime]")
            day = stamp["datetime"][:10] if stamp else ""
            sid = f"uregni-{slugify(m.group(1))}"
            found.setdefault(sid, Candidate(
                sid, title, day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
                urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not rows:
        raise CollectorError("Utility Regulator news list showed no rows: markup changed")
    if not found:
        raise QuietRun("No electricity item on the Utility Regulator news pages this run")
    return LISTING, list(found.values())[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    text = html_to_text(body)
    if len(text.strip()) < 200:
        raise CollectorError(f"Utility Regulator page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
