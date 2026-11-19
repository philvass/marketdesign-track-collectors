"""SPRK — Sabiedrisko pakalpojumu regulēšanas komisija, the Latvian Public
Utilities Commission and national energy regulator.

Discovery: the server-rendered news listing on sprk.gov.lv, narrowed with the
site's own sector filter to "Elektroenerģija". SPRK also regulates gas, heat,
water, waste, post and telecoms, and the filter is the commission's own
classification, which is more reliable than keywords. Each card carries the
date and the sector badge. Latvian is read because the English edition
translates only part of the news. robots.txt allows the listing and the
articles (it closes admin, search and the print-to-PDF paths).

The commission announces here its consultations and decisions on network
tariff methodologies, system-service and balancing rules, connection rules and
its market monitoring. The first two pages of the filtered list are read.

Not read: the register of individual council decisions, which is mostly
licences and tariffs of single district-heating and water companies.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "SPRK (Latvian Public Utilities Commission)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.sprk.gov.lv"
# 193 is the "Elektroenerģija" sector in the listing's own filter form.
LISTING = f"{BASE}/lv/jaunumi?category%5B193%5D=193"
PAGES = 2
MAX_ITEMS = 20

_ITEM = re.compile(r"/lv/jaunums/([^/?#]+)")


def discover(session):
    found: dict[str, Candidate] = {}
    rows_seen = 0
    for page in range(PAGES):
        url = LISTING if page == 0 else f"{LISTING}&page={page}"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if page == 0:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select(".views-row"):
            a = row.select_one("h2 a[href]")
            m = _ITEM.search(a["href"]) if a else None
            if not m:
                continue
            rows_seen += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            stamp = row.select_one("time[datetime]")
            day = (stamp["datetime"][:10] if stamp else "")
            sid = f"sprk-{slugify(m.group(1))}"
            found.setdefault(sid, Candidate(
                sid, title, day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
                urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not rows_seen:
        raise CollectorError("SPRK news listing showed no article cards: markup or filter changed")
    return LISTING, list(found.values())[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("article") or soup.select_one("main") or soup.select_one("#main-content") or soup
    text = html_to_text(body)
    if len(text.strip()) < 200:
        raise CollectorError(f"SPRK page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
