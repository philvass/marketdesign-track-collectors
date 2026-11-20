"""Fingrid — the Finnish transmission system operator.

Discovery: Fingrid's own RSS feed of news and releases in Finnish
(/api/rss/news?language=fi), allowed by robots.txt. The feed carries the full
text of each release in its description, so the article pages are fetched
only if that text is missing. Finnish is read because it is the complete
edition; the English one omits some market notices.

Fingrid runs the Finnish reserve markets (FCR, aFRR, mFRR), balance service
and its pricing, the grid-service tariffs, the connection queue and its
priority procedure, Datahub, and the Finnish side of the Nordic and European
balancing platforms and capacity calculation. Its market notices, press
releases and consultations all appear in this one feed.

Not read, by feed category: disturbance and deviation notices (Häiriöt ja
poikkeamat), the customer magazine Fingrid-lehti, and items that are only
about construction projects. By title: interim reports, shareholder and
financing announcements, appointments, webinars and training sessions.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "Fingrid"
DOCUMENT_TYPE = "TSO"

FEED = "https://www.fingrid.fi/api/rss/news?language=fi"
MAX_ITEMS = 25

_SKIP_CATEGORIES = {"Häiriöt ja poikkeamat", "Fingrid-lehti"}
_MARKET_CATEGORIES = {"Sähkömarkkinat", "Sähköjärjestelmä", "Kuulemiset ja konsultaatiot"}
_CORPORATE = re.compile(
    r"johdon katsaus|puolivuosikatsaus|osavuosikatsaus|tilinpäätös|osakkeenomistaj|yhtiökokou|"
    r"joukkovelkakirja|luottoluokitu|nimity|hallituksen puheenjohtaja|toimitusjohtajaksi|"
    r"webinaari|koulutuksen|asiakastyytyväisyy|palkitsi|fingrid-lehti|huoltokatko", re.I)

_TEXT: dict[str, str] = {}


def discover(session):
    r = get_with_retry(session, FEED, timeout=60)
    if not r.content.strip():
        raise UpstreamUnavailable("Fingrid news feed returned an empty response")
    try:
        root = ET.fromstring(r.content.lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError as exc:
        raise CollectorError(f"Fingrid news feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("Fingrid news feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for item in items:
        guid = (item.findtext("guid") or "").strip().lower()
        link = (item.findtext("link") or "").strip()
        title = " ".join((item.findtext("title") or "").split())
        cats = {(c.text or "").strip() for c in item.findall("category")}
        if not guid or not title or "fingrid.fi/" not in link:
            continue
        if cats & _SKIP_CATEGORIES or _CORPORATE.search(title):
            continue
        if "Projektit" in cats and not cats & _MARKET_CATEGORIES:
            continue
        try:
            day = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            day = None
        sid = f"fingrid-{guid}"
        body = BeautifulSoup(item.findtext("description") or "", "html.parser").get_text("\n")
        _TEXT[sid] = "\n".join(line.strip() for line in body.splitlines() if line.strip())
        found.setdefault(sid, Candidate(sid, title, day, link))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise QuietRun("Fingrid news feed carried only disturbance and magazine items this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    text = _TEXT.get(candidate.source_id, "")
    if len(text) >= 200:
        return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = html_to_text(soup.select_one("main") or soup)
    if len(text.strip()) < 200:
        raise CollectorError(f"Fingrid page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
