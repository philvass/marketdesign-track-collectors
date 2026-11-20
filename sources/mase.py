"""MASE — Ministero dell'Ambiente e della Sicurezza Energetica, the Italian
ministry that holds the energy portfolio.

Discovery: two server-rendered tables on the ministry's portal, each row a
date and a headline: the press releases (Comunicati Stampa) and the news
archive (Notizie). Italian electricity legislation is announced here: the
"DL Bollette" measures on electricity cost, the FER decrees and their
auctions, the capacity market and storage (MACSE) decrees, the end of the
protected retail market, nuclear enabling law, and Italy's positions at the
Energy Council.

The ministry also covers climate diplomacy, water, waste, nature and the
recovery plan, so only rows whose headline mentions electricity matters pass.
Headlines are short and often start with a subject word ("Energia:", "DL
Bollette", "Nucleare:"), which the filter relies on.

robots: the portal's own file (/portale/robots.txt) allows every agent. The
file at the site root answers "Access Denied" from the delivery network for
any client; nothing outside /portale/ is requested. Links in the tables carry
a back-navigation query string, which is removed before fetching.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "MASE (Italian Ministry of Environment and Energy Security)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://www.mase.gov.it"
LISTS = (f"{BASE}/portale/comunicati-stampa", f"{BASE}/portale/archivio-notizie-1")
PER_LIST = 12

_ITEM = re.compile(r"/portale/-/([^/?#]+)")
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d{2})")
_ELECTRICITY = re.compile(
    r"elettric|\benergia\b|energetic|bollette|rinnovabil|\bFER\b|fotovoltaic|agrivoltaic|eolic|"
    r"idroelettric|accumul|\bMACSE\b|mercato della capacit|capacity market|\breti\b|rete di trasmissione|"
    r"nucleare|tutele graduali|maggior tutela|mercato libero|\bPNIEC\b|aree idonee|"
    r"comunit[àa] energetiche|\bCER\b|energy release|interconness|aste\b|\bPUN\b|\bGSE\b|Terna|ARERA",
    re.I)
_DROP = re.compile(
    r"\bCOP ?\d+|ha incontrato|incontra\b|ambasciator|G7|G20|Youth4Climate|fiera|ecomondo|"
    r"campagna|study tour|dialoghi|protocollo di intesa|\bMou\b|ETS\b", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    rows_seen = 0
    for url in LISTS:
        try:
            r = get_with_retry(session, url, timeout=60)
        except CollectorError as exc:
            errors.append(str(exc))
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for a in soup.select("td.views-field-title a[href]"):
            m = _ITEM.search(a["href"])
            title = " ".join(a.get_text(" ", strip=True).split())
            if not m or not title:
                continue
            rows_seen += 1
            if _DROP.search(title) or not _ELECTRICITY.search(title):
                continue
            row = a.find_parent("tr")
            when = row.select_one("td.views-field-created") if row else None
            d = _DATE.search(when.get_text(" ", strip=True)) if when else None
            pub = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None
            sid = f"mase-{slugify(m.group(1))}"
            found.setdefault(sid, Candidate(sid, title, pub, f"{BASE}/portale/-/{m.group(1)}"))
            n += 1
            if n >= PER_LIST:
                break
    if not rows_seen:
        raise CollectorError("MASE tables listed no rows: markup changed. " + " | ".join(errors)[:300])
    if not found:
        raise QuietRun("No electricity item on the MASE listings this run")
    return " + ".join(LISTS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".asset-full-content") or soup.select_one(".journal-content-article")
    if body is None:
        raise CollectorError(f"MASE article body not found: {candidate.url}")
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"MASE article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
