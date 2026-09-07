"""PSE (pse.pl) — Polish TSO.

Discovery: the Liferay asset-publisher feeds behind the operator
communications and press listings. Poland runs a capacity market and reformed
its balancing market in 2024, so its operator notices carry design content that
no other source here reports.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "PSE"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.pse.pl"
FEEDS = [
    f"{BASE}/komunikaty-osp/-/asset_publisher/UORxdCP4f0LA/rss",
    f"{BASE}/biuro-prasowe/aktualnosci/-/asset_publisher/fwWgbbtxcZUt/rss",
]


ATOM = "http://www.w3.org/2005/Atom"


def _date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def discover(session):
    found: dict[str, Candidate] = {}
    empty = 0
    for feed in FEEDS:
        try:
            r = get_with_retry(session, feed, timeout=45)
        except CollectorError:
            empty += 1
            continue
        if not r.content.strip():
            empty += 1
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        # Liferay serves Atom here, not RSS, so both shapes are handled.
        items = root.findall(".//item") or root.findall(f".//{{{ATOM}}}entry")
        for item in items:
            title = " ".join((item.findtext("title")
                              or item.findtext(f"{{{ATOM}}}title") or "").split())
            link_el = item.find(f"{{{ATOM}}}link")
            link = ((item.findtext("link") or "").strip()
                    or (link_el.get("href") if link_el is not None else ""))
            if not title or not link:
                continue
            raw_date = (item.findtext("pubDate")
                        or item.findtext(f"{{{ATOM}}}published")
                        or item.findtext(f"{{{ATOM}}}updated"))
            sid = f"pse-{slugify(link.rstrip('/').split('/')[-1] or title)}"
            found.setdefault(sid, Candidate(sid, title, _date(raw_date), link))

    if not found:
        if empty == len(FEEDS):
            raise UpstreamUnavailable("PSE feeds returned nothing")
        raise CollectorError("PSE discovery returned no candidates")
    return " + ".join(FEEDS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = (soup.select_one(".journal-content-article") or soup.select_one(".asset-full-content")
            or soup.find("main") or soup)
    return html_to_text(body)[:MAX_CONTENT_CHARS]
