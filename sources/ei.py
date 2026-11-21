"""Energimarknadsinspektionen (Ei) — the Swedish energy markets regulator.

Discovery: the news archive at ei.se/om-oss/nyheter. The page fills its list
through a search form that submits `query=*` back to the same address, and the
server renders the result, ten items a page with date, title and lead; the two
newest pages are read. robots.txt allows the path (it forbids only session and
state parameters, which are not used; a session id the server appends to links
is stripped).

Ei sets the revenue caps and tariff rules for the Swedish networks, approves
Svenska kraftnät's terms, methodologies and derogations under the EU network
codes, puts its own regulations out for comment and supervises the wholesale
market. Swedish is read; the English site is a small subset.

Ei also regulates gas and district heating, so a title-and-lead filter keeps
the electricity items. Not read: the weekly price commentary "Läget på
elmarknaden", and the e-diarium of individual revenue-cap and concession
decisions, which are case files on named companies.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Energimarknadsinspektionen (Ei)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://ei.se"
LISTING = f"{BASE}/om-oss/nyheter"
PAGES = (f"{LISTING}?query=*&submitButton=", f"{LISTING}?query=*&startAtHit=10")
MAX_ITEMS = 20

_ELECTRICITY = re.compile(
    r"\bel\b|\bel(en|nät|marknad|handel|pris|område|lag|försörjning|system|kund|använd|produ|avtal|"
    r"effekt|beredskap|certifikat)|nätavgift|nätföretag|nätreglering|nättariff|nätutveckling|"
    r"nätkod|intäktsram|tariff|effektavgift|balans|stödtjänst|kapacitet|flaskhals|flexibilit|"
    r"villkorade avtal|anslutning|budområde|transmission|stamnät|svenska kraftnät|"
    r"ursprungsgaranti|grossistmarknad|remit\b|acer\b|omdirigering|mätning|aggregat|"
    r"energidelning|energilag|lagring", re.I)
_DROP = re.compile(r"läget på elmarknaden|veckorapport", re.I)
# "nätföretag" and "intäktsram" are shared with the gas rules; a title about gas
# or district heating passes only if it names electricity as well.
_OTHER_FUEL = re.compile(r"gas|fjärrvärm", re.I)
_EL_TITLE = re.compile(r"\bel\b|\bel(en|nät|marknad|handel|pris|område|lag|försörjning|system|kund)", re.I)
_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")

_LEADS: dict[str, str] = {}


def discover(session):
    found: dict[str, Candidate] = {}
    seen = 0
    for n, page in enumerate(PAGES):
        try:
            r = get_with_retry(session, page, timeout=60)
        except CollectorError:
            if n == 0:
                raise
            break                      # the first page alone is still a valid run
        soup = BeautifulSoup(r.text, "html.parser")
        for li in soup.select("li.ei-search-result-news__item"):
            a = li.select_one("a.ei-search-result-news__link[href]")
            if not a:
                continue
            seen += 1
            href = urljoin(BASE, re.sub(r";jsessionid=[^?#]*", "", a["href"]).split("?")[0])
            title = " ".join(a.get_text(" ", strip=True).split())
            day = li.select_one(".ei-search-result-news__date")
            lead = li.select_one(".ei-search-result-news__description")
            lead = " ".join(lead.get_text(" ", strip=True).split()) if lead else ""
            m = _DATE.search(day.get_text() if day else "") or _DATE.search(href)
            if not title or _DROP.search(title) or not _ELECTRICITY.search(f"{title} {lead}"):
                continue
            if _OTHER_FUEL.search(title) and not _EL_TITLE.search(title):
                continue
            sid = f"ei-{slugify(href.rstrip('/').split('/')[-1])}"
            _LEADS[sid] = lead
            found.setdefault(sid, Candidate(sid, title, "-".join(m.groups()) if m else None, href))
            if len(found) >= MAX_ITEMS:
                break
    if not seen:
        raise CollectorError("Ei news archive listed no items: markup or search form changed")
    if not found:
        raise QuietRun("No electricity item among the newest Ei news this run")
    return PAGES[0], list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    # The print header carries the time of the request, which would change the
    # text on every fetch.
    for tag in soup.select(".ei-print-only"):
        tag.decompose()
    body = soup.select_one("main") or soup
    # Every article ends with a list of the latest other news, which changes
    # whenever Ei publishes anything.
    text = html_to_text(body).split("\nFler nyheter\n")[0]
    if len(text.strip()) < 200:
        raise CollectorError(f"Ei page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
