"""Hungarian Ministry of Economy and Energy (Gazdasági és Energetikai
Minisztérium), on the government portal kormany.hu.

Energy has had no ministry of its own since the 2026 change of government; it
sits in this ministry, which is why the adapter reads its page rather than a
"Ministry of Energy".

Discovery: two server-rendered pages of the portal, each showing a handful of
news cards with date, headline and lead:

1. the ministry's own page, with its five latest items;
2. the portal's front page, with the ten latest items of the whole government,
   which catches energy announcements made by the prime minister's office or
   the finance ministry.

That is all the portal serves as plain pages. The full news lists (the
ministry's /hirek and the portal's /hirek) are filled by scripts from
/publicapi, and robots.txt closes /publicapi to every agent, so they are not
read, neither directly nor through a rendered page. The consequence is a short
window: an item that leaves both cards before a run is missed.

A headline-and-lead filter keeps electricity items only: the ministry also
covers industry, trade, oil and gas, district heating and business credit.
Hungarian only; the English site (abouthungary.hu) is a separate publication.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Hungarian Ministry of Economy and Energy"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://kormany.hu"
MINISTRY = f"{BASE}/kormanyzat/gazdasagi-es-energetikai-miniszterium"
PAGES = (MINISTRY, f"{BASE}/")

_DATE = re.compile(r"(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")
_ELECTRICITY = re.compile(
    r"villamos|áram(?!l)|energiapiac|energiaellátás|energiaár|rezsi|erőmű|atomerőmű|Paks|napelem|"
    r"szélerőmű|szélenergi|megújuló|energiatárol|hálózatfejleszt|áramhálózat|okosmér|MAVIR|"
    r"energetikai (?:törvény|szabályoz|pályázat|reform|stratégi)|kapacitásmechanizmus|METÁR|"
    r"energiaközösség|energiaügy|energiastratégia", re.I)


def _date(raw: str) -> str | None:
    m = _DATE.search(raw or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def discover(session):
    found: dict[str, Candidate] = {}
    cards, errors = 0, []
    for url in PAGES:
        try:
            r = get_with_retry(session, url, timeout=60)
        except CollectorError as exc:
            errors.append(str(exc))
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select('a.article-card__link[href^="/hirek/"]'):
            head = a.select_one(".article-card__title")
            title = " ".join((head.get_text(" ", strip=True) if head else a.get("aria-label", "")).split())
            if not title:
                continue
            cards += 1
            lead_el = a.select_one(".article-card__description")
            lead = " ".join(lead_el.get_text(" ", strip=True).split()) if lead_el else ""
            if not _ELECTRICITY.search(f"{title} {lead}"):
                continue
            day = a.select_one(".article-card__date")
            sid = f"hu_gov-{slugify(a['href'].rstrip('/').split('/')[-1], 140)}"
            found.setdefault(sid, Candidate(sid, title, _date(day.get_text() if day else ""),
                                            urljoin(BASE, a["href"])))
    if not cards:
        raise CollectorError("kormany.hu pages showed no news cards: markup changed or pages now "
                             "script-built. " + " | ".join(errors)[:200])
    if not found:
        raise UpstreamUnavailable("No electricity item among the news cards on kormany.hu this run")
    return " + ".join(PAGES), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.select_one("section.article-page") or soup.find("main") or soup)
    if len(text) < 200:
        raise CollectorError(f"kormany.hu article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
