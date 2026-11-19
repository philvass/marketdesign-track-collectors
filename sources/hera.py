"""HERA — the Croatian Energy Regulatory Agency.

Discovery: the "Novosti" list on the agency's Croatian home page, a plain
server-rendered table in which every entry has a date written in words, a
headline, a short official summary and usually a "Više..." link to a notice
page or a PDF. The site's robots.txt allows everything. The Croatian edition
is read because the English one is a small, late subset.

The list carries what matters here: decisions of the governing council (press
releases after each session), tariff decisions and methodologies for
guaranteed supply and network use, connection charges, the framework for
self-consumption and storage, and the opening of public consultations.

HERA also regulates gas, heat and oil. An entry is dropped when its headline
is about gas or heat and does not mention electricity; council press releases
cover all sectors and are kept whole.

When an entry has no detail link, the record carries the summary from the list
and the text of the first document it links on hera.hr, if any.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  extract_pdf_text, looks_like_pdf, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "HERA (Croatia)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.hera.hr/hr/html/"
LISTING = f"{BASE}index.html"
MAX_ITEMS = 20

_MONTHS = {"siječnja": 1, "veljače": 2, "ožujka": 3, "travnja": 4, "svibnja": 5, "lipnja": 6,
           "srpnja": 7, "kolovoza": 8, "rujna": 9, "listopada": 10, "studenoga": 11,
           "studenog": 11, "prosinca": 12}
_DATE = re.compile(r"(\d{1,2})\.\s*([a-zčćšžđ]+)\s+(20\d{2})", re.I)
_OTHER_SECTOR = re.compile(r"plin|toplinsk|naft|biogoriv", re.I)
_ELECTRICITY = re.compile(r"električn|elektroenerg|obnovljiv|skladištenje energije|baterij", re.I)
_DROP = re.compile(r"^poziv za sjednicu|hrvatskog radija|registra stanovništva|radionic|"
                   r"godišnji skup", re.I)

_META: dict[str, str] = {}


def _date(raw: str) -> str | None:
    m = _DATE.search(raw or "")
    month = _MONTHS.get(m.group(2).lower()) if m else None
    return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}" if month else None


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    entries = 0
    for td in soup.select("td"):
        when, head = td.select_one("p.calendar"), td.find("h6")
        if not when or not head or td.find("td"):      # skip the outer layout cell
            continue
        entries += 1
        title = " ".join(head.get_text(" ", strip=True).split())
        if not title or _DROP.search(title):
            continue
        if _OTHER_SECTOR.search(title) and not _ELECTRICITY.search(title):
            continue
        date = _date(when.get_text(" ", strip=True))
        links = [a for a in td.find_all("a", href=True)]
        more = next((a for a in links if a.get_text(strip=True).lower().startswith("više")), None)
        own = next((a for a in links if not a["href"].startswith("http")
                    or "hera.hr" in a["href"]), None)
        target = more or own
        if target is not None:
            url = urljoin(BASE, target["href"])
            stem = re.sub(r"\.(html?|pdf)$", "", url.rstrip("/").split("/")[-1], flags=re.I)
            sid = f"hera-{slugify(stem)}"
        else:
            url = LISTING
            sid = f"hera-{date or 'undated'}-{slugify(title, 50)}"
        if sid in found:
            continue
        _META[sid] = "\n".join(" ".join(p.get_text(" ", strip=True).split())
                               for p in td.find_all("p")
                               if "calendar" not in (p.get("class") or [])
                               and not p.get_text(strip=True).lower().startswith("više"))
        found[sid] = Candidate(sid, title, date, url)
        if len(found) >= MAX_ITEMS:
            break
    if not entries:
        raise CollectorError("HERA home page listed no news entries: markup changed")
    if not found:
        raise CollectorError("HERA: every entry was filtered out; check the sector filter")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    parts = [candidate.title]
    lead = _META.get(candidate.source_id, "").strip()
    if lead:
        parts.append(lead)
    if candidate.url != LISTING:
        r = get_with_retry(session, candidate.url, timeout=90)
        if looks_like_pdf(r):
            parts.append(extract_pdf_text(r.content).strip())
        else:
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["noscript", "title"]):
                tag.decompose()
            parts.append(html_to_text(soup.body or soup))
    text = "\n\n".join(p for p in parts if p)
    if len(text) < 200:
        raise CollectorError(f"HERA entry yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
