"""EirGrid (eirgrid.ie) — Irish TSO and, with SONI, the SEM market operator.

Discovery: the news page, whose embedded page data lists the news items.
Ireland runs the capacity market that the reliability-option design is usually
argued from, so its consultations and market notices carry weight beyond their
system size.

This adapter used to call the site's JSON endpoint at /api/news. EirGrid's
robots.txt disallows /api/ for every agent, so that route is no longer used;
the same items are in the data the allowed /news page carries for its own
rendering. The source ids are built as before, so the state carries over.
"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "EirGrid"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.eirgrid.ie"
NEWS = f"{BASE}/news"


def _date(raw) -> str | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return None


def _news_nodes(node, out: list[dict]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "node--news" and isinstance(node.get("path"), dict):
            out.append(node)
            return
        for value in node.values():
            _news_nodes(value, out)
    elif isinstance(node, list):
        for value in node:
            _news_nodes(value, out)


def discover(session):
    r = get_with_retry(session, NEWS, timeout=45)
    tag = BeautifulSoup(r.text, "html.parser").find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        raise CollectorError("EirGrid news page carried no embedded page data")
    try:
        data = json.loads(tag.string)
    except ValueError as exc:
        raise CollectorError(f"EirGrid embedded page data did not parse: {exc}")
    nodes: list[dict] = []
    _news_nodes(data, nodes)

    found: dict[str, Candidate] = {}
    for item in nodes:
        title = " ".join(BeautifulSoup(str(item.get("title") or ""), "html.parser")
                         .get_text(" ", strip=True).split())
        alias = ((item.get("path") or {}).get("alias") or "").strip()
        if not title or not alias:
            continue
        link = urljoin(BASE, alias)
        sid = f"eirgrid-{slugify(alias.rstrip('/').split('/')[-1] or title)}"
        found.setdefault(sid, Candidate(sid, title, _date(item.get("created")), link))

    if not found:
        raise CollectorError("EirGrid news page data listed no news items: structure changed")
    return NEWS, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.find("main") or soup.find("article") or soup
    return html_to_text(body)[:MAX_CONTENT_CHARS]
