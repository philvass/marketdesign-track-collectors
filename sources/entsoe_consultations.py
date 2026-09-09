"""ENTSO-E consultation hub (consultations.entsoe.eu).

The existing `entsoe` adapter reads ENTSO-E's news. Its consultations live on
a separate Citizen Space instance, and that is where TSO methodology
proposals are actually put to stakeholders: imbalance settlement
harmonisation, intraday capacity calculation, long-term transmission rights,
harmonised allocation rules, CCR-level amendments.

It is also how Belgian and other challenge-protected TSOs stay visible. Elia
cannot be collected directly, but the Central European proposals it is party
to are consulted here in the open.

One page carries every consultation with its state, so discovery is a single
request and no pagination is needed.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, get_with_retry, html_to_text, slugify, MAX_CONTENT_CHARS

INSTITUTION = "ENTSO-E"
DOCUMENT_TYPE = "TSO_ASSOCIATION"

BASE = "https://consultations.entsoe.eu"
LISTING = f"{BASE}/consultation_finder/"

# Citizen Space stamps each consultation "Opened <date>" and, once shut,
# "Closed <date>"; the opening is the publication date TRACK wants.
_OPENED = re.compile(r"Opened\s+(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})", re.I)
_CLOSES = re.compile(r"(Closes|Closed)\s+(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})", re.I)


def _parse(day: str, month: str, year: str) -> str | None:
    """Citizen Space abbreviates some months and spells out others."""
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(f"{day} {month[:9]} {year}", fmt).date().isoformat()
        except ValueError:
            continue
    return None

DATE_REFINED_ON_FETCH = True

# Research, innovation and system-development consultations are ENTSO-E's
# other work; the monitor covers market design.
_OFF_TOPIC = re.compile(r"/(?:r-i|system-development|rd-i)/", re.I)


def discover(session):
    r = get_with_retry(session, LISTING, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for card in soup.select("li.dss-card"):
        a = card.select_one("h2 a[href], h3 a[href], a[href]")
        if not a:
            continue
        href = a["href"].split("?")[0]
        if "consultations.entsoe.eu" not in href or href.rstrip("/").endswith("consultations.entsoe.eu"):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if len(title) < 12:
            continue
        state = " ".join(card.get("class") or [])
        sid = f"entsoe-cons-{slugify(href.rstrip('/').split('/')[-1])}"
        c = Candidate(sid, title, None, href)
        # Carry the state so an open consultation is distinguishable from an
        # archived one when the desk reads it.
        c.state = "OPEN" if "closed" not in state else "CLOSED"
        found.setdefault(sid, c)
    if not found:
        raise UpstreamUnavailable("ENTSO-E consultation finder carried no consultations")
    return LISTING, list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    return bool(_OFF_TOPIC.search(candidate.url))


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.get_text(" ", strip=True).split())
        if len(title) > 8:
            candidate.title = title
    main = soup.find("main") or soup
    text = html_to_text(main)
    m = _OPENED.search(text)
    if m:
        candidate.publication_date = _parse(m.group(1), m.group(2), m.group(3))
    # The deadline is the fact a reader acts on, and it is only on this page,
    # so state it in the text the analysis sees rather than leaving the model
    # to infer it from "Closes".
    c = _CLOSES.search(text)
    if c:
        closing = _parse(c.group(2), c.group(3), c.group(4))
        if closing:
            label = "closed" if c.group(1).lower() == "closed" else "closes"
            text = f"Consultation {label} {closing}.\n\n{text}"
    return text[:MAX_CONTENT_CHARS]
