"""Terna (terna.it) — Italian TSO.

Discovery: the English press-release listing, read through a rendered fetch.
Terna builds both its listings and its article bodies client-side — a plain
request returns about sixty characters of shell — so this source only exists
because core can drive a browser.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  render_html, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Terna"
DOCUMENT_TYPE = "TSO"
NEEDS_BROWSER = True

BASE = "https://www.terna.it"
LISTING = f"{BASE}/en/media/press-releases"
ARTICLE = re.compile(r"/en/media/press-releases/detail/")
_DATE = re.compile(r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
                   r"September|October|November|December)\s+(20\d{2})", re.I)
# The stamp on the article page, month first: "08/13/2026 - 12:02 PM".
_DATE_STAMP = re.compile(r"\b(\d{2})/(\d{2})/(20\d{2})\b")
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}


def discover(session):
    soup = BeautifulSoup(render_html(LISTING, timeout=90, virtual_time_ms=15000), "html.parser")

    found: dict[str, Candidate] = {}
    for a in soup.find_all("a", href=True):
        if not ARTICLE.search(a["href"]):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if len(title) < 20:
            continue
        url = urljoin(BASE, a["href"])
        sid = f"terna-{slugify(url.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, None, url))

    if not found:
        raise CollectorError("Terna listing carried no press releases")
    return LISTING, list(found.values())


# Dates live on the article page, not in the listing cards.
DATE_REFINED_ON_FETCH = True


def fetch_content(session, candidate: Candidate) -> str:
    soup = BeautifulSoup(render_html(candidate.url, timeout=90, virtual_time_ms=12000),
                         "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    # The consent banner is several thousand characters and sits above the
    # article, which pushes the release date out of any sane search window.
    for tag in soup.find_all(attrs={"id": re.compile(r"consent|cookie", re.I)}):
        tag.decompose()
    for tag in soup.find_all(attrs={"class": re.compile(r"consent|cookie", re.I)}):
        tag.decompose()
    if not candidate.publication_date:
        meta = soup.find("meta", attrs={"property": "article:published_time"})
        stamp = (meta.get("content") if meta else None) or ""
        time_el = soup.find("time")
        stamp = stamp or (time_el.get("datetime") if time_el else "") or ""
        if stamp[:4].isdigit():
            candidate.publication_date = stamp[:10]

    # Terna stamps the release in its own element, month first despite the
    # site being Italian: "08/13/2026 - 12:02 PM". Read that rather than
    # searching the body, which yields dates the article talks about — a
    # half-year report "as of 30 June" was being filed under 30 June.
    if not candidate.publication_date:
        el = soup.select_one(".publication-date__time, .cmp--website-publicationdate")
        m = _DATE_STAMP.search(el.get_text(" ", strip=True)) if el else None
        if m:
            try:
                candidate.publication_date = datetime(
                    int(m.group(3)), int(m.group(1)), int(m.group(2))).date().isoformat()
            except ValueError:
                pass

    body = soup.find("main") or soup.find("article") or soup
    text = html_to_text(body)

    if not candidate.publication_date:
        m = _DATE.search(text[:4000])
        if m:
            try:
                candidate.publication_date = datetime(
                    int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))
                ).date().isoformat()
            except (ValueError, KeyError):
                pass
    if len(text.strip()) < 400:
        raise CollectorError(f"Terna article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
