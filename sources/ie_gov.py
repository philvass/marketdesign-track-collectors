"""Irish Department of Climate, Energy and the Environment (DCEE) — the
ministry responsible for energy policy and electricity legislation.

Discovery: the department's own landing page on gov.ie, which shows its latest
press releases, consultations and publications as server-rendered links. The
full lists behind "View all" are gov.ie search pages, and robots.txt disallows
/search/ for every agent, so they are not read; the landing page and the item
pages are allowed. That limits a run to the dozen or so newest items, which is
enough for a source visited every day but means nothing older can be
backfilled by this route.

The landing page shows no dates, so each item's publication date is read from
its own page when it is fetched.

The department also covers climate, waste, marine planning, fisheries and
natural resources, so a title filter keeps the electricity items: renewable
support schemes (RESS, ORESS), offshore wind, grid and interconnection policy,
security of supply, electricity market legislation, storage, demand and
data-centre policy, and energy price measures.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Department of Climate, Energy and the Environment (Ireland)"
DOCUMENT_TYPE = "GOVERNMENT"
# Ministries announce consultations days after the texts are dated.
MAX_AGE_DAYS = 7
# The landing page lists titles only; the date is on each item's page.
DATE_REFINED_ON_FETCH = True

BASE = "https://www.gov.ie"
LANDING = f"{BASE}/en/department-of-climate-energy-and-the-environment/"
MAX_ITEMS = 20

_ITEM = re.compile(
    r"/en/department-of-climate-energy-and-the-environment/"
    r"(press-releases|consultations|publications)/([^/?#]+)/?$")
_ELECTRICITY = re.compile(
    r"electri|\bgrid\b|renewable|\bRESS\b|ORESS|offshore wind|onshore wind|\bwind\b|solar|"
    r"interconnect|security of supply|energy security|capacity market|generation|storage|"
    r"data centre|large energy user|demand flexib|flexib|private wires|microgen|"
    r"energy (bill|price|cost|credit|affordab|market|polic|act|regulat)|power system|"
    r"\bCRU\b|EirGrid|ESB|net-zero industry act|hydrogen strategy|energy communit", re.I)
_OFF_TOPIC = re.compile(r"electric vehicle|\bEV\b|charger grant|research and innovation", re.I)
_PUBLISHED = re.compile(r"Published on:?\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})", re.I)
_UPDATED = re.compile(r"Last updated on:?\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})", re.I)
_FURNITURE = re.compile(
    r"^(Did you find what you were looking for\?|Find what you were looking for\?|"
    r"Help us improve AI search results by|giving your feedback.*|Close|View the file|View)$", re.I)
_KIND = {"press-releases": "Press release", "consultations": "Consultation",
         "publications": "Publication"}


def discover(session):
    r = get_with_retry(session, LANDING, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    titles: dict[str, str] = {}
    links_seen = 0
    for a in soup.find_all("a", href=True):
        m = _ITEM.search(a["href"])
        if not m:
            continue
        links_seen += 1
        url = urljoin(BASE, a["href"])
        text = " ".join(a.get_text(" ", strip=True).split())
        # Picture links to the same item carry no text; keep the longest title seen.
        if len(text) > len(titles.get(url, "")):
            titles[url] = text
    for url, title in titles.items():
        m = _ITEM.search(url)
        # Items shown only as a picture link get their title from the address.
        title = title or m.group(2).replace("-", " ").capitalize()
        if _OFF_TOPIC.search(title) or not _ELECTRICITY.search(title):
            continue
        sid = f"ie-gov-{m.group(1)}-{slugify(m.group(2))}"
        found.setdefault(sid, Candidate(sid, f"{_KIND[m.group(1)]}: {title}", None, url))
        if len(found) >= MAX_ITEMS:
            break
    if not links_seen:
        raise CollectorError("DCEE landing page showed no press-release or consultation links: markup changed")
    # A dozen recent items with none on electricity is a quiet spell, not a fault.
    if not found:
        raise UpstreamUnavailable("No electricity item among the latest DCEE items this run")
    return LANDING, list(found.values())


def _date(text: str) -> str | None:
    m = _PUBLISHED.search(text) or _UPDATED.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    heading = soup.find("h1")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    text = "\n".join(ln for ln in html_to_text(body).splitlines() if not _FURNITURE.match(ln))
    if not candidate.publication_date:
        candidate.publication_date = _date(text[:4000])
    if heading:
        full = " ".join(heading.get_text(" ", strip=True).split())
        kind = candidate.title.split(":", 1)[0]
        if len(full) > 10:
            candidate.title = f"{kind}: {full}"[:300]
    if len(text.strip()) < 200:
        raise CollectorError(f"DCEE page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
