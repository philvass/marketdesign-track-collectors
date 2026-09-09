"""Potomac Economics — market monitor for MISO, NYISO, ISO-NE and ERCOT.

One firm holds the monitoring mandate for four RTOs, so a single adapter
covers most of the American market-monitoring literature, including ERCOT,
whose own site cannot be collected.

Discovery: the document library, queried per market and restricted to the
current and previous publication year. The library is a plain table with the
market and year in their own cells, and the PDF behind a Download link.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, UpstreamUnavailable, CollectorError, get_with_retry,
                  extract_pdf_text, looks_like_pdf, slugify, MAX_CONTENT_CHARS)
from sources.us_common import REGION, MONITOR_NOISE  # noqa: F401

INSTITUTION = "Potomac Economics"
DOCUMENT_TYPE = "MARKET_MONITOR"

BASE = "https://www.potomaceconomics.com"
LIBRARY = f"{BASE}/document-library/"
MARKETS = ["MISO", "NYISO", "ISO-NE", "ERCOT"]

# The library dates documents by publication year only, so the day is never
# known. Reports are annual or quarterly and the freshness gate is measured in
# days, which would baseline all of them: widen the window to a year.
MAX_AGE_DAYS = 400

# Most file names carry the real publication date, which is better than the
# library's year-only cell: 5-13-2026, 03-17-25 and 2026-05-13 all appear.
_FILE_DATE = re.compile(r"(?:^|[-_])(\d{1,2})[-_](\d{1,2})[-_](20\d{2}|\d{2})(?:$|[-_.])")


def _date_from_name(url: str) -> str | None:
    stem = url.rstrip("/").split("/")[-1].replace(".pdf", "")
    m = _FILE_DATE.search(stem)
    if not m:
        return None
    month, day, year = m.group(1), m.group(2), m.group(3)
    if len(year) == 2:
        year = f"20{year}"
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def discover(session):
    years = [date.today().year, date.today().year - 1]
    found: dict[str, Candidate] = {}
    problems = []
    for market in MARKETS:
        for year in years:
            try:
                r = get_with_retry(session, LIBRARY, timeout=60,
                                   params={"filtermarket": market, "filteryear": str(year)})
            except CollectorError as exc:
                problems.append(f"{market} {year}: {exc}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for row in soup.select("table.library-table tbody tr"):
                a = row.select_one('a[href$=".pdf"]')
                h3 = row.select_one("h3")
                if not a or not h3:
                    continue
                title = " ".join(h3.get_text(" ", strip=True).split())
                if not title:
                    continue
                url = urljoin(BASE, a["href"])
                sid = f"potomac-{slugify(url.rstrip('/').split('/')[-1].replace('.pdf', ''))}"
                # Fall back to the start of the library's publication year
                # when the file name carries no date, rather than inventing one.
                published = _date_from_name(url) or f"{year}-01-01"
                found.setdefault(sid, Candidate(sid, f"{market}: {title}", published, url))
    if not found:
        raise UpstreamUnavailable("Potomac Economics library returned no documents: " + "; ".join(problems))
    return f"{LIBRARY} ({', '.join(MARKETS)})", list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    t = candidate.title.lower()
    # Slide decks restate the report they accompany.
    if "presentation" in t:
        return True
    return bool(MONITOR_NOISE.search(candidate.title))


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=120)
    if not looks_like_pdf(r):
        raise UpstreamUnavailable(f"expected a PDF at {candidate.url}")
    return extract_pdf_text(r.content)[:MAX_CONTENT_CHARS]
