"""EirGrid (eirgrid.ie) — Irish TSO and, with SONI, the SEM market operator.

Discovery: the site's JSON news endpoint. Ireland runs the capacity market
that the reliability-option design is usually argued from, so its consultations
and market notices carry weight beyond their system size.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "EirGrid"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.eirgrid.ie"
NEWS_API = f"{BASE}/api/news"


def _date(raw) -> str | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return None


def discover(session):
    r = get_with_retry(session, NEWS_API, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("EirGrid news API returned an empty response")
    try:
        payload = r.json()
    except ValueError as exc:
        raise CollectorError(f"EirGrid news API returned invalid JSON: {exc}")

    found: dict[str, Candidate] = {}
    for item in payload.get("results") or []:
        title = " ".join(BeautifulSoup(str(item.get("title") or ""), "html.parser")
                         .get_text(" ", strip=True).split())
        alias = ((item.get("path") or {}).get("alias") or "").strip()
        if not title or not alias:
            continue
        link = urljoin(BASE, alias)
        sid = f"eirgrid-{slugify(alias.rstrip('/').split('/')[-1] or title)}"
        found.setdefault(sid, Candidate(sid, title, _date(item.get("created")), link))

    if not found:
        raise UpstreamUnavailable("EirGrid news API returned no items")
    return NEWS_API, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.find("main") or soup.find("article") or soup
    return html_to_text(body)[:MAX_CONTENT_CHARS]
