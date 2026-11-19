"""TGE — Towarowa Giełda Energii, the Polish power exchange and the Polish
NEMO for single day-ahead and intraday coupling.

Discovery: the "Aktualności TGE" listing on tge.pl, a server-rendered list of
the ten newest announcements with date, title and lead. The site's robots.txt
forbids only one unrelated file path.

This is where the exchange announces changes to its markets: new products
and trading rules, coupling milestones, the flexibility platform it is
building with the system operators, changes to the guarantees-of-origin and
certificate registers. It publishes two or three items a month.

Dropped by title: quarterly and monthly trading summaries, awards,
competitions, anniversaries and training sessions.

Not read: the "Regulacje" page. It holds the current rulebooks as undated
PDFs that are replaced in place, so it gives no notice of a change; the
changes themselves are announced in the listing read here.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "TGE (Towarowa Giełda Energii)"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://tge.pl"
LISTING = f"{BASE}/aktualnosci-tge"

_ID = re.compile(r"cmn_id=(\d+)")
_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
_CORPORATE = re.compile(
    r"kwartał \d{4} r\. na TGE|półrocze|podsumowanie (miesiąca|roku)|\w+ \d{4} r\. na TGE|"
    r"dzień energetyka|świętujemy|konkurs|platynowe megawaty|dziennikarz|rozświetlił|"
    r"szkoleni|webinar|konferencj|życzenia|jubileusz|zarząd\w* TGE|rada nadzorcza", re.I)


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("TGE listing returned an empty response")
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    rows = 0
    for a in soup.select('.news li h4.title a[href*="cmn_id="]'):
        m = _ID.search(a["href"])
        if not m:
            continue
        rows += 1
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or _CORPORATE.search(title):
            continue
        when = a.find_parent("li").select_one("p.date")
        d = _DATE.search(when.get_text(" ", strip=True)) if when else None
        sid = f"tge-{m.group(1)}"
        found.setdefault(sid, Candidate(sid, title, f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
                                        urljoin(BASE, a["href"])))
    if not rows:
        raise CollectorError("TGE listing carried no announcements: markup changed")
    if not found:
        raise UpstreamUnavailable("TGE listing held only corporate items this run")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    # The article sits in the block that holds its heading; the page has no <main>.
    head = next((h for h in soup.find_all(["h1", "h2"])
                 if h.get_text(" ", strip=True)[:40] == candidate.title[:40]), None)
    body = head.parent if head else soup.select_one("section.mainContainer") or soup
    text = html_to_text(body).strip()
    if len(text) < 200:
        raise CollectorError(f"TGE article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
