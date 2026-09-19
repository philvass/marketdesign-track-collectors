"""SPP MMU — the Market Monitoring Unit of the Southwest Power Pool (US).

SPP's monitor is internal (unlike MISO/NYISO/ISO-NE/ERCOT, whose monitor is
Potomac Economics, and PJM, whose monitor is Monitoring Analytics). Its reports
are published on spp.org under the market-monitoring section as document
collections, each addressed by a numeric id: State of the Market (annual and
quarterly), the recurring reliability/market reviews, and MMU comments and
filings.

Discovery: each collection page (/spp-documents-filings/?id=NNNN) is plain
server-rendered HTML — a list of `div.doc.doc-pdf` blocks, each with the PDF
link (its text is the title), a size, and a `<small>` publication date. The
monitor's reports are the product, so only the general monitor-noise filter is
applied, not the market-design title gate.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, UpstreamUnavailable, CollectorError, get_with_retry,
                  extract_pdf_text, looks_like_pdf, slugify, MAX_CONTENT_CHARS)
from sources.us_common import REGION, MONITOR_NOISE  # noqa: F401

INSTITUTION = "SPP Market Monitoring Unit"
DOCUMENT_TYPE = "MARKET_MONITOR"

BASE = "https://www.spp.org"

# The report collections linked from spp.org/markets-operations/market-monitoring/.
# id -> the label the market-monitoring page gives the collection (used to
# prefix titles so a bare "2026 Q1 Report" says which series it belongs to).
COLLECTIONS = {
    "18510": "MMU Report",
    "18512": "Annual State of the Market",
    "18590": "Quarterly State of the Market",
    "25496": "Frequently Constrained Area",
    "127892": "MMU Comments",
}

_MONTHS = ("Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
           "|January|February|March|April|June|July|August|September|October|November|December")
_DATE_DMY = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})\s+(20\d{{2}})\b")
_DATE_MY = re.compile(rf"\b({_MONTHS})\s+(20\d{{2}})\b")


def _parse_date(text: str) -> str | None:
    text = " ".join((text or "").split())
    m = _DATE_DMY.search(text)
    if m:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt).date().isoformat()
            except ValueError:
                pass
    m = _DATE_MY.search(text)
    if m:
        for fmt in ("%b %Y", "%B %Y"):
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)}", fmt).date().isoformat()
            except ValueError:
                pass
    return None


def discover(session):
    found: dict[str, Candidate] = {}
    problems = []
    for cid, label in COLLECTIONS.items():
        url = f"{BASE}/spp-documents-filings/?id={cid}"
        try:
            r = get_with_retry(session, url, timeout=60)
        except CollectorError as exc:
            problems.append(f"id={cid}: {exc}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for block in soup.select("div.doc"):
            a = block.select_one('a[href$=".pdf"]')
            if not a:
                continue
            title = " ".join(a.get_text(" ", strip=True).split())
            if not title or len(title) < 6:
                continue
            small = block.find("small")
            date = _parse_date(small.get_text(" ", strip=True)) if small else None
            href = urljoin(BASE, a["href"])
            sid = f"spp-mmu-{slugify(href.rstrip('/').split('/')[-1].replace('.pdf', ''))}"
            full = title if title.lower().startswith(("spp", "state of the market")) else f"{label}: {title}"
            found.setdefault(sid, Candidate(sid, full, date, href))
    if not found:
        raise UpstreamUnavailable("SPP MMU collections returned no documents: " + "; ".join(problems))
    return f"{BASE}/markets-operations/market-monitoring/", list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    t = candidate.title.lower()
    # Slide decks and the syntax help file are not substantive reports.
    if "presentation" in t or "search-syntax" in candidate.url:
        return True
    return bool(MONITOR_NOISE.search(candidate.title))


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=120)
    if not looks_like_pdf(r):
        raise UpstreamUnavailable(f"expected a PDF at {candidate.url}")
    return extract_pdf_text(r.content)[:MAX_CONTENT_CHARS]
