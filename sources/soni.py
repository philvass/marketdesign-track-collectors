"""SONI — the electricity transmission system operator for Northern Ireland
and, with EirGrid, operator of the all-island market and system.

Discovery: the news page of soni.ltd.uk. The page is built by scripts, but the
server sends the newest news items inside it as embedded page data (title,
date and address of each), so the page is read plainly and that data is
parsed; nothing is rendered. robots.txt allows the news pages and disallows
the site's /api/ endpoints, which are therefore not used, although the page
itself calls them to load older items. Only the newest items (about nine) are
visible this way, which is enough for a source visited every day.

SONI publishes here its winter outlook and capacity statements, forward work
plan, system-services and connection arrangements for Northern Ireland, and
all-island items issued jointly with EirGrid. Corporate items (accreditations,
partnerships, sponsorship, appointments, community funds) are dropped by
title.

Not read: the publications library and the consultation portal, which are
loaded only through the closed API.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "SONI"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.soni.ltd.uk"
NEWS = f"{BASE}/news"

_CORPORATE = re.compile(
    r"accreditation|partnership|sponsor|appoint|chief executive|board|award|apprentice|graduate|"
    r"scholarship|community (fund|benefit)|charity|schools?\b|careers|gender pay|menopause|"
    r"diversity|volunteer|annual report|financial results|female leaders|engagement strategy", re.I)


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


def _page_data(html: str, url: str) -> dict:
    tag = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        raise CollectorError(f"SONI page carried no embedded page data: {url}")
    try:
        return json.loads(tag.string)
    except ValueError as exc:
        raise CollectorError(f"SONI embedded page data did not parse: {exc}")


def discover(session):
    r = get_with_retry(session, NEWS, timeout=45)
    nodes: list[dict] = []
    _news_nodes(_page_data(r.text, NEWS), nodes)
    if not nodes:
        raise CollectorError("SONI news page data listed no news items: structure changed")
    found: dict[str, Candidate] = {}
    for node in nodes:
        alias = (node.get("path") or {}).get("alias") or ""
        title = " ".join((node.get("title") or "").split())
        if not alias.startswith("/news/") or not title or _CORPORATE.search(title):
            continue
        day = (node.get("created") or "")[:10]
        sid = f"soni-{slugify(alias.rsplit('/', 1)[-1])}"
        found.setdefault(sid, Candidate(
            sid, title, day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None, f"{BASE}{alias}"))
    return NEWS, list(found.values())


def _html_fields(node, out: list[str]) -> None:
    """Collect the processed rich-text fields of an article in reading order."""
    if isinstance(node, dict):
        processed = node.get("processed")
        if isinstance(processed, str) and processed.strip():
            out.append(html_to_text(BeautifulSoup(processed, "html.parser")))
            return
        for value in node.values():
            _html_fields(value, out)
    elif isinstance(node, list):
        for value in node:
            _html_fields(value, out)


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body_parts: list[str] = []
    try:
        page = _page_data(r.text, candidate.url)
        _html_fields(((page.get("props") or {}).get("pageProps") or {}).get("node"), body_parts)
    except CollectorError:
        pass
    text = "\n\n".join(p for p in body_parts if p)
    if len(text) < 200:                                # fall back to whatever the server rendered
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        text = html_to_text(soup.select_one("main") or soup)
    if len(text.strip()) < 200:
        raise CollectorError(f"SONI page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
