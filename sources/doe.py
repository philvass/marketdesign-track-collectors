"""US DOE — Department of Energy.

Discovery: the newsroom (energy.gov/newsroom) is a Drupal listing of
`views-row` cards, each with a display-date <time> and a title link under
/articles/ (or an office sub-path like /em/articles/). Server-rendered, so a
plain request is enough.

DOE is a broad department and most of its newsroom is not wholesale
market design — the US title filter and TRACK's US significance gate keep only
the grid / transmission / interconnection / market-policy items, which are few.
That sparseness is expected: DOE is a policy body, not a market operator.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, get_with_retry, html_to_text, slugify, MAX_CONTENT_CHARS
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "US DOE"
DOCUMENT_TYPE = "GOVERNMENT"

BASE = "https://www.energy.gov"
LISTING = f"{BASE}/newsroom"
MAX_ITEMS = 40


def _date(iso: str) -> str | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return None


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for row in soup.select(".views-row"):
        link = row.select_one(".views-field-title a[href]")
        if not link:
            continue
        href = link.get("href", "")
        if "/articles/" not in href:
            continue
        title = " ".join(link.get_text(" ", strip=True).split())
        time_el = row.select_one(".views-field-field-display-date time[datetime]")
        date = _date(time_el["datetime"]) if time_el else None
        url = urljoin(BASE, href)
        sid = f"doe-{slugify(href.rstrip('/').split('/')[-1])}"
        if title:
            found.setdefault(sid, Candidate(sid, title, date, url))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise UpstreamUnavailable("DOE newsroom carried no article cards (layout may have changed)")
    return LISTING, list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    return not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        t = " ".join(h1.get_text(" ", strip=True).split())
        if len(t) > 8:
            candidate.title = t
    main = soup.find("main") or soup.find("article") or soup
    return html_to_text(main)[:MAX_CONTENT_CHARS]
