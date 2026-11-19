"""Creos Luxembourg — the Luxembourg electricity (and gas) network operator,
which owns and runs the transmission grid.

Discovery: two server-rendered pages on creos-net.lu, whose robots.txt
restricts nothing. French is the site's main language; some items are written
in English.

1. Actualités: the news cards, each with a numeric news id, date and title.
   This is where Creos announces network tariffs and the new tariff structure,
   flexibility and balancing arrangements, and market information sessions.
2. Consultations publiques: the list of its own public consultations (network
   development plans, the scenario report, tariff structure, terms for balance
   responsible parties), each with its period and sector. Only those of the
   electricity sector are kept, dated by the day the period opens.

Dropped by title: corporate items (annual report, appointments, sponsorship,
events), roadworks and local supply interruptions, and gas or hydrogen items.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Creos Luxembourg"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.creos-net.lu"
NEWS = f"{BASE}/particuliers/actualites"
CONSULTATIONS = f"{BASE}/particuliers/creos-luxembourg/consultations"
MAX_NEWS = 18
MAX_CONSULTATIONS = 6

_NEWS_ID = re.compile(r"tx_news_pi1(?:%5B|\[)news(?:%5D|\])=(\d+)")
_DMY = re.compile(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})")
_PERIOD = re.compile(r"Période\s*:\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_SECTOR = re.compile(r"Secteur\s*:\s*([^\n]+)")
_DROP = re.compile(
    r"rapport annuel|highlights|nomination|conseil d.administration|sponsor|partenariat|"
    r"journée|salon|foire|recrut|apprenti|chantier|travaux|coupure|interruption|"
    r"fête|concours|Energy ID|interview", re.I)
_GAS = re.compile(r"hydrog|HY4Link|\bgaz\b|\bgas\b", re.I)
_POWER = re.compile(r"[ée]lectri", re.I)


def _iso(m) -> str | None:
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def discover(session):
    found: dict[str, Candidate] = {}
    seen_any = False

    r = get_with_retry(session, CONSULTATIONS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.select_one("main") or soup
    n = 0
    for a in main.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        if not re.match(r"(Public )?consultation", title, re.I):
            continue
        block = a
        for _ in range(6):                           # climb to the entry that holds the period line
            block = block.parent
            if block is None or _PERIOD.search(block.get_text("\n")):
                break
        text = block.get_text("\n") if block is not None else ""
        period, sector = _PERIOD.search(text), _SECTOR.search(text)
        if not period or len(_PERIOD.findall(text)) > 1:
            continue
        seen_any = True
        if sector and not re.search(r"lectricit", sector.group(1), re.I):
            continue
        url = urljoin(BASE, a["href"])
        news = _NEWS_ID.search(url)
        sid = (f"creos-news-{news.group(1)}" if news
               else f"creos-consultation-{slugify(url.rstrip('/').split('/')[-1])}")
        found.setdefault(sid, Candidate(sid, title, _iso(period), url))
        n += 1
        if n >= MAX_CONSULTATIONS:
            break

    r = get_with_retry(session, NEWS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    n = 0
    for card in soup.select(".news-thumb"):
        a = card.select_one('a[href*="tx_news_pi1"]')
        head = card.select_one(".news_title")
        news = _NEWS_ID.search(a["href"]) if a else None
        if not news or not head:
            continue
        seen_any = True
        title = " ".join(head.get_text(" ", strip=True).split())
        if _DROP.search(title) or (_GAS.search(title) and not _POWER.search(title)):
            continue
        stamp = card.select_one("time")
        day = _iso(_DMY.search((stamp.get("datetime") or stamp.get_text()) if stamp else ""))
        sid = f"creos-news-{news.group(1)}"
        found.setdefault(sid, Candidate(sid, title, day, urljoin(BASE, a["href"])))
        n += 1
        if n >= MAX_NEWS:
            break
    if not seen_any:
        raise CollectorError("Creos pages showed no news cards or consultations: markup changed")
    return f"{NEWS} + {CONSULTATIONS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup.select_one("article") or soup
    text = html_to_text(body)
    if len(text.strip()) < 200:
        raise CollectorError(f"Creos page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
