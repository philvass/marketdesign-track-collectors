"""SPP — Southwest Power Pool.

Discovery: the press-release listing, where each item is a div.news-item
carrying its own date, headline and lead. Articles live under /news-list/,
whose index page returns a 500 on its own but whose article pages are fine.

SPP matters to a European reader mainly for Markets+, the day-ahead market
it is building for the West in competition with the CAISO extended day-ahead
market. Transmission-project and personnel news, which is most of the feed,
is dropped by the shared US title filter.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, get_with_retry, html_to_text, slugify, MAX_CONTENT_CHARS
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "SPP"
DOCUMENT_TYPE = "ISO"

BASE = "https://spp.org"
LISTING = f"{BASE}/newsroom/press-releases/"
_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|"
                   r"October|November|December)\s+(\d{1,2}),\s+(20\d{2})", re.I)


def _date(text: str) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for item in soup.select("div.news-item"):
        a = item.select_one("h2.title-news a[href], a[href*='/news-list/']")
        if not a:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if len(title) < 12:
            continue
        url = urljoin(BASE, a["href"])
        sid = f"spp-{slugify(url.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, _date(item.get_text(" ", strip=True)[:120]), url))
    if not found:
        raise UpstreamUnavailable("SPP press-release listing carried no items")
    return LISTING, list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    return not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    # The page has no <main>; falling back to the document body would drag in
    # the whole navigation, which is longer than most releases.
    main = soup.select_one(".news-content") or soup.select_one(".page-content") or soup
    text = html_to_text(main)
    if not candidate.publication_date:
        candidate.publication_date = _date(text[:600])
    return text[:MAX_CONTENT_CHARS]
