"""HEnEx — the Hellenic Energy Exchange (EnEx Group), operator of the Greek
day-ahead, intraday and energy derivatives markets, with its clearing house
EnExClear.

Discovery: the news feed of the group's site (RSS 1.0), which robots.txt
allows. It carries the exchange's announcements with their dates; the article
pages are server-rendered. The Greek edition is read because the feed is
published for it.

What matters here are the announcements on market rules: changes to products
and their withdrawal, price tick and order parameters, coupling changes
(SIDC, intraday auctions), new platforms. Dropped by title: the monthly
clearing-fund size notices, certification exams and seminars, general
meetings, market-maker obligation notices and the gas trading platform.

Not read: the two feeds on the home page, which are operational (intraday
auction cancellations, call-auction times), and the rulebook library, whose
decisions are arranged by decision number rather than by date and cannot be
read newest-first. The regulator's approvals of those rulebooks arrive through
the `raaey` adapter.
"""
from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "HEnEx (Hellenic Energy Exchange)"
DOCUMENT_TYPE = "MARKET_OPERATOR"

FEED = "https://www.enexgroup.gr/el/web/guest/news/-/asset_publisher/h9B7UvH67xPr/rss"
MAX_ITEMS = 20

_RSS = "{http://purl.org/rss/1.0/}"
_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_ID = re.compile(r"/content/(?:id/)?([A-Za-z0-9_-]+)")
# Matched against the title with accents removed and lower-cased.
_DROP = re.compile(
    r"υψος κεφαλαιου εκκαθαρισης|εξετασ|σεμιναρι|πιστοποι|γενικη συνελευση|"
    r"ειδικου διαπραγματευτη|φυσικου αεριου|οικονομικ\w+ καταστασ|αργι")


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("HEnEx news feed returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"HEnEx news feed did not parse: {exc}")
    # The site serves RSS 1.0 here and Atom on its other feeds; accept either.
    entries = []
    for item in root.iter(f"{_RSS}item"):
        entries.append((item.findtext(f"{_RSS}title"), item.findtext(f"{_RSS}link"),
                        item.findtext(f"{_DC}date")))
    for item in root.iter(f"{_ATOM}entry"):
        link = item.find(f"{_ATOM}link")
        entries.append((item.findtext(f"{_ATOM}title"), link.get("href") if link is not None else "",
                        item.findtext(f"{_ATOM}published") or item.findtext(f"{_ATOM}updated")))
    if not entries:
        raise CollectorError("HEnEx news feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for title, link, stamp in entries:
        title = " ".join((title or "").split())
        title = re.sub(r"\s*\(Copy\)\s*$", "", title)
        link = (link or "").strip()
        m = _ID.search(link)
        if not title or not m or _DROP.search(_norm(title)):
            continue
        d = re.match(r"(\d{4}-\d{2}-\d{2})", stamp or "")
        sid = f"henex-{m.group(1).lower()}"
        found.setdefault(sid, Candidate(sid, title, d.group(1) if d else None, link.split("?")[0]))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise UpstreamUnavailable("No market-rule announcement in the HEnEx news feed this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".asset-full-content") or soup.select_one(".asset-content")
    if body is None:
        raise CollectorError(f"HEnEx announcement body not found: {candidate.url}")
    text = f"{candidate.title}\n\n{html_to_text(body)}"
    if len(text) < 200:
        raise CollectorError(f"HEnEx announcement yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
