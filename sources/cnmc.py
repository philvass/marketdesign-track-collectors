"""CNMC (cnmc.es) — Spanish competition and markets regulator.

Spain is the largest European market with no other regulator source here, so
discovery reads three routes and a quiet one is never a failure:

1. The energy consultations listing. This is the route that matters: every
   proposed circular, resolution and operating-procedure change goes out to
   consultation here, properly titled, energy only, newest first. The listing
   carries no dates, so the first few pages are read during discovery to date
   them; fetch_content reuses those pages rather than requesting them twice.
2. The press notes on the energy sector page, which are dated in the listing.
3. The site RSS feed, filtered to energy items. It was once the only route and
   is why this source kept reporting itself unavailable: the feed is a ten-item
   firehose of every council session and notification the whole commission
   logs, so most runs it holds no energy item at all, and an energy item can
   scroll off it between two runs. It is kept as a bonus, never relied on.
"""
from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from urllib.parse import urljoin

from core import (Candidate, CollectorError, get_with_retry,
                  extract_pdf_text, html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "CNMC"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.cnmc.es"
CONSULTATIONS = f"{BASE}/consultas-publicas/energia"
SECTOR = f"{BASE}/sectores-que-regulamos/energia"
FEED = f"{BASE}/rss.xml"

# The listing runs newest first and a consultation stays open for weeks, so the
# head of it is all a monitor needs; the rest closed long ago.
MAX_CONSULTATIONS = 6

ENERGY = re.compile(
    r"\b(electric|eléctric|energía|energ[ée]tic|gas|red el[ée]ctrica|sistema el[ée]ctrico|"
    r"peaje|retribuci[óo]n|autoconsumo|circular|hidrógeno|renovable|mercado el[ée]ctrico)\b",
    re.I)
# The energy sector page also covers road fuels, which are not market design.
_FUELS = re.compile(r"carburante|estaciones de servicio|gasolin|petrol|butano|\bGLP\b", re.I)

_MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
           "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}
_ES_DATE = re.compile(r"\b(\d{1,2})\s+(?:de\s+)?([A-Za-zé]{3})[a-zé]*\.?\s+(?:del?\s+)?(20\d{2})\b")
_EXPEDIENTE = re.compile(r"Expediente\s+(.+?)\s+Suceso\b")

_PAGE_CACHE: dict[str, str] = {}


def _date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _es_date(text: str) -> str | None:
    """First Spanish-format date in the text: '11 Nov 2026', '11 de Nov del 2026'."""
    for m in _ES_DATE.finditer(text or ""):
        month = _MONTHS.get(m.group(2).lower()[:3])
        if not month:
            continue
        try:
            return datetime(int(m.group(3)), month, int(m.group(1))).date().isoformat()
        except ValueError:
            continue
    return None


def _main(html: str):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return soup, (soup.select_one("main") or soup.select_one(".region-content") or soup)


def _consultations(session) -> list[Candidate]:
    r = get_with_retry(session, CONSULTATIONS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select('.views-field-title a[href*="/consultas-publicas/"]')
    if not rows:
        raise CollectorError("CNMC energy consultations listing has no rows: markup changed")
    out = []
    for a in rows[:MAX_CONSULTATIONS]:
        title = " ".join(a.get_text(" ", strip=True).split())
        url = urljoin(BASE, a["href"])
        if not title:
            continue
        sid = f"cnmc-consulta-{slugify(url.rstrip('/').split('/')[-1])}"
        published = None
        try:
            page = get_with_retry(session, url, timeout=45).text
            _PAGE_CACHE[url] = page
            # The page opens with its publication date, ahead of the title.
            published = _es_date(html_to_text(_main(page)[1])[:600])
        except CollectorError:
            pass                    # undated: fetch_content gets another try
        out.append(Candidate(sid, f"Consulta pública: {title}", published, url))
    return out


def _press(session) -> list[Candidate]:
    r = get_with_retry(session, SECTOR, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select('a[href^="/prensa/"], a[href^="/node/"]'):
        t = a.select_one(".morenews-title")
        if not t:
            continue
        title = " ".join(t.get_text(" ", strip=True).split())
        if not title or _FUELS.search(title):
            continue
        when = a.select_one("time[datetime]")
        url = urljoin(BASE, a["href"])
        sid = f"cnmc-{slugify(url.rstrip('/').split('/')[-1])}"
        out.append(Candidate(sid, title, _date(when["datetime"]) if when else None, url))
    return out


def _feed(session) -> list[Candidate]:
    r = get_with_retry(session, FEED, timeout=45)
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"CNMC RSS did not parse: {exc}")
    out = []
    for item in root.findall(".//item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        summary = " ".join(BeautifulSoup(item.findtext("description") or "", "html.parser")
                           .get_text(" ", strip=True).split())
        if not title or not link:
            continue
        if not (ENERGY.search(title) or ENERGY.search(summary)):
            continue
        # Feed titles are the event type ("Resolución del Consejo"); the case
        # name in the description is what says which resolution it is.
        m = _EXPEDIENTE.search(summary)
        if m:
            title = f"{title}: {m.group(1)[:140]}"
        sid = f"cnmc-{slugify(link.rstrip('/').split('/')[-1] or title)}"
        out.append(Candidate(sid, title, _date(item.findtext("pubDate")), link))
    return out


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    for name, route in (("consultations", _consultations), ("press", _press), ("rss", _feed)):
        try:
            for c in route(session):
                found.setdefault(c.source_id, c)
        except CollectorError as exc:
            errors.append(f"{name}: {exc}")

    # The consultations listing always has rows, so an empty result means the
    # routes themselves failed. That is worth a red mark; a feed with no
    # energy item in it today is not, and no longer reaches this point.
    if not found:
        raise CollectorError("CNMC discovery found nothing. " + " | ".join(errors)[:300])
    return f"{CONSULTATIONS} + energy press + rss.xml (energy filter)", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    html = _PAGE_CACHE.get(candidate.url)
    if html is None:
        html = get_with_retry(session, candidate.url, timeout=45).text
    soup, body = _main(html)
    text = html_to_text(body)
    if not candidate.publication_date:
        candidate.publication_date = _es_date(text[:600])

    # CNMC pages are stubs: the decision or proposal itself is the attached PDF.
    pdf = soup.select_one('a[href*="/sites/default/files/"][href$=".pdf"]')
    if pdf:
        try:
            pr = get_with_retry(session, urljoin(BASE, pdf["href"]), timeout=90)
            pdf_text = extract_pdf_text(pr.content)
            if len(pdf_text.strip()) > len(text.strip()):
                # Keep the page's own summary and deadline ahead of the PDF:
                # for a consultation that is where the closing date is stated.
                text = f"{candidate.title}\n\n{text.strip()[:3000]}\n\n{pdf_text}"
        except CollectorError:
            pass
    return text[:MAX_CONTENT_CHARS]
