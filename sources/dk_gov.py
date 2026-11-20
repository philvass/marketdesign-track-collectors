"""Danish Ministry of Climate, Energy and Utilities (KEFM) and the Danish
Energy Agency (Energistyrelsen).

Discovery, two routes, both allowed by the sites' robots.txt:

1. kefm.dk news. The ministry's news archive is filled by a script from a
   signed search request and has no feed, so the sitemap.xml that robots.txt
   advertises is read instead. Every release is listed there as
   /aktuelt/nyheder/<year>/<month>/<slug>. The sitemap's lastmod is the last
   edit, not the publication, so it only orders the items; title and date are
   read from the page, which is why DATE_REFINED_ON_FETCH is set.
2. ens.dk press releases (/om-os/pressemeddelelser), a server-rendered list
   with title, lead and date; the first page of ten is read.

Danish electricity policy is announced here: political agreements on the
grid and its connection queue, tariffs and levies, tenders for offshore wind
and their support terms, security of supply. Both bodies also deal with
climate, heating, gas, CO2 storage and efficiency grants, so only items whose
title (for the ministry: the address, which is the title) or lead names
electricity pass, and press invitations, travel and appointments are dropped.

Not read: hoeringsportalen.dk, the cross-government consultation portal, and
the agency's subject pages.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Danish Ministry of Climate, Energy and Utilities / Danish Energy Agency"
DOCUMENT_TYPE = "GOVERNMENT"
# Agreements and tenders are announced days after the texts are dated.
MAX_AGE_DAYS = 7
DATE_REFINED_ON_FETCH = True

KEFM = "https://www.kefm.dk"
KEFM_SITEMAP = f"{KEFM}/sitemap.xml"
ENS = "https://ens.dk"
ENS_LIST = f"{ENS}/om-os/pressemeddelelser"
# One page only: every candidate is fetched on every run (see DATE_REFINED_ON_FETCH),
# and the agency publishes a few releases a month.
ENS_PAGES = (ENS_LIST,)
KEFM_ITEMS = 8
ENS_ITEMS = 10

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "okt": 10, "nov": 11, "dec": 12}
_KEFM_ITEM = re.compile(r"^https://www\.kefm\.dk/aktuelt/nyheder/(20\d{2})/([a-z]{3})/([^/?#]+)$")
# Written for both Danish text and its transliteration in addresses (ø -> oe, å -> aa).
_ELECTRICITY = re.compile(
    r"\bel\b|\bel(net|marked|pris|afgift|forsyning|forbrug|regning|produktion|handel|system|"
    r"ektrificering|ektrificere|kunde|tarif|kabel)|str(ø|oe)m|energinet|nettilslutning|"
    r"netvirksomhed|\btarif|havvind|vindm(ø|oe)lle|landvind|solcelle|energi(ø|oe)|"
    r"forsyningssikkerhed|kapacitetsmekanism|fleksibilitet|vedvarende energi|\bve-|"
    r"oprindelsesgaranti|udlandsforbindelse|atomkraft|akutplan", re.I)
_DROP = re.compile(r"presseinvitation|pressem(ø|oe)de|rejser til|bes(ø|oe)ger|ans(æ|ae)tter|"
                   r"ny direkt(ø|oe)r|forperson|formand|doorstep", re.I)
_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_KEFM_DATE = re.compile(r"Publiceret\s+(\d{2})-(\d{2})-(20\d{2})")
_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _kefm(session) -> list[Candidate]:
    r = get_with_retry(session, KEFM_SITEMAP, timeout=60)
    root = ET.fromstring(r.content)
    rows = []
    listed = 0
    for node in root.iter(f"{_NS}url"):
        m = _KEFM_ITEM.match((node.findtext(f"{_NS}loc") or "").strip())
        month = _MONTHS.get(m.group(2)) if m else None
        if not month:
            continue
        listed += 1
        words = m.group(3).replace("-", " ")
        if _DROP.search(words) or not _ELECTRICITY.search(words):
            continue
        rows.append((int(m.group(1)), month, node.findtext(f"{_NS}lastmod") or "", m.group(3), m.group(0)))
    if not listed:
        raise CollectorError("kefm.dk sitemap listed no news: structure changed")
    rows.sort(reverse=True)
    # The listing gives no title; the slug stands in until the page is read.
    return [Candidate(f"dk_gov-kefm-{slugify(slug, max_len=140)}", f"KEFM: {slug.replace('-', ' ')}", None, loc)
            for _y, _m, _mod, slug, loc in rows[:KEFM_ITEMS]]


def _ens(session) -> list[Candidate]:
    found: dict[str, Candidate] = {}
    listed = 0
    for n, page in enumerate(ENS_PAGES):
        try:
            r = get_with_retry(session, page, timeout=45)
        except CollectorError:
            if n == 0:
                raise
            break
        for item in BeautifulSoup(r.text, "html.parser").select("div.listing"):
            a = item.select_one("h2 a[href]")
            if not a or not a["href"].startswith("/presse/"):
                continue
            listed += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            lead = item.select_one(".listing__text")
            lead = " ".join(lead.get_text(" ", strip=True).split()) if lead else ""
            stamp = item.select_one("time[datetime]")
            m = _ISO.search(stamp["datetime"]) if stamp else None
            if _DROP.search(title) or not _ELECTRICITY.search(f"{title} {lead}"):
                continue
            sid = f"dk_gov-ens-{slugify(a['href'].rstrip('/').split('/')[-1], max_len=140)}"
            found.setdefault(sid, Candidate(sid, f"Energistyrelsen: {title}",
                                            "-".join(m.groups()) if m else None, urljoin(ENS, a["href"])))
            if len(found) >= ENS_ITEMS:
                break
    if not listed:
        raise CollectorError("ens.dk press list yielded no items: markup changed")
    return list(found.values())


def discover(session):
    found: list[Candidate] = []
    errors = []
    for route in (_kefm, _ens):
        try:
            found.extend(route(session))
        except (CollectorError, ET.ParseError) as exc:
            errors.append(str(exc))
    if errors and not found:
        raise CollectorError("Danish energy ministry and agency routes both failed. " + " | ".join(errors)[:300])
    if not found:
        raise QuietRun("No electricity item in the newest KEFM and Energistyrelsen releases this run")
    return f"{KEFM_SITEMAP} + {ENS_LIST}", found


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    is_kefm = candidate.url.startswith(KEFM)
    head = soup.find("h1")
    if is_kefm and head and head.get_text(strip=True):
        candidate.title = f"KEFM: {' '.join(head.get_text(' ', strip=True).split())}"
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one('[role="main"]') or soup.select_one("main") or soup
    text = html_to_text(body)
    if is_kefm:
        # Below the release come the newsletter sign-up and lists of related
        # news and themes, which change without the release changing.
        text = re.split(r"\n(?:Tilmeld dig ministeriets nyhedsbrev|Relaterede nyheder)\n", text)[0]
        m = _KEFM_DATE.search(text[:800])
        if m:
            candidate.publication_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    if len(text.strip()) < 200:
        raise CollectorError(f"Page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
