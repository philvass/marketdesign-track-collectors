"""NERC — North American Electric Reliability Corporation (US).

The newsroom (nerc.com/newsroom) is a JavaScript-rendered listing, so it is
fetched with the headless-Chrome render_html path (the same one Terna and EEX
use). NERC is not behind a bot challenge — rendering is only to run the scripts
that build the list. Each card is an anchor to /newsroom/<slug> whose text is
"<Month DD, YYYY> [category] <title>".

NERC develops the mandatory reliability standards; most are engineering, but a
growing set is market-adjacent (inverter-based-resource ride-through, large-load
interconnection, physical/cyber security cost recovery) and it files them at
FERC. The US title filter and significance gate keep only those.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, render_html, html_to_text, slugify, MAX_CONTENT_CHARS
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "NERC"
DOCUMENT_TYPE = "RELIABILITY"

BASE = "https://www.nerc.com"
LISTING = f"{BASE}/newsroom"
MAX_ITEMS = 30

_DATE = re.compile(r"^([A-Z][a-z]{2,8} \d{1,2}, 20\d{2})\s*(.*)$", re.S)
_CATEGORIES = ["Reliability Insights", "Reliability Insight", "Press Release",
               "Headlines", "Podcasts", "Statement", "Blog", "News"]


def _parse(text: str):
    text = " ".join(text.split())
    m = _DATE.match(text)
    if not m:
        return None, None
    raw, rest = m.group(1), m.group(2).strip()
    for cat in _CATEGORIES:
        if rest.startswith(cat):
            rest = rest[len(cat):].strip()
            break
    try:
        date = datetime.strptime(raw, "%B %d, %Y").date().isoformat()
    except ValueError:
        date = None
    return date, rest


def discover(session):
    html = render_html(LISTING, timeout=90, virtual_time_ms=11000)
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Candidate] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.match(r"^/?newsroom/[A-Za-z0-9]", href) or href.rstrip("/").endswith("/newsroom"):
            continue
        date, title = _parse(a.get_text(" ", strip=True))
        if not title or len(title) < 12:
            continue
        url = urljoin(BASE, href)
        sid = f"nerc-{slugify(href.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, date, url))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise UpstreamUnavailable("NERC newsroom rendered no news cards (layout may have changed)")
    return LISTING, list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    return not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    html = render_html(candidate.url, timeout=90, virtual_time_ms=9000)
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find(["h1", "h2"])
    if h1:
        t = " ".join(h1.get_text(" ", strip=True).split())
        if len(t) > 8:
            candidate.title = t
    main = soup.find("main") or soup.find("article") or soup
    text = html_to_text(main)
    if len(text) < 200:  # render sometimes returns the shell before hydration
        text = candidate.title + "\n\nSee the source URL for the full NERC notice."
    return text[:MAX_CONTENT_CHARS]
