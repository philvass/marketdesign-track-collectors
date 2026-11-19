"""Statnett — the Norwegian transmission system operator.

Discovery: the two server-rendered lists Statnett keeps for market
participants, each showing five items a page with title and publication time:

1. Nyheter for aktører i kraftbransjen, the industry news archive: tariffs,
   reserve markets (FCR, aFRR, mFRR), capacity calculation and flow-based,
   the interconnector arrangements, connection rules, the system operator's
   guidelines.
2. Høringer og konsultasjoner, Statnett's own consultations on terms and
   methodologies before they go to the regulator RME.

Two pages of each are read (`?index=1` is the "Se flere" button's own
request). The site publishes no robots.txt (the address answers 404), so
nothing is disallowed. Norwegian is read; the English site has only part of it.

Not read: the general newsroom and its RSS feed, which are almost entirely
grid-construction projects, financing and corporate news; and Meldinger fra
Landssentralen, the control centre's operational messages. Cable faults and
repairs that appear in the industry news are dropped by title.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text, slugify,
                  MAX_CONTENT_CHARS)

INSTITUTION = "Statnett"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.statnett.no"
LISTS = (("", f"{BASE}/for-aktorer-i-kraftbransjen/nyhetsarkiv/"),
         ("Høring", f"{BASE}/for-aktorer-i-kraftbransjen/horinger-og-konsultasjoner/"))
PAGES_PER_LIST = 2

_OPERATIONAL = re.compile(
    r"skade på|feil på|reparert|reparasjon|tilbake i (normal )?drift|oljelekkasje|"
    r"webinar|seminar|konferanse", re.I)
_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    for kind, url in LISTS:
        for index in range(PAGES_PER_LIST):
            page = url if index == 0 else f"{url}?index={index}"
            try:
                r = get_with_retry(session, page, timeout=45)
            except CollectorError as exc:
                errors.append(str(exc))
                break
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("#resultatliste article")
            if not items:
                if index == 0:
                    errors.append(f"no items at {page}")
                break
            for item in items:
                a = item.select_one(".articleItem-heading a[href]")
                if not a:
                    continue
                title = " ".join(a.get_text(" ", strip=True).split())
                href = urljoin(BASE, a["href"])
                if not title or _OPERATIONAL.search(title):
                    continue
                stamp = item.select_one("time[datetime]")
                m = _DATE.search(stamp["datetime"]) if stamp else None
                if kind and not title.lower().startswith(("høring", "utvidet høring")):
                    title = f"{kind}: {title}"
                sid = f"statnett-{slugify(href.rstrip('/').split('/')[-1])}"
                found.setdefault(sid, Candidate(sid, title, "-".join(m.groups()) if m else None, href))
    if not found:
        raise CollectorError("Statnett lists yielded no items: markup changed. "
                             + " | ".join(errors)[:300])
    return " + ".join(u for _, u in LISTS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("main") or soup
    # The headline and lead sit in a <header> inside the article, which the
    # shared text helper removes along with the site header, so they are read first.
    head = body.find("header")
    lead = " ".join(head.get_text(" ", strip=True).split()) if head else candidate.title
    for tag in body(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = f"{lead}\n\n{html_to_text(body)}"
    if len(text.strip()) < 200:
        raise CollectorError(f"Statnett page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
