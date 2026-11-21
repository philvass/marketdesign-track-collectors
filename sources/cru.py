"""CRU — the Commission for Regulation of Utilities, Ireland's energy and water
regulator.

Discovery: the news pages, read through the site's own content API
(api.cru.ie, the read-only API that cru.ie itself is built from; its
robots.txt restricts nothing). Each news item is returned whole with its date,
lead and body, so nothing has to be rendered.

CRU announces here its decisions and consultations on network tariffs and
their structure, connection policy, demand flexibility, retail market rules
and security of supply. It also regulates gas, water, and electrical and gas
safety, so a title-and-lead filter keeps the electricity-market items and
drops prosecutions of unregistered contractors, safety campaigns, water
charges and corporate notices.

Deliberately not read: the publications library. cru.ie's robots.txt allows
the library's landing page but disallows every document page under
/publications/, and the library is not exposed through the content API, so
the decision and consultation papers themselves are left alone. The news
items announce the significant ones and link to them.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "CRU (Commission for Regulation of Utilities)"
DOCUMENT_TYPE = "REGULATOR"

API = "https://api.cru.ie/api/pages/"
SITE_NEWS = "https://www.cru.ie/en-ie/about-us/news/"
FETCH = 40                                   # newest news pages asked for
MAX_ITEMS = 25

_ELECTRICITY = re.compile(
    r"electricity|power system|network tariff|tariff structure|use of system|grid connection|"
    r"connection polic|large energy user|data centre|flexib|demand response|demand side|"
    r"capacity market|capacity auction|security of supply|generation|renewable|offshore wind|"
    r"storage|interconnect|smart meter|time.of.use|dynamic pric|supplier|retail market|"
    r"wholesale|price control|PR6|PR5|ESB Networks|EirGrid|\bSEM\b|PSO levy|microgen|"
    r"energy communit|private wires|hybrid connection|curtailment|constraint|"
    r"energy (market|polic|price|cost|customer|offer|bill)", re.I)
_OFF_TOPIC = re.compile(
    r"convicted|prosecut|registered electrical contractor|registered gas installer|safe electric|"
    r"carbon monoxide|gas safety|electrical safety|safety annual report|petroleum|\bLPG\b|"
    r"uisce|water charg|wastewater|gender pay|recruit|careers|appoint|commissioner\b.*\bterm|"
    r"annual report|strategic plan|christmas|office clos|Gas Networks Ireland|biomethane", re.I)

_LEADS: dict[str, str] = {}


def discover(session):
    r = get_with_retry(session, API, timeout=45, params={
        "type": "newsapp.NewsContentPage", "order": "-first_published_at",
        "limit": FETCH, "fields": "lead_text,published_date"})
    if not r.content.strip():
        raise UpstreamUnavailable("CRU content API returned an empty response")
    try:
        items = r.json()["items"]
    except (ValueError, KeyError) as exc:
        raise CollectorError(f"CRU content API returned no item list: {exc!r}")
    if not items:
        raise CollectorError("CRU content API listed no news pages: page type changed")

    found: dict[str, Candidate] = {}
    for item in items:
        meta = item.get("meta") or {}
        title = " ".join((item.get("title") or "").split())
        slug = meta.get("slug") or ""
        lead = " ".join((item.get("lead_text") or meta.get("search_description") or "").split())
        if not title or not slug or not item.get("id"):
            continue
        if _OFF_TOPIC.search(title) or not _ELECTRICITY.search(f"{title} {lead}"):
            continue
        day = (item.get("published_date") or meta.get("first_published_at") or "")[:10]
        sid = f"cru-news-{item['id']}"
        _LEADS[sid] = lead
        # The public page is linked; the text is fetched from the API record of the same page.
        found.setdefault(sid, Candidate(
            sid, title, day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
            f"{SITE_NEWS}{slug}/"))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise QuietRun("No electricity-market item among the newest CRU news pages")
    return f"{API}?type=newsapp.NewsContentPage", list(found.values())


def _blocks(node, out: list[str]) -> None:
    """Collect the rich-text blocks of a page body in reading order."""
    if isinstance(node, dict):
        if node.get("type") == "html" and isinstance(node.get("value"), str):
            out.append(html_to_text(BeautifulSoup(node["value"], "html.parser")))
            return
        for value in node.values():
            _blocks(value, out)
    elif isinstance(node, list):
        for value in node:
            _blocks(value, out)
    elif isinstance(node, str) and "<p" in node:
        out.append(html_to_text(BeautifulSoup(node, "html.parser")))


def fetch_content(session, candidate: Candidate) -> str:
    page_id = candidate.source_id.rsplit("-", 1)[-1]
    r = get_with_retry(session, f"{API}{page_id}/", timeout=45)
    try:
        page = r.json()
    except ValueError as exc:
        raise CollectorError(f"CRU content API returned invalid JSON for page {page_id}: {exc}")
    parts = [candidate.title]
    lead = " ".join((page.get("lead_text") or _LEADS.get(candidate.source_id) or "").split())
    if lead:
        parts.append(lead)
    body: list[str] = []
    _blocks(page.get("body"), body)
    parts.extend(b for b in body if b and b != lead)
    text = "\n\n".join(parts)
    if len(text) < 200:
        raise CollectorError(f"CRU news page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
