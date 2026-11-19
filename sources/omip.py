"""OMIP — the Portuguese pole of the Iberian electricity market operator: the
derivatives exchange for MIBEL power (and PVB gas) futures, with its clearing
house OMIClear. It also runs Portuguese auctions (guarantees of origin, PRG,
storage). The spot market is OMIE's and is read by the `omie` adapter.

Discovery: two of the RSS feeds OMIP publishes, which robots.txt allows.

1. The news feed: releases on new contracts, changes to maturities and
   contract sizes, clearing recognitions, auction launches. Each item resolves
   to a PDF release, or occasionally a page.
2. The market-message feed restricted to market-structure changes, whose
   items carry the full text of the notice in the feed itself.

Not read: the "all market messages" feed, which is dominated by trading-session
events. Dropped by title: the monthly market report (statistics only).
Market-structure messages that consist of a contract code and nothing else are
left out, since there is no text to analyse.

Some news items have no attached release and their page answers "access
denied" to visitors who are not logged in (the site's own permission, not a
bot block). For those the record carries the lead from the feed and says so. The feed repeats an item once per
attachment; items are keyed by their own URL so each is collected once.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, extract_pdf_text, looks_like_pdf, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "OMIP"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://www.omip.pt"
NEWS_FEED = f"{BASE}/pt/publications-feed/all/feed.xml"
STRUCTURE_FEED = f"{BASE}/pt/market-messages-feed/trading-session-events/feed.xml"
MAX_ITEMS = 20
MIN_NOTICE_CHARS = 200

_PT_MONTHS = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
              "set": 9, "out": 10, "nov": 11, "dez": 12}
_DATE_NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d{2})")
_DATE_WORD = re.compile(r"(\d{1,2})\s+([A-Za-zç]{3})[a-zç]*\.?\s+(20\d{2})")
_DROP = re.compile(r"relat[óo]rio mensal|monthly report|relat[óo]rio e contas|assembleia geral", re.I)

_NOTICES: dict[str, str] = {}
_LEADS: dict[str, str] = {}


def _date(raw: str | None) -> str | None:
    raw = (raw or "").strip()
    m = _DATE_NUM.search(raw)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = _DATE_WORD.search(raw)
    month = _PT_MONTHS.get(m.group(2).lower()) if m else None
    return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}" if month else None


def _items(session, url):
    r = get_with_retry(session, url, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable(f"OMIP feed returned an empty response: {url}")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"OMIP feed did not parse ({url}): {exc}")
    out = []
    for item in root.findall(".//item"):
        head = item.find("title")
        # The feed wraps the title in an anchor element instead of escaping it.
        title = " ".join("".join(head.itertext()).split()) if head is not None else ""
        title = " ".join(BeautifulSoup(title, "html.parser").get_text(" ", strip=True).split())
        link = (item.findtext("link") or "").strip()
        body = BeautifulSoup(item.findtext("description") or "", "html.parser").get_text("\n", strip=True)
        if title and link:
            out.append((title, link, _date(item.findtext("pubDate")), body))
    return out


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    seen_any = False
    for kind, url in (("news", NEWS_FEED), ("notice", STRUCTURE_FEED)):
        try:
            items = _items(session, url)
        except CollectorError as exc:
            errors.append(str(exc))
            continue
        seen_any = seen_any or bool(items)
        for title, link, pub, body in items:
            if _DROP.search(title):
                continue
            slug = link.rstrip("/").split("/")[-1]
            if kind == "notice":
                if len(body) < MIN_NOTICE_CHARS:
                    continue
                sid = f"omip-notice-{slugify(slug)}"
                _NOTICES[sid] = body
                title = f"OMIP market notice: {title}"
            else:
                sid = f"omip-{slugify(slug)}"
                _LEADS[sid] = body
            found.setdefault(sid, Candidate(sid, title, pub, link))
            if len(found) >= MAX_ITEMS:
                break
    if not seen_any:
        raise CollectorError("OMIP feeds carried no items: format changed. " + " | ".join(errors)[:300])
    if not found:
        raise UpstreamUnavailable("No market-rule item in the OMIP feeds this run")
    return f"{NEWS_FEED} + {STRUCTURE_FEED}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    notice = _NOTICES.get(candidate.source_id)
    if notice:
        return f"{candidate.title}\n\n{notice}"[:MAX_CONTENT_CHARS]
    try:
        r = get_with_retry(session, candidate.url, timeout=90, attempts=1)
    except CollectorError:
        lead = _LEADS.get(candidate.source_id) or ""
        if len(lead) < 80:
            raise
        return (f"{candidate.title}\n\n{lead}\n\nNota: esta notícia do OMIP não tem comunicado anexo e a "
                "página só está acessível a utilizadores registados; este registo contém o resumo "
                "oficial do feed. (Note: this OMIP news item has no attached release and its page is "
                "open only to registered users; this record carries the official lead from the feed. "
                "See the source URL.)")[:MAX_CONTENT_CHARS]
    if looks_like_pdf(r):
        text = extract_pdf_text(r.content).strip()
    else:
        soup = BeautifulSoup(r.text, "html.parser")
        text = html_to_text(soup.select_one("article") or soup.select_one("main") or soup)
    if len(text) < 200:
        raise CollectorError(f"OMIP release yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
