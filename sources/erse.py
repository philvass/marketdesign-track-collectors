"""ERSE — Entidade Reguladora dos Serviços Energéticos, the Portuguese energy
regulator.

Discovery: two server-rendered listings on erse.pt, whose robots.txt allows
every agent:

1. Comunicados, the formal press statements: tariff proposals and decisions,
   regulations and directives adopted, the outcome of public consultations.
   Most entries are a PDF, a few are a page.
2. Destaques, the highlights: every public consultation is announced here on
   the day it opens, along with reports and regulatory notices.

Each card carries the title and the date. The Portuguese site is read; the
English one is a partial translation.

ERSE also regulates natural gas, road fuels, bottled gas and electric-vehicle
charging, so a title filter keeps electricity items (tariffs, regulations,
consultations, system services, flexibility, MIBEL) and drops entries that are
only about gas or fuels, the monthly newsletter and outreach events. The
consultation register itself is not read: its entries are announced in
Destaques with the same date.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ERSE"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.erse.pt"
LISTS = (("Comunicado", f"{BASE}/comunicacao/comunicados/"),
         ("Destaque", f"{BASE}/comunicacao/destaques/"))
PER_LIST = 12

_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d{2})")
_MEDIA = re.compile(r"/media/([a-z0-9]+)/([^/?#]+)\.pdf", re.I)
_PAGE = re.compile(r"/comunicacao/(?:comunicados|destaques)/([^/?#]+)/?$")
_ELECTRICITY = re.compile(
    r"el[ée]tric|eletricidade|tarifa|pre[çc]os|consulta p[úu]blica|regulament|diretiva|"
    r"mercado|MIBEL|flexibilidade|autoconsumo|redes|interliga|garantias de origem|PDIRT|PDIRD|"
    r"capacidade|armazenamento|servi[çc]os de sistema|produ[çc][ãa]o|renov[áa]ve|"
    r"comercializa|apag[ãa]o|REMIT", re.I)
_OTHER_SECTOR = re.compile(r"g[áa]s|gases|combust[íi]ve|GPL|garrafa|PDIRD-G|PDIRG|mobilidade", re.I)
_POWER = re.compile(r"el[ée]tric|eletricidade", re.I)
_DROP = re.compile(r"newsletter|censos s[ée]nior|convocat[óo]ria|tomou posse|eleit[oa]|balan[çc]o sancionat", re.I)


def _wanted(title: str) -> bool:
    if _DROP.search(title) or not _ELECTRICITY.search(title):
        return False
    # "mobilidade elétrica" is vehicle charging, a separate regulated sector.
    rest = re.sub(r"mobilidade el[ée]trica", "mobilidade", title, flags=re.I)
    return not _OTHER_SECTOR.search(rest) or bool(_POWER.search(rest))


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    cards_seen = 0
    for kind, url in LISTS:
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError as exc:
            errors.append(f"{kind}: {exc}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for card in soup.select("div.card.listagem"):
            a = card.select_one("a[href]")
            head = card.select_one(".card-title")
            if a is None or head is None:
                continue
            cards_seen += 1
            href = unquote(a["href"])
            title = " ".join(head.get_text(" ", strip=True).split())
            media, page = _MEDIA.search(href), _PAGE.search(href)
            if media:
                sid = f"erse-{media.group(1).lower()}-{slugify(media.group(2), 50)}"
            elif page:
                sid = f"erse-{slugify(page.group(1))}"
            else:
                continue
            if not title or not _wanted(title) or sid in found:
                continue
            when = card.select_one(".card-data")
            d = _DATE.search(when.get_text(" ", strip=True)) if when else None
            pub = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None
            found[sid] = Candidate(sid, title, pub, urljoin(BASE, a["href"]))
            n += 1
            if n >= PER_LIST:
                break
    if not cards_seen:
        raise CollectorError("ERSE listings yielded no cards: markup changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise UpstreamUnavailable("No electricity item on the ERSE listings this run")
    return " + ".join(u for _, u in LISTS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=90)
    if _MEDIA.search(unquote(candidate.url)):
        text = extract_pdf_text(r.content).strip()
        return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("#content") or soup.select_one("main") or soup
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"ERSE page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
