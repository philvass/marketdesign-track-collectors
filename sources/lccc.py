"""LCCC — Low Carbon Contracts Company, the UK government-owned counterparty
to Contracts for Difference, and with its sister Electricity Settlements
Company the settlement body for the Capacity Market.

Discovery: two server-rendered pages on lowcarboncontracts.uk.

1. The news page, whose first screen holds the four newest notices: levy rate
   and reserve determinations, market reference prices, scheme announcements.
   robots.txt forbids the paged and filtered views (/news/?...), so only that
   first screen is read; at the company's pace of a few notices a month it is
   enough for a daily run.
2. Guidance and publications, one page that lists every document with its
   posting date: CfD standard terms, metering and milestone guidance,
   methodologies. It is not in date order, so the cards are sorted here and
   the newest taken.

Dropped by title: annual reports, governance papers and careers items, and the
hydrogen and carbon-capture contract paperwork, which is not electricity
market design.

Content: the notice or publication page, and for a publication the text of
its first PDF as well, since the page is only a short introduction to it.
"""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Low Carbon Contracts Company (LCCC)"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://www.lowcarboncontracts.uk"
NEWS = f"{BASE}/news/"
PUBLICATIONS = f"{BASE}/resources/guidance-and-publications/"
MAX_PUBLICATIONS = 16

_NEWS_CARD = re.compile(
    r'class="date">\s*Posted:?\s*(\d{2})\.(\d{2})\.(\d{4})\s*</p>\s*<h3>\s*'
    r'<a href="(/news/[^"?#]+)">([^<]+)</a>', re.S)
_PUB_CARD = re.compile(
    r'<a href="(/resources/guidance-and-publications/[^"?#]+)"[^>]*class="card-img.*?'
    r'class="date">\s*Posted:?\s*(\d{2})\.(\d{2})\.(\d{4})\s*</p>\s*'
    r'<h4 class="card-title">([^<]+)</h4>', re.S)
_SKIP = re.compile(
    r"annual report|annual performance|report and accounts|terms of reference|committee|"
    r"strategy|careers|rewards|gender pay|investment report|framework document|publication scheme|slide pack|conference|"
    r"hydrogen|\bLCHA\b|\bLCHS\b|\bHAR\d|carbon capture|\bCCUS\b|\bICC\b|dispatchable power agreement",
    re.I)
_TAIL = re.compile(r"\n\s*(Quick Links|Back to all news|Related)\s*\n", re.I)


def _slug(href: str) -> str:
    return slugify(href.rstrip("/").split("/")[-1])


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []

    try:
        html = get_with_retry(session, NEWS, timeout=45).text
        cards = _NEWS_CARD.findall(html)
        if not cards:
            errors.append("news: no cards matched")
        for dd, mm, yyyy, href, title in cards:
            title = " ".join(unescape(title).split())
            if _SKIP.search(title):
                continue
            sid = f"lccc-news-{_slug(href)}"
            found.setdefault(sid, Candidate(sid, title, f"{yyyy}-{mm}-{dd}", urljoin(BASE, href)))
    except CollectorError as exc:
        errors.append(f"news: {exc}")

    try:
        html = get_with_retry(session, PUBLICATIONS, timeout=60).text
        cards = _PUB_CARD.findall(html)
        if not cards:
            errors.append("publications: no cards matched")
        cards.sort(key=lambda c: (c[3], c[2], c[1]), reverse=True)
        n = 0
        for href, dd, mm, yyyy, title in cards:
            title = " ".join(unescape(title).split())
            sid = f"lccc-pub-{_slug(href)}"
            if _SKIP.search(f"{title} {href.replace('-', ' ')}") or sid in found:
                continue
            found[sid] = Candidate(sid, title, f"{yyyy}-{mm}-{dd}", urljoin(BASE, href))
            n += 1
            if n >= MAX_PUBLICATIONS:
                break
    except CollectorError as exc:
        errors.append(f"publications: {exc}")

    if not found:
        raise CollectorError("LCCC pages yielded no items: markup changed. " + " | ".join(errors)[:300])
    return f"{NEWS} + {PUBLICATIONS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    pdf = next((urljoin(BASE, a["href"]) for a in body.find_all("a", href=True)
                if a["href"].startswith("/documents/") and a["href"].lower().endswith(".pdf")), None)
    text = html_to_text(body)
    cut = _TAIL.search(text)
    if cut and cut.start() > 150:
        text = text[:cut.start()]
    parts = [text.strip()]
    if pdf and candidate.source_id.startswith("lccc-pub-"):
        try:
            doc = extract_pdf_text(get_with_retry(session, pdf, timeout=90).content).strip()
        except Exception:        # a scanned or oversized PDF leaves the page text standing
            doc = ""
        if doc:
            parts.append(f"--- Document ---\n{doc}")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
