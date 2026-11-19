"""Agencija za energijo — the Slovenian energy regulator.

Discovery: three server-rendered lists on agen-rs.si, whose robots.txt forbids
only the search pages:

1. Novice, the agency's news: press releases, published analyses (the national
   flexibility needs assessment, network-charge calculations) and invitations
   to comment.
2. Javna obravnava aktov, the public hearings on the agency's general acts:
   the methodologies for network charges, the regulatory framework, the prices
   of balancing and non-frequency ancillary services.
3. Javna posvetovanja, its broader consultations (the flexibility market,
   smart metering, access to metering data).

Each entry carries its publication date, and the two consultation lists also
carry the agency's own subject labels. The Slovenian pages are read because
the English edition holds only a fraction of them.

The agency also regulates gas and district heat. A consultation is kept only
if it is labelled "Električna energija" (or carries no sector label at all);
a news item is dropped when its title and lead speak of gas or heat and not of
electricity.

Not read: the site's RSS feed, whose item links lead back to the news list
rather than to the articles; and the Odločbe pages, which are individual
decisions on named parties.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Agencija za energijo (Slovenia)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.agen-rs.si"
NEWS = f"{BASE}/novice"
CONSULTATIONS = (("Javna obravnava akta", f"{BASE}/javna-obravnava-aktov"),
                 ("Javno posvetovanje", f"{BASE}/posvetovanja"))
PER_LIST = 8

_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_OTHER_SECTOR = re.compile(r"\bplin|toplot|daljinsk\w+ ogrevan", re.I)
_ELECTRICITY = re.compile(r"elektri|elektro|omrežnin|prožnost|\bOVE\b|obnovljiv", re.I)
_SECTOR_LABELS = {"električna energija", "zemeljski plin", "toplota"}


def _date(raw: str) -> str | None:
    m = _DATE.search(raw or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def _slug(href: str) -> str:
    return slugify(href.split("?")[0].rstrip("/").split("/")[-1])


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    blocks = 0

    try:
        soup = BeautifulSoup(get_with_retry(session, NEWS, timeout=45).text, "html.parser")
        for item in soup.select(".news_item"):
            blocks += 1
            a = item.select_one("h4 a[href]")
            if not a:
                continue
            title = " ".join(a.get_text(" ", strip=True).split())
            lead = " ".join(p.get_text(" ", strip=True) for p in item.find_all("p"))
            text = f"{title} {lead}"
            if not title or (_OTHER_SECTOR.search(text) and not _ELECTRICITY.search(text)):
                continue
            when = item.select_one(".date")
            sid = f"agen_rs-novice-{_slug(a['href'])}"
            found.setdefault(sid, Candidate(sid, title, _date(when.get_text() if when else ""),
                                            urljoin(BASE, a["href"])))
            if len(found) >= PER_LIST:
                break
    except CollectorError as exc:
        errors.append(f"novice: {exc}")

    for kind, url in CONSULTATIONS:
        try:
            soup = BeautifulSoup(get_with_retry(session, url, timeout=45).text, "html.parser")
        except CollectorError as exc:
            errors.append(f"{kind}: {exc}")
            continue
        n = 0
        for item in soup.select(".consultation"):
            blocks += 1
            a = item.select_one("h4 a[href]")
            if not a:
                continue
            labels = {s.get_text(" ", strip=True).lower() for s in item.select("span.label")}
            sectors = labels & _SECTOR_LABELS
            if sectors and "električna energija" not in sectors:
                continue
            title = " ".join(a.get_text(" ", strip=True).split())
            when = item.select_one(".date")
            href = a["href"].split("?")[0]
            sid = f"agen_rs-{slugify(kind.split()[1])}-{_slug(href)}"
            if not title or sid in found:
                continue
            found[sid] = Candidate(sid, f"{kind}: {title}",
                                   _date(when.get_text() if when else ""), urljoin(BASE, href))
            n += 1
            if n >= PER_LIST:
                break

    if not blocks:
        raise CollectorError("Agencija za energijo lists yielded no entries: markup changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise CollectorError("Agencija za energijo: entries found but none parsed. "
                             + " | ".join(errors)[:300])
    return " + ".join([NEWS] + [u for _, u in CONSULTATIONS]), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = (soup.select_one(".asset-full-content") or soup.select_one(".journal-content-article")
            or soup.select_one("#main-content"))
    if body is None:
        raise CollectorError(f"Agencija za energijo page has no article body: {candidate.url}")
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"Agencija za energijo page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
