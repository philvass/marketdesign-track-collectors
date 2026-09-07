"""CNMC (cnmc.es) — Spanish competition and markets regulator.

Discovery: the site RSS feed, filtered to energy items. CNMC covers several
sectors from one newsroom, so the filter is deliberately narrow: circulars,
resolutions and consultations naming electricity, the system operator or the
market. Spain is the largest European market with no other source here.
"""
from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from urllib.parse import urljoin

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  extract_pdf_text, html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "CNMC"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.cnmc.es"
FEED = f"{BASE}/rss.xml"

ENERGY = re.compile(
    r"\b(electric|eléctric|energía|energ[ée]tic|gas|red el[ée]ctrica|sistema el[ée]ctrico|"
    r"peaje|retribuci[óo]n|autoconsumo|circular|hidrógeno|renovable|mercado el[ée]ctrico)\b",
    re.I)


def _date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("CNMC RSS returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"CNMC RSS did not parse: {exc}")

    found: dict[str, Candidate] = {}
    for item in root.findall(".//item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        summary = item.findtext("description") or ""
        if not title or not link:
            continue
        if not (ENERGY.search(title) or ENERGY.search(summary)):
            continue
        sid = f"cnmc-{slugify(link.rstrip('/').split('/')[-1] or title)}"
        found.setdefault(sid, Candidate(sid, title, _date(item.findtext("pubDate")), link))

    if not found:
        raise UpstreamUnavailable("CNMC RSS carried no energy items this run")
    return f"{FEED} (energy filter)", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one("main") or soup.select_one(".region-content") or soup
    text = html_to_text(body)

    # CNMC node pages are stubs: the decision itself is the attached PDF.
    pdf = soup.select_one('a[href*="/sites/default/files/"][href$=".pdf"]')
    if pdf:
        try:
            pr = get_with_retry(session, urljoin(BASE, pdf["href"]), timeout=90)
            pdf_text = extract_pdf_text(pr.content)
            if len(pdf_text.strip()) > len(text.strip()):
                text = f"{candidate.title}\n\n{pdf_text}"
        except CollectorError:
            pass
    return text[:MAX_CONTENT_CHARS]
