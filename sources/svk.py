"""Svenska kraftnät — the Swedish transmission system operator.

Discovery: the site's own RSS feed of all news (/Api/RSSFeed/GetAllNews),
allowed by robots.txt. The feed is the whole archive in one response, grouped
by category rather than sorted, so the items are sorted by their pubDate here
and only the newest are kept. Swedish is read because the English site carries
a small subset.

Svenska kraftnät runs the Swedish balancing markets (FCR, aFRR, mFRR, FFR), the
strategic reserve, the EPAD auctions, the settlement structure and the Swedish
side of the Nordic and European market-coupling and network-code work. Those
items sit in the market categories of the news archive (elmarknad, europeisk
elmarknad, balansansvar, nätkoder, strukturförändringar, NBM) and in the
general news.

Not read: the project pages under /utveckling-av-kraftsystemet/, which are
most of the feed and report line routes, felling and open-house meetings;
technical guidelines for contractors, dam safety, the trainee blog; and, by
title, appointments, recruitment, invitations to meetings and the monthly
statistics notes.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "Svenska kraftnät"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.svk.se"
FEED = f"{BASE}/Api/RSSFeed/GetAllNews"
MAX_ITEMS = 25

_CATEGORY = re.compile(
    r"/press-och-nyheter/nyheter/(elmarknad-allmant|europeisk-elmarknad|balansansvar|"
    r"natkoder|strukturforandringar|nbm|allmanna-nyheter)/")
_DROP = re.compile(
    r"^välkommen|^inbjudan|webbinarium|webbmöte|konferens|\bträffa\b|månadsrapport|"
    r"\bny(tt)? \S*(chef|direktör)|\bblir \S*\s?(chef|direktör)|generaldirektör|överdirektör|"
    r"årsredovisning|delårsrapport|rekryter|\bjobb|trainee|referensgrupp|hyresannons|"
    r"upphandling av (entreprenad|konsult)", re.I)


def discover(session):
    r = get_with_retry(session, FEED, timeout=90)
    if not r.content.strip():
        raise UpstreamUnavailable("Svenska kraftnät news feed returned an empty response")
    try:
        root = ET.fromstring(r.content.lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError as exc:
        raise CollectorError(f"Svenska kraftnät news feed did not parse: {exc}")

    rows = []
    for item in root.iter("item"):
        guid = (item.findtext("guid") or "").strip()
        link = (item.findtext("link") or "").strip()
        title = " ".join((item.findtext("title") or "").split())
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if not guid.isdigit() or not title or not _CATEGORY.search(link):
            continue
        rows.append((when.date().isoformat(), int(guid), title, link))
    if not rows:
        raise CollectorError("Svenska kraftnät news feed carried no market news items: format changed")

    rows.sort(reverse=True)
    found = []
    for day, guid, title, link in rows:
        if _DROP.search(title):
            continue
        found.append(Candidate(f"svk-{guid}", title, day, link))
        if len(found) >= MAX_ITEMS:
            break
    return FEED, found


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    # The timestamp is written relative to today ("Igår, 10.04"), which would
    # change the text, and so its hash, from one day to the next.
    for tag in soup.select("time.timestamp, .pageContentFooter"):
        tag.decompose()
    body = soup.select_one("main") or soup
    text = html_to_text(body)
    if len(text.strip()) < 200:
        raise CollectorError(f"Svenska kraftnät page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
