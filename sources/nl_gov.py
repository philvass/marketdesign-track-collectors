"""Dutch government — the ministry responsible for energy (Economische Zaken
en Klimaat, with the ministers for Klimaat en Groene Groei), on
rijksoverheid.nl.

Discovery: two plain routes, both allowed by the site's robots.txt, which
restricts nothing.

1. The news sitemap, /news/sitemap.xml, which the site publishes for news
   crawlers: every government news release of the last two days with its
   title and publication time. It covers all ministries, so the Dutch
   electricity filter below does the selecting.
2. The ministry's own page, which shows its three newest releases in the
   server-rendered HTML. It catches an item that has already aged out of the
   sitemap when a run was missed.

Why not the news archive: since the site was rebuilt, /actueel/nieuws is drawn
by scripts from a search service, the former feeds.rijksoverheid.nl host and
the opendata.rijksoverheid.nl document API are gone, and the per-page RSS link
is produced by a dialog rather than published at an address. The two routes
above need none of that, but they only reach back two days, so this source
depends on the daily run.

Not read: internetconsultatie.nl, where draft energy legislation is consulted
on. Its robots.txt disallows everything for undeclared agents.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Dutch Ministry of Economic Affairs and Climate (EZK/KGG)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://www.rijksoverheid.nl"
NEWS_SITEMAP = f"{BASE}/news/sitemap.xml"
MINISTRY = f"{BASE}/ministeries/ministerie-van-economische-zaken-en-klimaat"
MAX_ITEMS = 20

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
       "news": "http://www.google.com/schemas/sitemap-news/0.9"}
_ARTICLE = re.compile(r"/actueel/nieuws/(\d{4})/(\d{2})/(\d{2})/([^/?#\"]+)")
_ELECTRICITY = re.compile(
    r"elektriciteit|stroomnet|stroomprij|stroommarkt|\bstroom\b|energiewet|energiemarkt|"
    r"energiesysteem|energieopslag|batterij|netcongestie|netcapaciteit|netbeheer|nettarie|"
    r"hoogspanning|transportschaarste|terugleverkosten|salderingsregeling|saldering|"
    r"wind op zee|windpark|kernenergie|kerncentrale|SDE\+\+|duurzame energie|"
    r"leveringszekerheid|capaciteitsmechanisme|flexibiliteit|energieleverancier|"
    r"garanties van oorsprong|TenneT|energierekening|energiebelasting", re.I)


def _candidate(match: re.Match, title: str, when: str | None = None) -> Candidate:
    y, m, d, slug = match.groups()
    return Candidate(f"nl_gov-{y}{m}{d}-{slugify(slug)}", " ".join(title.split()),
                     (when or f"{y}-{m}-{d}")[:10], f"{BASE}{match.group(0)}")


def discover(session):
    found: dict[str, Candidate] = {}
    listed = 0
    errors = []

    try:
        r = get_with_retry(session, NEWS_SITEMAP, timeout=45)
        root = ET.fromstring(r.content)
        for url in root.findall("sm:url", _NS):
            m = _ARTICLE.search(url.findtext("sm:loc", "", _NS))
            title = url.findtext("news:news/news:title", "", _NS)
            if not m or not title.strip():
                continue
            listed += 1
            if _ELECTRICITY.search(title):
                c = _candidate(m, title, url.findtext("news:news/news:publication_date", "", _NS) or None)
                found.setdefault(c.source_id, c)
    except (CollectorError, ET.ParseError) as exc:
        errors.append(f"news sitemap: {exc}")

    try:
        r = get_with_retry(session, MINISTRY, timeout=45)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            m = _ARTICLE.search(a["href"])
            if not m:
                continue
            listed += 1
            head = a.find(["h2", "h3", "h4"])
            title = (head or a).get_text(" ", strip=True)
            lead = a.get_text(" ", strip=True)
            if title and _ELECTRICITY.search(lead):
                c = _candidate(m, title)
                found.setdefault(c.source_id, c)
    except CollectorError as exc:
        errors.append(f"ministry page: {exc}")

    if not listed:
        raise CollectorError("rijksoverheid.nl listed no news on either route: format changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise QuietRun(f"No electricity item among {listed} current Dutch government releases")
    return f"{NEWS_SITEMAP} + {MINISTRY}", list(found.values())[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.select_one("main") or soup).strip()
    if len(text) < 200:
        raise CollectorError(f"rijksoverheid.nl article yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
