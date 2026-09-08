"""NYISO — New York ISO.

Discovery: the press-release asset publisher at /view-press. The listing
carries titles but no dates, so the date is read from the article page.
Operational notices (energy watches and warnings, heat, records) and the
annual Power Trends report are dropped by title; what remains is the
occasional capacity-market, pricing or FERC-filing release.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, get_with_retry, html_to_text, slugify, MAX_CONTENT_CHARS
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "NYISO"
DOCUMENT_TYPE = "ISO"

BASE = "https://www.nyiso.com"
LISTING = f"{BASE}/view-press"
_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|"
                   r"October|November|December)\s+(\d{1,2}),\s+(20\d{2})", re.I)

# Dates live on the article page, not in the listing.
DATE_REFINED_ON_FETCH = True


def _clean_title(t: str) -> str:
    t = " ".join(t.split())
    return re.sub(r"^\s*press release\s*\|\s*", "", t, flags=re.I)


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for a in soup.select("a.asset-title[href]"):
        title = _clean_title(a.get_text(" ", strip=True))
        if len(title) < 12:
            continue
        url = urljoin(BASE, a["href"]).split("?", 1)[0]
        sid = f"nyiso-{slugify(url.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, None, url))
    if not found:
        raise UpstreamUnavailable("NYISO press listing carried no releases")
    return LISTING, list(found.values())


# The asset publisher mixes NYISO's own releases with press coverage, which
# arrives titled "OUTLET | headline". Coverage is never a primary source.
_COVERAGE = re.compile(r"^[A-Z0-9 .&'’-]{3,40}\s*\|")


def is_out_of_scope(candidate: Candidate) -> bool:
    return bool(_COVERAGE.match(candidate.title)) or not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = _clean_title(h1.get_text(" ", strip=True))
        if len(title) > 8:
            candidate.title = title
    main = soup.find("main") or soup
    text = html_to_text(main)
    m = _DATE.search(text[:4000])
    if m and not candidate.publication_date:
        try:
            candidate.publication_date = datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
        except ValueError:
            pass
    return text[:MAX_CONTENT_CHARS]
