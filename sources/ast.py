"""AST — Augstsprieguma tīkls, the Latvian transmission system operator.

Discovery: the site's RSS feed of "Aktualitātes", which carries news, notices
and the public consultations together, each with its category and date.
Latvian is read because it is the master edition; consultation documents are
often in English anyway and are quoted in the article. robots.txt allows the
feed and the article pages (it closes admin and search).

AST runs the Latvian balancing market and, with Elering and Litgrid, the
Baltic balancing, reserve-capacity and capacity-calculation arrangements that
followed synchronisation with continental Europe; its consultations on those
methodologies are the reason it is read. Corporate items (bond issues,
results, appointments, sponsorship, procurement) are dropped by title.

Not read: the operational transparency data and the outage notices.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Augstsprieguma tīkls (AST)"
DOCUMENT_TYPE = "TSO"

FEED = "https://www.ast.lv/lv/rss.xml"
MAX_ITEMS = 25

_CORPORATE = re.compile(
    r"obligācij|valdes loce|valdes priekšsēd|padomes loce|padomes priekšsēd|finanšu rezultāt|peļņ|"
    r"dividen|apgrozījum|kredītreiting|ziedo|sponsor|stipendij|iepirkum|vakanc|prakse|"
    r"apbalvo|balvu|gada pārskat|akcionār|darba devēj|dispečeru vadības un datu centrs", re.I)
_OPERATIONAL = re.compile(r"atslēgum|remontdarbu grafik|izsoles rezultāt", re.I)
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")


def _date(raw: str | None) -> str | None:
    m = _DATE.search(raw or "")                      # the feed writes dd.mm.yyyy, not RFC 822
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("AST feed returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"AST feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("AST feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        if not title or "/events/" not in link:
            continue
        category = (item.findtext("category") or "").strip()
        if category == "Finanšu informācija" or _CORPORATE.search(title) or _OPERATIONAL.search(title):
            continue
        sid = f"ast-{slugify(link.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, _date(item.findtext("pubDate")), link))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise CollectorError("AST feed had items but none with an article link: format changed")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("article") or soup.select_one("main") or soup
    text = html_to_text(body)
    if len(text.strip()) < 200:
        raise CollectorError(f"AST page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
