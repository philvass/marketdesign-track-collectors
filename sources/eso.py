"""ESO EAD — Електроенергиен системен оператор, the Bulgarian electricity
transmission system operator.

Discovery: two server-rendered card lists on eso.bg, each card a headline, a
date and a numbered "повече..." link. The site's robots.txt allows everything.

1. Съобщения (messages): notices to the market, where approved ESO prices,
   capacity-calculation projects and rule changes appear.
2. Последни новини (news): press items, a few of which are market design
   (accession to the MARI platform, EU co-financing of the grid).

Bulgarian is read; the English edition repeats only some messages, and the
occasional English duplicate in the Bulgarian list is dropped.

Most of both lists is out of scope and is dropped by headline: environmental
notices of investment proposals, the recurring reductions of cross-border
transfer capacity, faults and storms, appointments, awards, students and
sponsorship. Each page holds the whole archive, so only its head is scanned.

Not read: the operational-data pages and the tender applications on
webapps.eso.bg.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "ESO EAD (Bulgaria)"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.eso.bg"
LISTS = (("messages", f"{BASE}/doc/?messages"), ("news", f"{BASE}/doc/?news"))
SCAN = 40
MAX_ITEMS = 20

_ID = re.compile(r"[?&](messages|news)=(\d+)")
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_DROP = re.compile(
    r"инвестиционно предложение|^о\s*б\s*я\s*в\s*а|трансграничните преносни капацитети|"
    r"net transfer capacity|повреда|авари|буря|студент|стажант|управителния съвет|"
    r"надзорния съвет|отличи|награда|грамота|дарител|състезание|форум|университет|"
    r"екологична оценка|ОВОС|\bдари\b|децата|списание|изпълнителен директор|празници|"
    r"подготвени за работа|готовност за работа|ден на енергетика|конкурс|честит", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    cards = 0
    for kind, url in LISTS:
        try:
            r = get_with_retry(session, url, timeout=60)
        except CollectorError as exc:
            errors.append(f"{kind}: {exc}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for card in soup.select(".card"):
            a = card.select_one(".card-footer a[href]")
            head = card.select_one(".card-body")
            m = _ID.search(a["href"]) if a else None
            if not m or head is None:
                continue
            cards += 1
            n += 1
            if n > SCAN:
                break
            title = " ".join(head.get_text(" ", strip=True).split()).rstrip(":")
            if not title or _DROP.search(title):
                continue
            when = card.select_one(".card-footer small")
            d = _DATE.search(when.get_text() if when else "")
            sid = f"eso-{m.group(1)}-{m.group(2)}"
            found.setdefault(sid, Candidate(
                sid, title[:300],
                f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None,
                urljoin(BASE, a["href"])))
    if not cards:
        raise CollectorError("ESO lists yielded no cards: markup changed. "
                             + " | ".join(errors)[:300])
    # Forty notices that are all capacity reductions and environmental
    # announcements is an ordinary stretch for this operator.
    if not found:
        raise UpstreamUnavailable("No market item among the latest ESO messages and news")
    items = sorted(found.values(), key=lambda c: c.publication_date or "", reverse=True)
    return " + ".join(u for _, u in LISTS), items[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    bodies = soup.select("section .card-body") or soup.select("section")
    if not bodies:
        raise CollectorError(f"ESO page has no body: {candidate.url}")
    body = max(bodies, key=lambda b: len(b.get_text()))
    text = f"{candidate.title}\n\n{html_to_text(body)}"
    if len(text) < 200:
        raise CollectorError(f"ESO page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
