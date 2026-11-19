"""MEKH (Magyar Energetikai és Közmű-szabályozási Hivatal) — the Hungarian
energy and public utility regulator.

Discovery: the office's own RSS feed, twenty news items with title, link,
lead and date. mekh.hu is a single-page application whose pages are filled by
a public backend on www-wb.mekh.hu; the feed lives there (the site's RSS
button points at it), and so does the JSON that carries each article's text,
which is what fetch_content reads. Neither host serves a robots.txt, so
nothing is closed to agents, and no page rendering is needed.

This is where MEKH announces its decisions on network tariffs and connection
charges, capacity tenders (wind, storage), approvals of the TSO's reports and
methodologies, derogations and draft decrees under consultation.

MEKH also regulates gas, district heating, water and waste. Items about those
alone are dropped by a title-and-lead filter, together with events, visits
and appointments. Hungarian: the English feed carries a fraction of the news.

Not read: the register of individual decisions (határozatok), which is
searchable only through a form and is case law for the most part.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "MEKH (Hungarian Energy and Public Utility Regulatory Authority)"
DOCUMENT_TYPE = "REGULATOR"

API = "https://www-wb.mekh.hu/api/v1"
FEED = f"{API}/rss"
PAGE = f"{API}/pages/content"

_OTHER = re.compile(r"földgáz|\bgáz|távhő|víziközmű|ivóvíz|hulladék|hidrogén", re.I)
_ELECTRICITY = re.compile(
    r"villamos|áram|rendszerhasználati|csatlakozási díj|erőmű|szélerőmű|naperőmű|kapacitás|"
    r"rugalmass|kiegyenlítő|energiatárol|tároló|MAVIR|hálózat|megújuló|METÁR|eredetigazol|"
    r"derogáci|piacmonitoring|piaci ár|aggregátor|energiaközösség", re.I)
_ROUTINE = re.compile(
    r"Erőművek Éjszak|verseny\b|csapatverseny|delegáci|nevezték ki|konferenci|Örményország|"
    r"együttműködési megállapodás|díjat nyert|pályakezd", re.I)

_LEADS: dict[str, str] = {}


def _plain(markup: str) -> str:
    return " ".join(BeautifulSoup(markup or "", "html.parser").get_text(" ", strip=True).split())


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("MEKH feed returned an empty response")
    try:
        items = ET.fromstring(r.content).findall(".//item")
    except ET.ParseError as exc:
        raise CollectorError(f"MEKH feed did not parse: {exc}")
    if not items:
        raise CollectorError("MEKH feed carried no items: format changed")
    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        lead = _plain(item.findtext("description") or "")
        if not title or "mekh.hu/" not in link:
            continue
        both = f"{title} {lead}"
        if _ROUTINE.search(title) or not _ELECTRICITY.search(both):
            continue
        if _OTHER.search(title) and not re.search(r"villamos|áram", both, re.I):
            continue
        try:
            day = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            day = None
        sid = f"mekh-{slugify(link.split('mekh.hu/', 1)[1], 140)}"
        _LEADS[sid] = lead
        found.setdefault(sid, Candidate(sid, title, day, link))
    if not found:
        raise UpstreamUnavailable("No electricity item in the MEKH feed this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    # The page's own slug, exactly as the feed writes it (some end in a hyphen).
    slug = candidate.url.split("mekh.hu/", 1)[1]
    r = get_with_retry(session, PAGE, params={"slug": slug, "lang": "hu"},
                       headers={"Accept": "application/json"}, timeout=45)
    try:
        page = r.json()
    except ValueError as exc:
        raise CollectorError(f"MEKH page endpoint did not return JSON for {slug}: {exc}")
    tags = ", ".join(t.get("text", "") for t in page.get("tags") or [] if t.get("text"))
    body = html_to_text(BeautifulSoup(page.get("html") or "", "html.parser"))
    parts = [(page.get("name") or candidate.title).strip(),
             _plain(page.get("lead") or "") or _LEADS.get(candidate.source_id, ""),
             body,
             f"Rovat: {tags}" if tags else ""]
    text = "\n\n".join(p for p in parts if p)
    if len(body) < 100:
        text += ("\n\nMegjegyzés: a hír teljes szövege a forrásoldalon olvasható; itt a cím és a bevezető áll. "
                 "(Note: only the title and lead were available; full text at the source URL.)")
    return text[:MAX_CONTENT_CHARS]
