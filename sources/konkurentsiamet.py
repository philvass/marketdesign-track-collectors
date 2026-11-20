"""Konkurentsiamet — the Estonian Competition Authority, which is also the
energy regulator.

Discovery: the site's RSS feed of news, in Estonian because the English
edition carries only a few translated items. robots.txt allows the feed and
the news pages (it closes only the search and admin paths).

The authority approves network tariffs and their methodologies, the
transmission operator's development plan, the terms of balancing and
connection, and enforces REMIT; it announces its public consultations as news
items. It is also the competition, post, rail and water authority, so a
title-and-lead filter keeps only electricity items before anything is fetched.

Not read: the document register, which lists every letter the office sends,
and the search pages, which robots.txt closes.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Konkurentsiamet (Estonian Competition Authority)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.konkurentsiamet.ee"
FEED = f"{BASE}/rss-feeds/rss.xml"
MAX_ITEMS = 25

_ELECTRICITY = re.compile(
    r"elekt|võrgutasu|võrguteenus|põhivõr|jaotusvõr|võrguettev|Elering|energiatur|energiasektor|"
    r"energiabörs|bilansi|sagedusreserv|reservvõimsus|varustuskind|taastuvenerg|päritolutunnistus|"
    r"REMIT|turureegl|võrgueeskir|liitumistasu|salvest|paindlikkus|desünkroni|sünkroni|"
    r"süsteemihaldur|Nord Pool|hulgitur", re.I)


def _date(raw: str | None) -> str | None:
    try:
        return parsedate_to_datetime((raw or "").strip()).date().isoformat()
    except (TypeError, ValueError):
        return None


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("Konkurentsiamet feed returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"Konkurentsiamet feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("Konkurentsiamet feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        lead = " ".join(BeautifulSoup(item.findtext("description") or "", "html.parser")
                        .get_text(" ", strip=True).split())
        if not title or not link:
            continue
        if not _ELECTRICITY.search(f"{title} {lead}"):
            continue
        if re.search(r"gaasi", title, re.I) and not re.search(r"elekt|energiatur", title, re.I):
            continue                                   # gas network items share the vocabulary
        sid = f"konkurentsiamet-{slugify(link.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, _date(item.findtext("pubDate")), link))
        if len(found) >= MAX_ITEMS:
            break
    # The feed mixes competition, post and rail news; a stretch with no
    # electricity item in it is a quiet spell, not a fault.
    if not found:
        raise QuietRun("No electricity item in the Konkurentsiamet feed this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    for modal in soup.select(".modal"):
        modal.decompose()
    body = soup.select_one("article") or soup.select_one("main") or soup
    text = html_to_text(body)
    if len(text.strip()) < 200:
        raise CollectorError(f"Konkurentsiamet page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
