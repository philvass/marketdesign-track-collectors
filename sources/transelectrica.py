"""Transelectrica — the Romanian electricity transmission system operator.

Discovery: the "Noutăți" list on web.transelectrica.ro, one server-rendered
table in which each row is a PDF notice with its title and date. That host's
robots.txt allows everything. The main site, www.transelectrica.ro, answers
its robots.txt with a server error, so nothing is read from it; in particular
its "Documente pentru discuție" and "Consultări" pages are left alone, and
public debates are picked up from the notices that announce them here.

The list mixes market notices with everything else the company must publish.
Kept: public debates on operational procedures (balancing and system
services, demand flexibility), capacity allocation in the grid, imbalance
settlement rules, tariffs, network codes. Dropped by title: expropriation
decisions and site plans for individual lines, sales of scrap and waste,
recruitment and selection, questionnaires, and the monthly notices that
imbalance calculations have been completed.

Romanian only; the notices are not translated.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  MAX_CONTENT_CHARS)

INSTITUTION = "Transelectrica"
DOCUMENT_TYPE = "TSO"

LISTING = "https://web.transelectrica.ro/noutati/lista_noutati.html"
SCAN_ROWS = 80        # the table goes back years, newest first
MAX_ITEMS = 20

_FILE = re.compile(r"noutati/(\d+)_(20\d{2})\.(\d{2})\.(\d{2})_[\d-]+\.pdf$", re.I)
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_DROP = re.compile(
    r"expropriere|plan\w* de amplasament|valorificare|deșeu|deseu|selecți|selecti|recrutare|"
    r"chestionar|scrisoare de așteptări|finalizarea calcul|acordului de mediu|etapei de încadrare|"
    r"consumului propriu tehnologic|trofeu|fraud|inaugurare|mărirea capacit|anunț publicitar|anunt publicitar|"
    r"reconductorare|proiectul .*LEA|acord de mediu|aviz de mediu|impact\w* asupra mediului|"
    r"închiriere|inchiriere|licitați\w+ (?:publică|deschisă) .*vânzare|post\w* vacant|concurs|"
    r"AGA\b|adunarea generală|dividend|rezultate financiare|sponsoriz|burs", re.I)


def discover(session):
    r = get_with_retry(session, LISTING, timeout=60)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    rows = 0
    for tr in soup.select("tr"):
        a = tr.find("a", href=True)
        m = _FILE.search(a["href"]) if a else None
        if not m:
            continue
        rows += 1
        if rows > SCAN_ROWS or len(found) >= MAX_ITEMS:
            break
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or _DROP.search(title):
            continue
        cells = tr.find_all("td")
        d = _DATE.search(cells[-1].get_text() if len(cells) > 1 else "")
        date = (f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d
                else f"{m.group(2)}-{m.group(3)}-{m.group(4)}")
        sid = f"transelectrica-{m.group(1)}"
        found.setdefault(sid, Candidate(sid, title, date, urljoin(LISTING, a["href"])))
    if not rows:
        raise CollectorError("Transelectrica notices table listed no PDF rows: markup changed")
    if not found:
        raise CollectorError("Transelectrica: every notice was filtered out; check the title filter")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=90)
    text = extract_pdf_text(r.content).strip()
    if len(text) < 150:
        text = (f"{text}\n\nNotă: anunțul este un document scanat fără text extractibil; "
                "textul integral se află la adresa sursă. (Note: the notice is a scanned "
                "document with no extractable text; see the source URL for the full text.)")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
