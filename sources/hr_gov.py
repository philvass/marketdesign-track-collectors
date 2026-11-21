"""Croatian Ministry of Economy (Ministarstvo gospodarstva), which holds the
energy portfolio through its energy directorate.

Discovery: the ministry's "Vijesti" listing on mingo.gov.hr, three pages of ten
server-rendered entries, each a headline and a date. The site's robots.txt
forbids a single unrelated path. Croatian is the only complete edition.

The ministry prepares the Electricity Market Act and its amendments, the
government's price-intervention decrees, renewable support rules and the
national energy plan, and announces them here among trade missions, consumer
prices and weekly fuel prices. The listing shows headlines only, so the
filter works on the headline: it keeps items that name electricity, energy
policy, renewables or the energy institutions, and drops fuel-price notices.
It is therefore a little wider than electricity alone; an energy headline
that turns out to be about gas is left to the analysis step.

Not read: e-Savjetovanja, the central government consultation portal, which
is a separate site covering every ministry.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "Ministry of Economy (Croatia)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://mingo.gov.hr"
LISTING = f"{BASE}/vijesti/8"
PAGES = 3

_ITEM = re.compile(r"/vijesti/[^/?#]+/(\d+)$")
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_ENERGY = re.compile(
    r"električn|elektroenerg|energetsk|energetik|energij|obnovljiv|sunčan\w+ elektran|"
    r"vjetroelektran|nuklearn|tržišt\w+ (?:električne|energije)|opskrb\w+ energ|"
    r"jamstv\w+ podrijetla|\bHOPS\b|\bHERA\b|\bHROTE\b|\bHEP\b|\bCROPEX\b|\bNECP\b", re.I)
_DROP = re.compile(r"cijene goriva|energetsk\w+ obnov\w+ zgrad|razdjelnik", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    entries = 0
    for page in range(1, PAGES + 1):
        url = LISTING if page == 1 else f"{LISTING}?trazi=1&page={page}"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if page == 1:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".news_item"):
            a = item.find("a", href=True)
            m = _ITEM.search(a["href"]) if a else None
            if not m:
                continue
            entries += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            if not title or _DROP.search(title) or not _ENERGY.search(title):
                continue
            when = item.select_one(".date")
            d = _DATE.search(when.get_text() if when else "")
            sid = f"hr_gov-{m.group(1)}"
            found.setdefault(sid, Candidate(
                sid, title,
                f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None,
                urljoin(BASE, a["href"])))
    if not entries:
        raise CollectorError("Croatian ministry news listing carried no entries: markup changed")
    # Thirty headlines of an economy ministry with no energy item among them
    # is an ordinary fortnight, not a defect.
    if not found:
        raise QuietRun("No energy item in the Croatian ministry news this run")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".article_left") or soup.select_one(".article_content")
    if body is None:
        raise CollectorError(f"Croatian ministry article has no body: {candidate.url}")
    for extra in body.select(".article_prev_next"):
        extra.decompose()
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"Croatian ministry article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
