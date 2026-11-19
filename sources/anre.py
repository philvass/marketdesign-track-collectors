"""ANRE — Autoritatea Națională de Reglementare în Domeniul Energiei, the
Romanian energy regulator.

Discovery: two category feeds of the regulator's WordPress site, whose
robots.txt forbids only the admin folder:

1. Documente de discuție / Energie electrică: the draft orders and decisions
   ANRE puts to public consultation (market rules, tariff methodologies,
   licensing, prosumer settlement, supply regulations).
2. Comunicări publice: press releases and announcements, where adopted orders
   are explained and procedures such as the designation of suppliers of last
   resort are opened.

The feeds carry the full text of each post, so no article page is fetched;
the documents attached to a post are listed by name and address at the end
of the record but not downloaded. Romanian is the only edition.

ANRE also regulates gas and heat. Posts filed only under gas or heat are
dropped, as are examination notices for electricians and installers, weekly
settlement figures and the withdrawal of individual licences.

Not read: the order and decision search on spv.anre.ro, an application rather
than a list.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "ANRE (Romania)"
DOCUMENT_TYPE = "REGULATOR"

FEEDS = ("https://anre.ro/category/documente-de-discutie/energie-electrica/feed/",
         "https://anre.ro/category/comunicari-publice/feed/")
MAX_ITEMS = 20
_NS = {"content": "http://purl.org/rss/1.0/modules/content/"}

_OTHER_CATEGORY = {"gaze naturale", "energie termica", "instalatori", "electricieni"}
_DROP = re.compile(
    r"examen|sesiune\w* (?:toamna|primavara|primăvara)|instalator|electrician|sume decontate|"
    r"retrage licen|gaze naturale|energi\w+ termic", re.I)

_BODY: dict[str, str] = {}


def _text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    docs = []
    for a in soup.find_all("a", href=True):
        if re.search(r"\.(pdf|docx?|xlsx?|zip)(\?|$)", a["href"], re.I):
            docs.append(f"- {' '.join(a.get_text(' ', strip=True).split())}: {a['href']}")
    text = html_to_text(soup)
    if docs:
        text += "\n\nDocumente atașate (attached documents, not downloaded):\n" + "\n".join(docs)
    return text


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    seen_items = 0
    for feed in FEEDS:
        try:
            r = get_with_retry(session, feed, timeout=45)
            root = ET.fromstring(r.content)
        except (CollectorError, ET.ParseError) as exc:
            errors.append(f"{feed}: {exc}")
            continue
        for item in root.findall(".//item"):
            seen_items += 1
            title = " ".join((item.findtext("title") or "").split())
            link = (item.findtext("link") or "").strip()
            post = re.search(r"[?&]p=(\d+)", item.findtext("guid") or "")
            if not title or not link or not post:
                continue
            cats = {(c.text or "").strip().lower() for c in item.findall("category")}
            if cats & _OTHER_CATEGORY and "energie electrica" not in cats:
                continue
            if _DROP.search(title) and "energie electrica" not in cats:
                continue
            try:
                when = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
            except (TypeError, ValueError):
                when = None
            sid = f"anre-{post.group(1)}"
            if sid in found:
                continue
            _BODY[sid] = _text(item.findtext("content:encoded", default="", namespaces=_NS)
                               or item.findtext("description") or "")
            found[sid] = Candidate(sid, title, when, link)
    if not seen_items:
        if errors and all("GET failed" in e for e in errors):
            raise UpstreamUnavailable("ANRE feeds unreachable: " + " | ".join(errors)[:300])
        raise CollectorError("ANRE feeds carried no items: format changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise UpstreamUnavailable("No electricity item in the ANRE feeds this run")
    items = sorted(found.values(), key=lambda c: c.publication_date or "", reverse=True)
    return " + ".join(FEEDS), items[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    body = _BODY.get(candidate.source_id, "").strip()
    text = f"{candidate.title}\n\n{body}"
    if len(body) < 100:
        # A post that is only a title and an attachment: read the page itself.
        r = get_with_retry(session, candidate.url, timeout=45)
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one("article") or soup.select_one("main") or soup
        text = f"{candidate.title}\n\n{_text(str(main))}"
    if len(text) < 200:
        raise CollectorError(f"ANRE post yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
