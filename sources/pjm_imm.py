"""Monitoring Analytics — the Independent Market Monitor for PJM.

Two listings, both plain server-rendered HTML with PDF links. The filings
page carries the IMM's protests, comments and answers on live FERC dockets,
which is the most direct commentary on PJM market design published anywhere.
The State of the Market page carries the quarterly and annual reports.

The monitor is not a decision-maker, so nothing here changes a rule by
itself. It is here because a market designer reading at a distance learns
more from the monitor's protest than from the press release it answers.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, UpstreamUnavailable, get_with_retry, extract_pdf_text,
                  looks_like_pdf, slugify, MAX_CONTENT_CHARS)
from sources.us_common import REGION, MONITOR_NOISE  # noqa: F401

INSTITUTION = "Monitoring Analytics (PJM IMM)"
DOCUMENT_TYPE = "MARKET_MONITOR"

BASE = "https://www.monitoringanalytics.com"
_YEAR = date.today().year
FILINGS = f"{BASE}/filings/{_YEAR}.shtml"
SOM = f"{BASE}/reports/PJM_State_of_the_Market/{_YEAR}.shtml"
# Filing rows stamp the date after the title, US-style.
_STAMP = re.compile(r"\b(\d{2})\.(\d{2})\.(20\d{2})\b")


def _date(text: str) -> str | None:
    m = _STAMP.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(3)}-{m.group(1)}-{m.group(2)}", "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _harvest(session, listing, prefix, found):
    r = get_with_retry(session, listing, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select('a[href$=".pdf"]'):
        href = a["href"]
        row = a.find_parent("tr") or a.parent
        row_text = " ".join(row.get_text(" ", strip=True).split())
        title = " ".join(a.get_text(" ", strip=True).split()) or row_text
        title = re.sub(r"\s*\(PDF\)\s*", " ", title).strip()
        # The State of the Market report is published as a 28MB whole plus
        # fifteen section PDFs. The whole is too large to fetch every run and
        # too broad to analyse; Section 2, the monitor's recommendations, is
        # the part that argues for design change. Take that and drop the rest.
        if prefix.endswith("som"):
            if not re.search(r"-sec2\.pdf$", href, re.I):
                continue
            title = f"PJM State of the Market {_YEAR}: recommendations"
        elif re.search(r"-(?:toc|preface|sec\d+|appendix)\.pdf$", href, re.I):
            continue
        # A link whose own text is empty falls back to its row, which on the
        # report pages is the entire table. Derive a title from the file name
        # instead of storing a page of link labels.
        if len(title) < 12 or len(title) > 220:
            stem = href.rstrip("/").split("/")[-1].replace(".pdf", "")
            title = " ".join(stem.replace("_", " ").replace("-", " ").split())[:200]
        url = urljoin(listing, href)
        sid = f"{prefix}-{slugify(href.rstrip('/').split('/')[-1].replace('.pdf', ''))}"
        found.setdefault(sid, Candidate(sid, title, _date(row_text), url))


def discover(session):
    found: dict[str, Candidate] = {}
    problems = []
    for listing, prefix in ((FILINGS, "pjmimm-filing"), (SOM, "pjmimm-som")):
        try:
            _harvest(session, listing, prefix, found)
        except Exception as exc:
            problems.append(f"{listing}: {exc}")
    if not found:
        raise UpstreamUnavailable("Monitoring Analytics listings carried no documents: " + "; ".join(problems))
    items = sorted(found.values(), key=lambda c: c.publication_date or "", reverse=True)
    return f"{FILINGS} + {SOM}", items


def is_out_of_scope(candidate: Candidate) -> bool:
    # Everything the IMM files is about PJM market design, so the market-design
    # keyword test would only lose documents. Only the monitor noise list runs.
    return bool(MONITOR_NOISE.search(candidate.title))


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=120)
    if not looks_like_pdf(r):
        raise UpstreamUnavailable(f"expected a PDF at {candidate.url}")
    return extract_pdf_text(r.content)[:MAX_CONTENT_CHARS]
