"""Slovak Ministry of Economy (Ministerstvo hospodárstva SR, MH SR).

The ministry is responsible for energy policy and drafts the Energy Act and
the act on support for renewables; it also runs the auctions for supported
generation and the price-compensation schemes.

Discovery: the Atom feed the site advertises at /feed, fifty entries from the
press releases, the "top" stories and the notices, each with title, link, date
and summary. robots.txt allows every agent. The article page is fetched for
the full text.

The ministry also covers industry, trade, investment and oil and gas supply,
so a filter on title and summary lets through only electricity: the market
and its legislation, prices and compensation, renewable support and auctions,
grids, nuclear and other generation capacity. Slovak only.

Not read: the topic pages under /energetika, which hold standing documents
and calls rather than announcements, and Slov-Lex, the government's
legislative portal, where the drafts themselves are lodged.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Slovak Ministry of Economy (MH SR)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

FEED = "https://www.economy.gov.sk/feed"
MAX_ENTRIES = 30                # entries looked at, newest first
_ATOM = "{http://www.w3.org/2005/Atom}"

_ELECTRICITY = re.compile(
    r"elektr|energetick\w+ (?:trh|zákon|legislatív|politik|kríz)|zákon\w* o energetike|"
    r"cen\w+ energi|dostupn\w+ energi|energopomoc|energodotác|obnoviteľn|\bOZE\b|veter|fotovolt|"
    r"akceleračn|jadrov|Mochov|kogenerač|prenosov|distribučn|sústav|aukci\w+ na|výkupc|"
    r"batéri|uskladň|flexibil|kapacitn", re.I)


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("MH SR feed returned an empty response")
    try:
        entries = ET.fromstring(r.content).findall(f"{_ATOM}entry")
    except ET.ParseError as exc:
        raise CollectorError(f"MH SR feed did not parse: {exc}")
    if not entries:
        raise CollectorError("MH SR feed carried no entries: format changed")
    found: dict[str, Candidate] = {}
    for entry in entries[:MAX_ENTRIES]:
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        link_el = entry.find(f"{_ATOM}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        summary = " ".join(BeautifulSoup(entry.findtext(f"{_ATOM}summary") or "", "html.parser")
                           .get_text(" ", strip=True).split())
        if not title or not link or not _ELECTRICITY.search(f"{title} {summary}"):
            continue
        day = re.match(r"\d{4}-\d{2}-\d{2}", (entry.findtext(f"{_ATOM}updated") or "").strip())
        sid = f"sk_gov-{slugify(link.rstrip('/').split('/')[-1], 140)}"
        found.setdefault(sid, Candidate(sid, title, day.group(0) if day else None, link))
    if not found:
        raise UpstreamUnavailable("No electricity item in the MH SR feed this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.find("article") or soup.find("main") or soup)
    if len(text) < 200:
        raise CollectorError(f"MH SR page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
