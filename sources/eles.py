"""ELES — the Slovenian electricity transmission system operator.

Discovery: two server-rendered news lists on eles.si. The site's robots.txt
forbids its module and resource folders (which is where its RSS feed is
served from, so the feed is not used) but not the news pages.

1. Novice za poslovne uporabnike, category 182: notices to market
   participants. This is where ELES announces changes to the terms for
   balancing service providers, its entry into the European balancing
   platforms, capacity-calculation go-lives and tenders for ancillary
   services. The unfiltered list is mostly daily notices of capacity
   allocation limits on single borders; the category leaves those out.
2. Novice: the company's general news, which carries the market items written
   for the public (the multi-NEMO arrangement, network-charge analyses).

Slovenian is read because the English site has only a part of the notices.
Operational notices (capacity limits, IT maintenance, auction results) and
corporate items (annual report, awards, sponsorship) are dropped by title.

Not read: the "Tekoča obvestila" list on the implementation of European
network codes, which has not been updated since 2022.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  MAX_CONTENT_CHARS)

INSTITUTION = "ELES"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.eles.si"
LISTS = (f"{BASE}/obratovanje/novice-za-poslovne-uporabnike/CategoryID/182",
         f"{BASE}/novice")
MAX_ITEMS = 20

_ARTICLE = re.compile(r"/ArticleID/(\d+)(?:/|$)")
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_DROP = re.compile(
    r"omejevanje dodelitve|vzdrževaln\w+ del|moteno delovanje|rezultati dražbe|nedelovanj|izpad|"
    r"letno poročilo|polletno|nagrad|priznanj|sponzor|donacij|imenovan|direktor\w* družbe|"
    r"nadzorn\w+ svet|obletnic|konferenc|vesoljsk|neurje|dan odprtih vrat|štipendij|zaposl", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    blocks = 0
    for url in LISTS:
        try:
            r = get_with_retry(session, url, timeout=60)
        except CollectorError as exc:
            errors.append(str(exc))
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for block in soup.select(".single-news-block"):
            a = block.select_one("h5 a[href]") or block.select_one('a[href*="/ArticleID/"]')
            m = _ARTICLE.search(a["href"]) if a else None
            if not m:
                continue
            blocks += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            if not title or _DROP.search(title):
                continue
            when = block.select_one(".single-news-date")
            d = _DATE.search(when.get_text() if when else "")
            sid = f"eles-{m.group(1)}"
            found.setdefault(sid, Candidate(
                sid, title,
                f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None,
                a["href"]))
    if not blocks:
        raise CollectorError("ELES news lists yielded no articles: markup changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise CollectorError("ELES: every listed article was filtered out; check the title filter")
    # Both lists pin items at the top, so order by date before capping.
    items = sorted(found.values(), key=lambda c: c.publication_date or "", reverse=True)
    return " + ".join(LISTS), items[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".news_detail") or soup.select_one(".news-blocks")
    if body is None:
        raise CollectorError(f"ELES article has no body block: {candidate.url}")
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"ELES article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
