"""ERÚ (Energetický regulační úřad) — the Czech energy regulator.

Discovery: two routes on eru.gov.cz, whose robots.txt closes only the Drupal
system paths:

1. The RSS feed of "Aktuální sdělení", the office's current notices: ten
   items with title, link and date.
2. The page "Veřejné konzultační procesy", which lists the consultations now
   open: draft price decisions and ordinances, the regulation methodology,
   grid codes of the system operators and the market operator's business
   terms. It gives titles only; the date stands at the head of each
   consultation page and is completed on fetch.

A consultation page is a short notice with the consulted text attached, so the
first attached PDF is read into the record as well.

ERÚ also regulates gas and district heat. Items whose title is about those
alone are dropped, and so are the webinars, statistics and reporting templates
that fill much of the feed. Czech only: the English site is a static summary.

Not read: "Pravomocná rozhodnutí", the register of individual licence and
penalty rulings, which is case law, and the Energetický regulační věstník,
whose price decisions are announced through the two routes above first.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ERÚ (Energetický regulační úřad)"
DOCUMENT_TYPE = "REGULATOR"
# Consultation dates are only on the consultation pages.
DATE_REFINED_ON_FETCH = True

BASE = "https://eru.gov.cz"
FEED = f"{BASE}/aktualni-sdeleni/rss"
CONSULTATIONS = f"{BASE}/verejne-konzultacni-procesy"
MAX_CONSULTATIONS = 12

_OTHER_FUELS = re.compile(r"plyn|NET4GAS|tepeln|teplár|zásobník", re.I)
_ELECTRICITY_TOO = re.compile(r"elektr|elektřin", re.I)
_ROUTINE = re.compile(
    r"webinář|seminář|konferenc|Měsíční spotřeba|Čtvrtletní zpráva|vzory šablon|vykazování dat|"
    r"výběrové řízení|volné místo|dotazník spokojenosti", re.I)
_DATE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(20\d{2})\b")


def _wanted(title: str) -> bool:
    if _ROUTINE.search(title):
        return False
    return not _OTHER_FUELS.search(title) or bool(_ELECTRICITY_TOO.search(title))


def _sid(url: str) -> str:
    return f"eru-{slugify(url.rstrip('/').split('/')[-1], 120)}"


def _feed(session) -> list[Candidate]:
    r = get_with_retry(session, FEED, timeout=45)
    try:
        items = ET.fromstring(r.content).findall(".//item")
    except ET.ParseError as exc:
        raise CollectorError(f"ERÚ feed did not parse: {exc}")
    if not items:
        raise CollectorError("ERÚ feed carried no items: format changed")
    out = []
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        if not title or not link or not _wanted(title):
            continue
        try:
            day = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            day = None
        out.append(Candidate(_sid(link), title, day, link))
    return out


def _consultations(session) -> list[Candidate]:
    r = get_with_retry(session, CONSULTATIONS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.find("main") or soup
    out = []
    for a in body.select('a[href^="/navrh"]'):
        title = " ".join(a.get_text(" ", strip=True).split())
        if len(title) < 15 or not _wanted(title):
            continue
        url = urljoin(BASE, a["href"])
        out.append(Candidate(_sid(url), f"Veřejná konzultace ERÚ: {title}", None, url))
        if len(out) >= MAX_CONSULTATIONS:
            break
    if not body.select('a[href^="/navrh"]'):
        raise CollectorError("ERÚ consultation page listed no drafts: markup changed")
    return out


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    # The feed goes first: where a consultation is in both, its entry carries the date.
    for name, route in (("feed", _feed), ("consultations", _consultations)):
        try:
            for c in route(session):
                found.setdefault(c.source_id, c)
        except CollectorError as exc:
            errors.append(f"{name}: {exc}")
    if not found:
        raise CollectorError("ERÚ yielded nothing. " + " | ".join(errors)[:300])
    return f"{FEED} + {CONSULTATIONS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.find("main") or soup
    attachment = body.select_one('a[href*="/sites/default/files/"][href$=".pdf"]')
    text = html_to_text(body)
    if not candidate.publication_date:
        m = _DATE.search(text[:600])
        if m:
            candidate.publication_date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if attachment and "konzultační proces" in text:
        url = urljoin(BASE, attachment["href"])
        try:
            pdf = extract_pdf_text(get_with_retry(session, url, timeout=90).content).strip()
            text += f"\n\n--- Konzultovaný dokument ({url}) ---\n{pdf}"
        except Exception as exc:  # the notice itself still stands
            text += f"\n\n(Přílohu se nepodařilo přečíst: {exc})"
    if len(text) < 300:
        raise CollectorError(f"ERÚ page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
