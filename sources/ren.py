"""REN — Redes Energéticas Nacionais, the Portuguese transmission system
operator for electricity (and gas).

Discovery: the news listing on ren.pt, server-rendered cards with the date,
the headline and REN's own subject tags. robots.txt allows the path. The
Portuguese edition is read; it is the complete one.

REN publishes little, and most of it is corporate. What matters here are the
system-operation items: emergency and restoration plans, market consultations,
network planning, interconnection with Spain, and the monthly consumption and
renewable-share statistics. Cards tagged as results presentations, local
communities, sustainability, social responsibility or gas only are dropped
before anything is fetched. The binding texts (operating manuals, tariff
decisions) are ERSE's and reach the monitor through the `erse` adapter.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "REN (Redes Energéticas Nacionais)"
DOCUMENT_TYPE = "TSO"

NEWS = "https://www.ren.pt/pt-pt/media/noticias"
MAX_ITEMS = 20

_ITEM = re.compile(r"/media/noticias/([^/?#]+)")
_MONTHS = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
           "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11,
           "dezembro": 12}
_DATE = re.compile(r"(\d{1,2})\s+(?:de\s+)?([a-zç]+)\s+(?:de\s+)?(20\d{2})", re.I)
_DROP_TAGS = re.compile(
    r"resultados|comunidades locais|sustentabilidade|responsabilidade social|medea|"
    r"encontros com futuro|pr[ée]mio|investidores|pessoas", re.I)
_GAS_TAGS = re.compile(r"g[áa]s|gases|portg[áa]s|hidrog[ée]nio", re.I)
_POWER = re.compile(r"el[ée]tric|eletricidade|energia", re.I)
_DROP_TITLE = re.compile(r"pr[ée]mio|em direto|assembleia geral|dividendo|obriga[çc][õo]es", re.I)


def _date(raw: str) -> str | None:
    m = _DATE.search(raw or "")
    month = _MONTHS.get(m.group(2).lower()) if m else None
    return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}" if month else None


def discover(session):
    r = get_with_retry(session, NEWS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select("article.post")
    if not cards:
        raise CollectorError("REN news listing carried no cards: markup changed")
    found: dict[str, Candidate] = {}
    for card in cards:
        a = card.select_one("a.post-link[href]") or card.select_one('a[href*="/media/noticias/"]')
        head = card.select_one(".post-title")
        m = _ITEM.search(a["href"]) if a else None
        title = " ".join(head.get_text(" ", strip=True).split()) if head else ""
        if not m or not title or _DROP_TITLE.search(title):
            continue
        tags = " | ".join(t.get_text(" ", strip=True) for t in card.select(".tag-ren"))
        if _DROP_TAGS.search(tags):
            continue
        if _GAS_TAGS.search(tags) and not _POWER.search(f"{tags} {title}".replace("Gases", "")):
            continue
        when = card.select_one(".post-date")
        sid = f"ren-{slugify(m.group(1))}"
        found.setdefault(sid, Candidate(
            sid, title, _date(when.get_text(" ", strip=True)) if when else None, a["href"]))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise QuietRun("No system or market item on the REN news listing this run")
    return NEWS, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("section.news") or soup.select_one("main") or soup.body or soup
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"REN article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
