"""ÚRSO (Úrad pre reguláciu sieťových odvetví) — the Slovak regulator of
network industries: electricity, gas, heat and water.

Discovery: two server-rendered pages on urso.gov.sk. The site serves no
robots.txt (the address answers 404), so nothing is closed to agents.

1. Aktuality, the office's news: cards with date, headline and a one-line
   lead, ten a page; the first two pages are read. This is where the office
   announces its draft ordinances (with the Slov-Lex file numbers), price
   proceedings, tariff reforms and positions on market rules.
2. Verejné konzultačné procesy, where a notice is posted while a consultation
   is open: mostly the technical conditions and operating rules of the system
   operators. Closed notices are commented out of the page by the office, so
   the page is often empty, which is a valid answer.

A headline-and-lead filter keeps only what concerns electricity or the
regulatory framework as a whole; water, heat and gas-only items are dropped.
Slovak only: the English site is a static summary.

Not read: the registers of price and substantive decisions, thousands of
individual rulings per year addressed to named companies.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ÚRSO (Úrad pre reguláciu sieťových odvetví)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.urso.gov.sk"
NEWS = f"{BASE}/aktuality/"
NEWS_PAGES = (NEWS, f"{NEWS}?page=2")
CONSULTATIONS = f"{BASE}/verejne-konzultacne-procesy/"

_ELECTRICITY = re.compile(
    r"elektr|tar[ií]f|sústav|sieťov\w+ poplat|distribu|prenos|regulačn\w+ (?:politik|obdob)|vyhlášk|"
    r"cenov\w+ konan|cenov\w+ rozhodnut|trh|dodávateľ|switching|flexibil|agregá|batéri|uskladň|"
    r"obnoviteľn|lokáln\w+ zdroj|záruk\w* pôvodu|TPS|TSS|pripomienkov|konzultác", re.I)
_OTHER = re.compile(r"vodár|vodn|kanaliz|tepl[oa]|tepeln|plyn", re.I)
_ELECTRICITY_STRICT = re.compile(r"elektr|sústav", re.I)
_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")


def _wanted(title: str, lead: str) -> bool:
    both = f"{title} {lead}"
    if _OTHER.search(both) and not _ELECTRICITY_STRICT.search(both):
        return False
    return bool(_ELECTRICITY.search(both))


def _sid(href: str) -> str:
    return f"urso-{slugify(href.strip('/').split('/')[-1], 140)}"


def _news(session) -> list[Candidate]:
    out, cards = [], 0
    for url in NEWS_PAGES:
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if url == NEWS:
                raise
            break                                   # the second page is a bonus
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("article.card"):
            a = card.select_one(".card__title a[href]")
            when = card.find("time")
            if not a:
                continue
            cards += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            lead_el = card.select_one(".card__text")
            lead = " ".join(lead_el.get_text(" ", strip=True).split()) if lead_el else ""
            if not _wanted(title, lead):
                continue
            day = (when.get("datetime") or "")[:10] if when else ""
            out.append(Candidate(_sid(a["href"]), title,
                                 day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
                                 urljoin(BASE, a["href"])))
    if not cards:
        raise CollectorError("ÚRSO Aktuality showed no cards: markup changed")
    return out


def _consultations(session) -> list[Candidate]:
    r = get_with_retry(session, CONSULTATIONS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")     # commented-out (closed) notices do not parse as links
    out = []
    for a in (soup.find("main") or soup).select('a[href*="verejnej-konzultacie"]'):
        title = " ".join((a.get("title") or a.get_text(" ", strip=True)).split())
        block = a.find_parent("p")
        m = _DATE.search(block.get_text(" ", strip=True)) if block else None
        if not m:
            prev = block.find_previous_sibling("p") if block else None
            m = _DATE.search(prev.get_text(" ", strip=True)) if prev else None
        if len(title) < 20 or (_OTHER.search(title) and not _ELECTRICITY_STRICT.search(title)):
            continue
        out.append(Candidate(_sid(a["href"]), title,
                             f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None,
                             urljoin(BASE, a["href"])))
    return out


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    for name, route in (("Aktuality", _news), ("konzultácie", _consultations)):
        try:
            for c in route(session):
                found.setdefault(c.source_id, c)
        except CollectorError as exc:
            errors.append(f"{name}: {exc}")
    if errors and not found:
        raise CollectorError("ÚRSO yielded nothing. " + " | ".join(errors)[:300])
    if not found:
        raise UpstreamUnavailable("No electricity item among the latest ÚRSO news and no open consultation")
    return f"{NEWS} + {CONSULTATIONS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.find("main") or soup)
    if len(text) < 200:
        raise CollectorError(f"ÚRSO page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
