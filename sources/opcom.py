"""OPCOM — the Romanian electricity and gas market operator.

Discovery: the operator's own announcements page ("Anunţuri - Ştiri / OPCOM")
in Romanian, a single server-rendered list in which each entry is a date and
one or two sentences, usually linking either a PDF (a procedure, a manual) or
the section of the site where the details were posted. The site's robots.txt
forbids nothing. Romanian is read because announcements appear there first
and some are never translated.

This is where OPCOM announces public consultations on its market documents,
revised procedures for the day-ahead and intraday markets, decoupling
manuals and new trading arrangements. The monthly publication of the average
day-ahead price, lists of non-compliant participants, training invitations
and gas-market notices are dropped by text.

OPCOM has no article pages. The record is the announcement itself, followed
by the text of the linked PDF when there is one, or by the head of the
linked section page (where the consultation documents are listed). The
entries have no identifier of their own, so the id is the date plus a digest
of the announcement text.

Not read: the per-market announcement pages (results, programmes, delivery
notices) and the "Consultare publică" settlement page, untouched since 2022.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  extract_pdf_text, looks_like_pdf, MAX_CONTENT_CHARS)

INSTITUTION = "OPCOM"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://www.opcom.ro"
LISTING = f"{BASE}/anunturi-stiri-pp/ro/1"
SCAN = 40
MAX_ITEMS = 15
SECTION_CHARS = 4000

_DATE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_DROP = re.compile(
    r"prețul mediu ponderat|pretul mediu ponderat|nu au îndeplinit obligația|sesiun\w+ de instruire|"
    r"gaze naturale|seminar|program de lucru|sărbători|mentenanță|mentenanta|întrerupere", re.I)

_TEXT: dict[str, str] = {}


def discover(session):
    r = get_with_retry(session, LISTING, timeout=60)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    entries = 0
    for li in soup.select("#contp li"):
        whole = " ".join(li.get_text(" ", strip=True).split())
        d = _DATE.match(whole)
        if not d:
            continue
        entries += 1
        if entries > SCAN or len(found) >= MAX_ITEMS:
            break
        text = whole[d.end():].strip(" -–:")
        if len(text) < 15 or _DROP.search(text):
            continue
        date = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}"
        a = li.find("a", href=True)
        url = urljoin(BASE, quote(a["href"], safe="/:?=&%#")) if a else LISTING
        digest = hashlib.sha1(text.lower().encode()).hexdigest()[:10]
        sid = f"opcom-{date.replace('-', '')}-{digest}"
        _TEXT[sid] = text
        title = text if len(text) <= 200 else text[:197].rsplit(" ", 1)[0] + "…"
        found.setdefault(sid, Candidate(sid, title, date, url))
    if not entries:
        raise CollectorError("OPCOM announcements page listed no dated entries: markup changed")
    if not found:
        raise CollectorError("OPCOM: every announcement was filtered out; check the text filter")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    notice = _TEXT.get(candidate.source_id, candidate.title)
    parts = [f"Anunț OPCOM din {candidate.publication_date}", notice]
    if candidate.url != LISTING and candidate.url.startswith(BASE):   # never follow off-site links
        try:
            r = get_with_retry(session, candidate.url, timeout=90)
            if looks_like_pdf(r):
                parts.append("[Document atașat]\n" + extract_pdf_text(r.content).strip())
            else:
                r.encoding = "utf-8"
                section = BeautifulSoup(r.text, "html.parser").select_one("#contp")
                if section is not None:
                    parts.append("[Începutul secțiunii la care trimite anunțul / head of the "
                                 "linked section]\n" + html_to_text(section)[:SECTION_CHARS])
        except CollectorError:
            pass
    if len(parts) == 2:
        parts.append("Notă: OPCOM publică anunțurile ca text scurt, fără pagină de articol; acesta "
                     "este textul integral al anunțului. (Note: OPCOM publishes announcements as "
                     "short text without an article page; this is the full announcement.)")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
