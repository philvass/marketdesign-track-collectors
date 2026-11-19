"""OTE — the Czech electricity and gas market operator.

OTE runs the Czech day-ahead and intraday electricity markets, imbalance
settlement, the register of guarantees of origin and the payment of renewable
support, so its notices cover new market products, revisions of its business
terms, changes for aggregators and flexibility providers, and consultations.

Discovery: the RSS feed of "Zprávy OTE" (reserse-novinky/RSS), fifty items
with title, link and date. robots.txt allows every agent everywhere. The feed
links point at an internal /pubweb/ path; the public address is the same path
without that segment, and that is the one fetched and recorded.

Most notices are two sentences and a link to the release or document itself,
so the first PDF linked from the notice body is read into the record.

Dropped by title: the registration, locking and removal of individual
balance-responsible parties, the monthly market report, magazine articles,
invitations, clock changes, gas-only and emission-allowance items.
Czech: the English edition omits part of the notices.

Not read: the "Informace OTE" feed, which is operational messages of the
trading system, and the daily index feed.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "OTE (Czech market operator)"
DOCUMENT_TYPE = "MARKET_OPERATOR"

FEED = "https://www.ote-cr.cz/reserse-novinky/RSS"
MAX_ITEMS = 20

_NS = {"rss": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}
_ROUTINE = re.compile(
    r"subjekt\w* zúčtování|Měsíční zpráva|Publikace v časopise|časopisu|Pozvánka|konferenc|"
    r"Přechod na \w+ čas|povolenek|elektronických pečetí|působí již|výroční zpráv", re.I)
_GAS = re.compile(r"plyn", re.I)
_ELECTRICITY = re.compile(r"elektr", re.I)


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"OTE feed did not parse: {exc}")
    items = root.findall("rss:item", _NS)
    if not items:
        raise CollectorError("OTE feed carried no items: format changed")
    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("rss:title", "", _NS)).split())
        link = (item.findtext("rss:link", "", _NS)).strip().replace("/pubweb/", "/", 1)
        if not title or not link or _ROUTINE.search(title):
            continue
        if _GAS.search(title) and not _ELECTRICITY.search(title):
            continue
        day = re.match(r"\d{4}-\d{2}-\d{2}", item.findtext("dc:date", "", _NS).strip())
        sid = f"ote-{slugify(link.rstrip('/').split('/')[-1], 140)}"
        found.setdefault(sid, Candidate(sid, title, day.group(0) if day else None, link))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise CollectorError("OTE feed: every item was filtered out, check the title filter")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("#parent-fieldname-text") or soup.select_one("#content-core")
    if body is None:
        raise CollectorError(f"OTE notice has no body block: {candidate.url}")
    stamp = soup.select_one("#slot-above-content-title")
    text = "\n".join(filter(None, [candidate.title,
                                   stamp.get_text(" ", strip=True) if stamp else "",
                                   html_to_text(body)]))
    pdf = body.select_one('a[href$=".pdf"]')
    if pdf:
        url = urljoin(candidate.url, pdf["href"])
        try:
            doc = extract_pdf_text(get_with_retry(session, url, timeout=90).content).strip()
            text += f"\n\n--- Příloha ({url}) ---\n{doc}"
        except Exception as exc:  # the notice itself still stands
            text += f"\n\n(Přílohu se nepodařilo přečíst: {url}: {exc})"
    if len(text) < 200:
        text += ("\n\nPoznámka: oznámení OTE má jen tento krátký text. "
                 "(Note: this OTE notice consists only of the short text above.)")
    return text[:MAX_CONTENT_CHARS]
