"""OKTE — the Slovak short-term electricity market operator.

OKTE organises the Slovak day-ahead and intraday markets, settles imbalances,
keeps the central metering data and the register of guarantees of origin. Its
notices announce consultations on and new versions of its operating rules
(Prevádzkový poriadok), new market products, market-coupling changes, auctions
of guarantees of origin and changes to the collateral rules.

Discovery: the RSS feed of "Oznamy" that the site advertises in its page head,
thirty items with id, title, lead and date. robots.txt restricts one named
crawler only. Slovak: the English feed lags behind.

The notice page is fetched for the full text. A notice that opens a
consultation links the proposed text as a PDF, which is read into the record.

Dropped by title: certificate renewals, service outages, clock changes,
invoicing and portal housekeeping, workshop invitations and the versions of
the technical interface specifications (TŠVD), which are data formats.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "OKTE (Slovak market operator)"
DOCUMENT_TYPE = "MARKET_OPERATOR"

FEED = "https://www.okte.sk/sk/rss/oznamy"
MAX_ITEMS = 20

_ROUTINE = re.compile(
    r"certifikát|odstávk|zimný čas|letný čas|fakturáci|Klientsk\w+ portál|Pozvánka|TŠVD|"
    r"Technickej špecifikáci|Registrácia na testovanie|Kredity v doprave", re.I)

_LEADS: dict[str, str] = {}


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    try:
        items = ET.fromstring(r.content).findall(".//item")
    except ET.ParseError as exc:
        raise CollectorError(f"OKTE feed did not parse: {exc}")
    if not items:
        raise CollectorError("OKTE feed carried no items: format changed")
    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip().replace("http://", "https://", 1)
        guid = (item.findtext("guid") or "").strip()
        if not title or not link or not guid.isdigit() or _ROUTINE.search(title):
            continue
        try:
            day = parsedate_to_datetime((item.findtext("pubDate") or "").replace(" Z", " +0000")
                                        ).date().isoformat()
        except (TypeError, ValueError):
            m = re.search(r"/oznamy/(\d{4}-\d{2}-\d{2})-", link)
            day = m.group(1) if m else None
        sid = f"okte-{guid}"
        _LEADS[sid] = (item.findtext("description") or "").strip()
        found.setdefault(sid, Candidate(sid, title, day, link))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise CollectorError("OKTE feed: every item was filtered out, check the title filter")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("article.bodyText") or soup.find("article")
    if body is None:
        raise CollectorError(f"OKTE notice has no article block: {candidate.url}")
    pdf = body.select_one('a[href$=".pdf"]')
    text = html_to_text(body)
    if pdf and "konzultác" in candidate.title.lower():
        url = urljoin(candidate.url, pdf["href"])
        try:
            doc = extract_pdf_text(get_with_retry(session, url, timeout=90).content).strip()
            text += f"\n\n--- Príloha ({url}) ---\n{doc}"
        except Exception as exc:  # the notice itself still stands
            text += f"\n\n(Prílohu sa nepodarilo prečítať: {url}: {exc})"
    if len(text) < 200:
        text = f"{candidate.title}\n\n{_LEADS.get(candidate.source_id, '')}\n\n{text}"
    return text[:MAX_CONTENT_CHARS]
