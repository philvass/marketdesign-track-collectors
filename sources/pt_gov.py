"""DGEG — Direção-Geral de Energia e Geologia, the Portuguese government's
energy directorate under the ministry responsible for energy.

Discovery: the "Destaques" listing on dgeg.gov.pt, server-rendered cards with
a headline and a link, newest first. robots.txt forbids only /media/, which is
not requested. DGEG is where Portuguese electricity legislation is explained
and put out for comment: decree-laws amending the national electricity system
regime, ministerial orders (portarias, despachos), public consultations, the
competitive procedures for grid injection capacity, the storage strategy, the
cogeneration reference tariff and the risk-preparedness plan.

The listing covers everything the directorate does, so only cards whose
headline mentions electricity matters pass, and the routine items are dropped:
monthly statistics, the newsletter, social-tariff processing notices, fuels,
gas, geology and quarries.

The listing carries no dates. Each article page ends with a "Data/Hora da
Notícia" line, which is read at fetch time. The whole listing page is long
(every highlight since 2020), so only its head is considered.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "DGEG (Portuguese Directorate-General for Energy and Geology)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7
# The listing gives no dates; they are read from the article page.
DATE_REFINED_ON_FETCH = True

BASE = "https://www.dgeg.gov.pt"
LISTING = f"{BASE}/pt/destaques/"
HEAD = 40          # cards considered, newest first
MAX_ITEMS = 20

_ITEM = re.compile(r"/pt/destaques/([^/?#]+)/?$")
_ELECTRICITY = re.compile(
    r"el[ée]tric|eletricidade|\bSEN\b|decreto-lei|portaria|despacho|consulta p[úu]blica|"
    r"armazenamento|autoconsumo|capacidade de inje[çc][ãa]o|reserva de capacidade|\bRESP\b|"
    r"renov[áa]ve|cogera[çc][ãa]o|leil[ãa]o|leil[õo]es|garantias de origem|comunidades de energia|"
    r"\bCER\b|\bACC\b|e[óo]lic|solar|fotovoltaic|h[íi]dric|PNEC|redes", re.I)
_DROP = re.compile(
    r"estat[íi]sticas r[áa]pidas|newsletter|tarifa social|combust[íi]ve|\bGPL\b|"
    r"g[áa]s\b|l[íi]tio|pedreira|geol[óo]g|hidrogeol|[áa]guas|mineir|norma np|selo|"
    r"COP ?\d+|em direto|pr[ée]mio|concurso para financiamento|linha de atendimento|"
    r"balan[çc]o energ[ée]tico", re.I)
_DATE = re.compile(r"Data/Hora da Not[íi]cia:?\s*(\d{1,2})/(\d{1,2})/(20\d{2})", re.I)


def discover(session):
    r = get_with_retry(session, LISTING, timeout=90)
    soup = BeautifulSoup(r.text, "html.parser")
    cards = [c for c in soup.select("div.card") if c.select_one('a[href*="/pt/destaques/"]')]
    if not cards:
        raise CollectorError("DGEG highlights listing carried no cards: markup changed")
    found: dict[str, Candidate] = {}
    for card in cards[:HEAD]:
        a = card.select_one('a[href*="/pt/destaques/"]')
        head = card.select_one(".card-title")
        m = _ITEM.search(unquote(a["href"]))
        title = " ".join(head.get_text(" ", strip=True).split()) if head else ""
        if not m or not title or _DROP.search(title) or not _ELECTRICITY.search(title):
            continue
        # Slugs are cut by the site at a fixed length, so two consultations can
        # share a long prefix; a digest of the whole slug keeps the ids apart.
        slug = m.group(1)
        sid = f"pt-gov-{slugify(slug, 60)}-{hashlib.md5(slug.encode()).hexdigest()[:8]}"
        found.setdefault(sid, Candidate(sid, title, None, urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise UpstreamUnavailable("No electricity item at the head of the DGEG highlights this run")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=90)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("div.tema-content") or soup.select_one("section.main-content")
    if body is None:
        raise CollectorError(f"DGEG article body not found: {candidate.url}")
    text = html_to_text(body)
    m = _DATE.search(text)
    if m:
        candidate.publication_date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if len(text) < 200:
        raise CollectorError(f"DGEG article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
