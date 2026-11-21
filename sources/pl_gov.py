"""Polish Ministry of Energy (Ministerstwo Energii), on the government portal
gov.pl/web/energia.

Discovery: the ministry's "Wiadomości" listing, a server-rendered page of ten
releases with date, title and lead; the three newest pages are read. gov.pl's
robots.txt allows everything.

The ministry drafts the Energy Law and its amendments, the capacity market
and renewables acts, price-freeze and network legislation, and announces the
Council of Ministers' decisions on them. It also publishes on fuels, gas,
coal, nuclear diplomacy and a daily maximum fuel price, so a Polish
title-and-lead filter keeps the electricity items only.

Content: the article page. The portal sometimes answers a request for an
article with a redirect to its home page while serving the listing normally
(seen repeatedly on 19 November 2026 during announced maintenance). When that
happens the record carries the title and the ministry's own lead from the
listing, and says so, rather than failing.

Not read: the legislative process itself (legislacja.gov.pl), which is a
separate system.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Polish Ministry of Energy"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://www.gov.pl"
LISTING = f"{BASE}/web/energia/wiadomosci"
PAGES = 3
MAX_ITEMS = 20

_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_ELECTRICITY = re.compile(
    r"energi[aięą] elektryczn|elektroenerget|rynk\w* energii|rynk\w* mocy|cen\w* energii|cen\w* prądu|"
    r"\bprąd|prawo energetyczne|prawa energetycznego|sieci\w* (przesył|dystrybuc|elektro)|"
    r"przyłącze|magazyn\w* energii|odnawialn|\bOZE\b|fotowolta|wiatrow|offshore|morsk\w* farm|"
    r"aukcj|kontrakt\w* różnicow|jądrow|atomow|elektrowni|bilansując|elastyczno|taryf\w* (za|dla) energi|"
    r"odbiorc\w* energii|sprzedawc\w* energii|gwarancj\w* pochodzenia|PSE\b|URE\b|"
    r"bezpieczeństw\w* dostaw energii|system\w* elektroenergetyczn|linii bezpośredni|cable pooling", re.I)
_SKIP = re.compile(r"maksymalna cena detaliczna paliw|zapas\w* interwencyjn|nabór wniosków|konkurs|"
                   r"cyber|szczyt|spotkani|rozmowy|gospodarzem|dołącz do|pozwoleni\w* na budowę|"
                   r"odbiorc\w* gazu|cen\w* gazu|paliw gazowych", re.I)

_META: dict[str, str] = {}


def discover(session):
    found: dict[str, Candidate] = {}
    rows = 0
    for page in range(1, PAGES + 1):
        url = LISTING if page == 1 else f"{LISTING}?page={page}&size=10"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if page == 1:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for when in (soup.select_one("main") or soup).select("span.date"):
            li = when.find_parent("li")
            a = li.select_one('.title a[href^="/web/energia/"]') if li else None
            d = _DATE.search(when.get_text(strip=True))
            if not a or not d:
                continue
            rows += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            intro = li.select_one(".intro")
            lead = " ".join(intro.get_text(" ", strip=True).split()) if intro else ""
            if _SKIP.search(title) or not _ELECTRICITY.search(f"{title} {lead}"):
                continue
            sid = f"pl_gov-{slugify(a['href'].rstrip('/').split('/')[-1])}"
            _META[sid] = lead
            found.setdefault(sid, Candidate(sid, title, f"{d.group(3)}-{d.group(2)}-{d.group(1)}",
                                            urljoin(BASE, a["href"])))
    if not rows:
        raise CollectorError("gov.pl energy ministry listing carried no dated items: markup changed")
    if not found:
        raise QuietRun(f"No electricity item among the {rows} newest Polish energy ministry releases")
    return LISTING, list(found.values())[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    lead = _META.get(candidate.source_id) or ""
    try:
        r = get_with_retry(session, candidate.url, timeout=45)
        served = urlparse(r.url).path.rstrip("/") == urlparse(candidate.url).path.rstrip("/")
    except CollectorError:
        r, served = None, False
    if served:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        text = html_to_text(soup.select_one("article") or soup.select_one("main") or soup).strip()
        if len(text) >= 300:
            return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
    parts = [candidate.title, lead,
             "Uwaga: portal gov.pl nie udostępnił pełnej treści komunikatu; wpis zawiera tytuł i lead "
             "opublikowany przez Ministerstwo Energii. Pełny tekst pod adresem źródłowym. "
             "(Note: gov.pl did not serve the article page; this record carries the title and the "
             "ministry's published lead. Full text at the source URL.)"]
    return "\n\n".join(p for p in parts if p)[:MAX_CONTENT_CHARS]
