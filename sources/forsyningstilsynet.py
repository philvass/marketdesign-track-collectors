"""Forsyningstilsynet — the Danish Utility Regulator.

Discovery: the site's sitemap.xml, which robots.txt advertises. The news
archive and the consultation list on forsyningstilsynet.dk are filled by a
script from a signed search request and offer no feed, but every news item
(/nyheder/<year>/<month>/<slug>) and every consultation
(/vejledning-og-indberetning/hoeringer/<year>/<month>/<slug>) is in the
sitemap with the year and month of publication in its address. The newest
months are taken, newest first.

The sitemap's lastmod is the time of the last edit, not of publication, so it
is used only for ordering. The publication date is printed at the top of each
page and is read there, which is why DATE_REFINED_ON_FETCH is set and the
number of items is kept small.

Forsyningstilsynet approves Energinet's methodologies and tariffs, the
network companies' tariff methods and revenue caps, enforces REMIT, and
consults on all of them. It also regulates gas, district heating, waste,
hydrogen and CO2, so addresses that name only those sectors are dropped.

Not read: afg.forsyningstilsynet.dk, the decisions database, which is an
application built in the browser; decisions of consequence are announced as
news with the decision linked.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Forsyningstilsynet"
DOCUMENT_TYPE = "REGULATOR"
DATE_REFINED_ON_FETCH = True

BASE = "https://forsyningstilsynet.dk"
SITEMAP = f"{BASE}/sitemap.xml"
MAX_ITEMS = 12

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "okt": 10, "nov": 11, "dec": 12}
_ITEM = re.compile(r"^https://forsyningstilsynet\.dk/(nyheder|vejledning-og-indberetning/hoeringer)/"
                   r"(20\d{2})/([a-z]{3})/([^/?#]+)$")
# Slugs are transliterated Danish (ae, oe, aa). A slug naming another sector
# passes only if it names electricity too.
_OTHER_SECTOR = re.compile(r"varme|affald|gas|brint|co2|vand|job|stilling")
_ELECTRIC = re.compile(r"(^|-)el(-|$)|elnet|elmarked|elhandel|elpris|elforsyning|elforbrug|"
                       r"elproducent|energinet|netvirksomhed|nettilslutning|tarif|remit")
_PAGE_DATE = re.compile(r"\b(\d{2})-(\d{2})-(20\d{2})\b")
_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def discover(session):
    r = get_with_retry(session, SITEMAP, timeout=60)
    if not r.content.strip():
        raise UpstreamUnavailable("Forsyningstilsynet sitemap returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"Forsyningstilsynet sitemap did not parse: {exc}")

    rows = []
    for node in root.iter(f"{_NS}url"):
        loc = (node.findtext(f"{_NS}loc") or "").strip()
        m = _ITEM.match(loc)
        month = _MONTHS.get(m.group(3)) if m else None
        if not month:
            continue
        slug = m.group(4)
        if _OTHER_SECTOR.search(slug) and not _ELECTRIC.search(slug):
            continue
        kind = "Høring" if "hoeringer" in m.group(1) else "Nyhed"
        rows.append((int(m.group(2)), month, node.findtext(f"{_NS}lastmod") or "", kind, slug, loc))
    if not rows:
        raise CollectorError("Forsyningstilsynet sitemap listed no news or consultations: structure changed")

    rows.sort(reverse=True)
    found = []
    for _year, _month, _mod, kind, slug, loc in rows[:MAX_ITEMS]:
        # The listing gives no title; the slug stands in until the page is read.
        title = f"{kind}: {slug.replace('-', ' ')}"
        found.append(Candidate(f"forsyningstilsynet-{slugify(slug, max_len=140)}", title, None, loc))
    return SITEMAP, found


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    head = soup.find("h1")
    if head and head.get_text(strip=True):
        kind = candidate.title.split(":")[0]
        candidate.title = f"{kind}: {' '.join(head.get_text(' ', strip=True).split())}"
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one('[role="main"]') or soup.select_one("main") or soup
    text = html_to_text(body).split("\nKontakt\nForsyningstilsynet\n")[0]
    m = _PAGE_DATE.search(text[:600])
    if m:
        candidate.publication_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    if len(text.strip()) < 200:
        raise CollectorError(f"Forsyningstilsynet page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
