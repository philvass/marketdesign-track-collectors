"""SEPS (Slovenská elektrizačná prenosová sústava) — the Slovak transmission
system operator.

Discovery: two server-rendered lists on sepsas.sk. Its robots.txt closes the
feeds (*/feed, */rss) and the /wp- paths to every agent, so the WordPress feed
and JSON interface are deliberately not used; the list pages are open.

1. Aktuality: notices to market participants — the operating rules
   (Prevádzkový poriadok) and technical conditions taking effect, ÚRSO
   decisions addressed to SEPS, cross-border capacity allocation, tenders for
   ancillary services, market-coupling tests.
2. Verejné konzultácie: every consultation SEPS runs or relays (its own rule
   changes, the ancillary-services strategy, the ten-year plan scenarios, and
   ACER or JAO consultations that concern the Slovak borders), each with its
   opening date. The list goes back years, so only its head is read.

Slovak: the English edition omits most notices.

Not read: Tlačové správy, the press releases, which are about construction
works, results and visits; anything of market weight in them is also posted
under Aktuality.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text, slugify,
                  MAX_CONTENT_CHARS)

INSTITUTION = "SEPS (Slovenská elektrizačná prenosová sústava)"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.sepsas.sk"
NEWS = f"{BASE}/pre-verejnost/aktuality/"
CONSULTATIONS = f"{BASE}/pre-verejnost/verejne-konzultacie/"
MAX_NEWS = 12
MAX_CONSULTATIONS = 10

_DATE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(20\d{2})\b")
_ROUTINE = re.compile(r"odstávk|výpadok|údržb\w+ (?:systému|portálu)|voľné pracovné|kariér", re.I)


def _date(raw: str) -> str | None:
    m = _DATE.search(raw or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def _sid(href: str) -> str:
    return f"seps-{slugify(href.rstrip('/').split('/')[-1], 140)}"


def _news(session) -> list[Candidate]:
    soup = BeautifulSoup(get_with_retry(session, NEWS, timeout=45).text, "html.parser")
    posts = soup.select("article.category-aktuality")
    if not posts:
        raise CollectorError("SEPS Aktuality showed no posts: markup changed")
    out = []
    for post in posts[:MAX_NEWS]:
        a = post.select_one(".post_title a[href]")
        when = post.find("time")
        if not a:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or _ROUTINE.search(title):
            continue
        day = (when.get("datetime") or "")[:10] if when else ""
        # The post id keeps two notices with the same headline apart.
        sid = f"seps-{post.get('data-id')}" if post.get("data-id") else _sid(a["href"])
        out.append(Candidate(sid, title, day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
                             a["href"]))
    return out


def _consultations(session) -> list[Candidate]:
    soup = BeautifulSoup(get_with_retry(session, CONSULTATIONS, timeout=45).text, "html.parser")
    links = soup.select('.post_title a[href*="/verejna-konzultacia/"]')
    if not links:
        raise CollectorError("SEPS Verejné konzultácie listed nothing: markup changed")
    out = []
    for a in links[:MAX_CONSULTATIONS]:
        card = a.find_parent(class_="innerWrapper")
        day = card.select_one(".date") if card else None
        title = " ".join(a.get_text(" ", strip=True).split())
        if title:
            out.append(Candidate(_sid(a["href"]), title,
                                 _date(day.get_text(" ", strip=True)) if day else None, a["href"]))
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
    if not found:
        raise CollectorError("SEPS yielded nothing. " + " | ".join(errors)[:300])
    return f"{NEWS} + {CONSULTATIONS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.find("main") or soup)
    if len(text) < 200:
        raise CollectorError(f"SEPS page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
