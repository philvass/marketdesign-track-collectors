"""Austrian Federal Ministry of Economy, Energy and Tourism (BMWET).

Energy moved from the climate ministry (the former BMK) to this ministry in
2025, so the electricity acts — the Elektrizitätswirtschaftsgesetz (ElWG), the
Renewable Expansion Act (EAG) and its support ordinances, the acceleration act
EABG — are announced here.

Discovery: the server-rendered list "Aktuelle Pressemeldungen", ten cards a
page with date and headline; the first two pages are read. robots.txt closes
only the search, syndication and test folders.

The ministry also covers trade, tourism, industry and apprenticeships, so a
headline filter lets through only what concerns electricity. The list shows no
lead, which is why the filter works on headlines alone and is kept broad.

German only; the English site carries no press releases. Not read: the
"Aktuelles" campaign pages and the topic pages under /Themen/Energie, which
describe schemes in force rather than changes to them.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Austrian Federal Ministry of Economy, Energy and Tourism (BMWET)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://www.bmwet.gv.at"
LISTING = f"{BASE}/Presse/AktuellePressemeldungen.html"
PAGES = (LISTING, f"{LISTING}?page=2")

_MONTHS = {"jänner": 1, "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
           "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
_DATE = re.compile(r"(\d{1,2})\.\s*(" + "|".join(_MONTHS) + r")\s+(20\d{2})", re.I)
_ELECTRICITY = re.compile(
    r"Strom|Elektrizit|ElWG|\bEAG\b|EAG-|EABG|Erneuerbar|Photovoltaik|\bPV\b|PV-|Windkraft|Wasserkraft|"
    r"Netzentgelt|Netztarif|Netzausbau|Netzinfrastruktur|Netzkosten|Energiemarkt|Energiepreis|"
    r"Energiegemeinschaft|Speicher|Marktprämie|Herkunftsnachweis|Versorgungssicherheit|"
    r"Kapazitätsmechanismus|Energiekrise|Energiegesetz|Energieministerrat|E-Control", re.I)


def _date(raw: str) -> str | None:
    m = _DATE.search(raw or "")
    return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}" if m else None


def discover(session):
    found: dict[str, Candidate] = {}
    cards = 0
    for url in PAGES:
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if url == LISTING:
                raise
            break                                   # the second page is a bonus
        soup = BeautifulSoup(r.text, "html.parser")
        for li in soup.select("li.overview-item"):
            a = li.find("a", href=True)
            head = li.select_one(".card-title-heading")
            day = li.select_one(".card-date")
            if not a or not head:
                continue
            cards += 1
            title = " ".join(head.get_text(" ", strip=True).split())
            if not _ELECTRICITY.search(title):
                continue
            slug = a["href"].rstrip("/").split("/")[-1].removesuffix(".html")
            sid = f"at_gov-{slugify(slug)}"
            found.setdefault(sid, Candidate(sid, title, _date(day.get_text() if day else ""),
                                            urljoin(BASE, a["href"])))
    if not cards:
        raise CollectorError("BMWET press list showed no cards: markup changed")
    if not found:
        raise UpstreamUnavailable("No electricity item among the latest BMWET press releases")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.find("main") or soup)
    if len(text) < 300:
        raise CollectorError(f"BMWET release yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
