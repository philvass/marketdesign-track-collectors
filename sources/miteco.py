"""MITECO — the Spanish Ministry for the Ecological Transition, which holds the
energy portfolio.

Discovery: two server-rendered listings on miteco.gob.es.

1. The energy section's public-participation page: prior consultations and
   public hearings on draft royal decrees, orders and resolutions. This is
   where Spanish electricity legislation first appears as a text (capacity
   market, access and connection, charges, the renewable remuneration regime,
   storage, self-consumption). Each entry gives the title and the opening date
   of the comment period, which is used as the publication date.
2. The ministry's press room, for decisions announced by release.

Both lists cover everything the ministry does (water, climate, biodiversity,
gas, mining, energy-saving certificates), so only entries whose title mentions
electricity matters pass. The filter is deliberately a little wide: a missed
decree costs more than a release the classifier discards.

robots.txt forbids URLs with a query string and asks for a 10-second crawl
delay. Only plain .html paths are requested and the delay is kept between
requests. The annexed PDFs of a consultation are not downloaded; the detail
page states what is proposed and links them for the reader.
"""
from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "MITECO (Spanish Ministry for the Ecological Transition)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://www.miteco.gob.es"
CONSULTATIONS = f"{BASE}/es/energia/participacion.html"
NEWS = f"{BASE}/es/prensa/ultimas-noticias.html"
PER_LIST = 12
CRAWL_DELAY = 10.0

_CONSULT = re.compile(r"/energia/participacion/\d{4}/detalle-participacion-publica-k-(\d+)\.html")
_NEWS = re.compile(r"/prensa/ultimas-noticias/(20\d{2})/[a-z]+/([^/]+)\.html")
_MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
           "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
           "diciembre": 12}
_DATE_WORDS = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(20\d{2})", re.I)
_DATE_NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d{2})")
_ELECTRICITY = re.compile(
    r"el[ée]ctric|electricidad|electrificaci|energ[ií]a el|renovable|fotovoltaic|e[óo]lic|"
    r"almacenamiento|autoconsumo|mercado de capacidad|capacidad de acceso|acceso y conexi[óo]n|"
    r"nudos? de transici|red(es)? de (transporte|distribuci)|planificaci[óo]n de la red|"
    r"subasta|r[ée]gimen retributivo|par[áa]metros retributivos|peajes|cargos del sistema|"
    r"PVPC|bono social|interconexi|gesti[óo]n de la demanda|flexibilidad|agregador|"
    r"comunidades energ[ée]ticas|hidroel[ée]ctric|bombeo|cogeneraci|operador del sistema|"
    r"Ley 24/2013|PNIEC", re.I)
# "renovable" and "almacenamiento" also describe gas; those entries are not ours.
_GAS = re.compile(r"gas natural|gases renovables|gasista|hidrocarburos|biometano", re.I)
_POWER = re.compile(r"el[ée]ctric|electricidad", re.I)


def _wanted(title: str) -> bool:
    if not _ELECTRICITY.search(title):
        return False
    return not _GAS.search(title) or bool(_POWER.search(title))

_last_request = 0.0


def _get(session, url):
    """One request, never sooner than the crawl delay after the previous one."""
    global _last_request
    wait = CRAWL_DELAY - (time.monotonic() - _last_request)
    if _last_request and wait > 0:
        time.sleep(wait)
    try:
        return get_with_retry(session, url, timeout=60)
    finally:
        _last_request = time.monotonic()


def _words_date(raw: str) -> str | None:
    m = _DATE_WORDS.search(raw or "")
    month = _MONTHS.get(m.group(2).lower()) if m else None
    return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}" if month else None


def _consultations(session, found, errors):
    soup = BeautifulSoup(_get(session, CONSULTATIONS).text, "html.parser")
    links = soup.select('a[href*="detalle-participacion-publica"]')
    if not links:
        errors.append("participation page listed no entries: markup changed")
        return
    n = 0
    for a in links:
        m = _CONSULT.search(a["href"])
        title = " ".join(a.get_text(" ", strip=True).split())
        if not m or not title or not _wanted(title):
            continue
        row = a.find_parent("li")
        when = row.select_one(".public-participation-search__date") if row else None
        sid = f"miteco-participacion-{m.group(1)}"
        found.setdefault(sid, Candidate(
            sid, title, _words_date(when.get_text(" ", strip=True)) if when else None, a["href"]))
        n += 1
        if n >= PER_LIST:
            break


def _news(session, found, errors):
    soup = BeautifulSoup(_get(session, NEWS).text, "html.parser")
    links = soup.select('a[href*="/prensa/ultimas-noticias/20"]')
    if not links:
        errors.append("press room listed no releases: markup changed")
        return
    n = 0
    for a in links:
        m = _NEWS.search(a["href"])
        head = a.select_one(".search-results__text")
        title = " ".join((head.get_text(" ", strip=True) if head else a.get("title", "")).split())
        if not m or not title or not _wanted(title):
            continue
        info = a.select_one(".search-results__info")
        d = _DATE_NUM.search(info.get_text(" ", strip=True)) if info else None
        pub = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None
        sid = f"miteco-nota-{m.group(1)}-{slugify(m.group(2))}"
        found.setdefault(sid, Candidate(sid, title, pub, a["href"]))
        n += 1
        if n >= PER_LIST:
            break


def discover(session):
    found: dict[str, Candidate] = {}
    errors: list[str] = []
    for reader in (_consultations, _news):
        try:
            reader(session, found, errors)
        except CollectorError as exc:
            errors.append(str(exc))
    if errors and not found:
        raise CollectorError("MITECO listings unreadable. " + " | ".join(errors)[:300])
    if not found:
        raise QuietRun("No electricity item on the MITECO listings this run")
    return f"{CONSULTATIONS} + {NEWS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    soup = BeautifulSoup(_get(session, candidate.url).text, "html.parser")
    head = soup.find("h1")
    body = head.find_parent("div", class_="cmp-container") if head else None
    text = html_to_text(body or soup.select_one("main") or soup)
    if len(text) < 200:
        raise CollectorError(f"MITECO page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
