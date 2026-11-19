"""Estonian Ministry of Climate (Kliimaministeerium) — the ministry responsible
for energy.

Discovery: the ministry's RSS news feed, in Estonian because the English
edition carries only a selection. robots.txt allows the feed and the news
pages (it closes only the search and admin paths).

Estonian electricity law and policy is announced here: amendments to the
Electricity Market Act, renewable auctions, the capacity mechanism, network
charges, the energy-sector development plan and desynchronisation follow-up.
The ministry also covers environment, transport, construction and the sea, so
a title-and-lead filter keeps only electricity items before anything is
fetched.

Not read: the draft-legislation register (eelnoud.valitsus.ee), which is a
separate government system, and the search pages, which robots.txt closes.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Estonian Ministry of Climate (Kliimaministeerium)"
DOCUMENT_TYPE = "GOVERNMENT"
# Ministries announce consultations days after the texts are dated.
MAX_AGE_DAYS = 7

BASE = "https://kliimaministeerium.ee"
FEED = f"{BASE}/rss-feeds/rss.xml"
MAX_ITEMS = 25

# Title words that mark an electricity item on their own.
_ELECTRICITY = re.compile(
    r"elektri(?!auto|kaubik|buss|rong|tõuke|sõiduk|liikur)|elektrit\b|võrgutasu|põhivõr|jaotusvõr|Elering|"
    r"Elektrilevi|energiatur|energiamajandus|energiahin|energiavarustus|energiajulge|varustuskind|"
    r"taastuvenerg|taastuvelek|vähempakkum|tuulepar|tuuleenerg|tuulehoo|meretuul|päikeseenerg|"
    r"päritolutunnistus|salvest|võimsusmehhanism|juhitav\w* võimsus|tuumaenerg|tuumajaam|"
    r"sünkroni|Estlink|energiaminist|energeetikanõukogu", re.I)
# The lead mentions energy in passing far more often, so there the test is narrower.
_LEAD = re.compile(
    r"elektritur|elektrivõr|elektrisüsteem|võrgutasu|taastuvelek|võimsusmehhanism|Elering|"
    r"elektrihin|vähempakkum", re.I)


def _date(raw: str | None) -> str | None:
    try:
        return parsedate_to_datetime((raw or "").strip()).date().isoformat()
    except (TypeError, ValueError):
        return None


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("Kliimaministeerium feed returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"Kliimaministeerium feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("Kliimaministeerium feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        lead = " ".join(BeautifulSoup(item.findtext("description") or "", "html.parser")
                        .get_text(" ", strip=True).split())
        if not title or not link:
            continue
        if not (_ELECTRICITY.search(title) or _LEAD.search(lead)):
            continue
        sid = f"ee-gov-{slugify(link.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, _date(item.findtext("pubDate")), link))
        if len(found) >= MAX_ITEMS:
            break
    # Most of the feed is environment and transport; a stretch with no
    # electricity item in it is a quiet spell, not a fault.
    if not found:
        raise UpstreamUnavailable("No electricity item in the Kliimaministeerium feed this run")
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
        raise CollectorError(f"Kliimaministeerium page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
