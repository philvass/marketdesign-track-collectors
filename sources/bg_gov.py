"""Bulgarian Ministry of Energy (Министерство на енергетиката).

Discovery: the ministry's RSS feed on me.government.bg, in Bulgarian, the
complete edition. The site's robots.txt forbids nothing. The feed carries the
full text of each release, so no article page is fetched.

The ministry drafts the Energy Act and the Renewable Energy Act amendments,
runs the compensation schemes for business and energy-intensive industry,
and steers market liberalisation for households; those steps are announced
here. A title-and-lead filter keeps electricity items and drops the rest of
the feed: gas and oil supply, mining, plant maintenance, competitions for
posts, diplomatic meetings without an electricity subject.

The feed dates each item at midnight Sofia time expressed in UTC, so the
date is converted back to local time before it is recorded.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "Ministry of Energy (Bulgaria)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

FEED = "https://www.me.government.bg/bg/rss.html"
MAX_ITEMS = 25
_NS = {"content": "http://purl.org/rss/1.0/modules/content/"}
_SOFIA = ZoneInfo("Europe/Sofia")

_ELECTRICITY = re.compile(
    r"електроенерг|електрическа енергия|електро-|\bток\w*\b|закона? за енергетиката|"
    r"възобновяеми източници|\bВЕИ\b|енергийн\w+ борса|либерализаци|регулиран\w+ пазар|"
    r"свободн\w+ пазар|компенсаци|електропренос|електроразпредел|съхранение на енерг|батери|"
    r"капацитет\w* механиз|балансиращ|ядрен\w+ мощност|\bАЕЦ\b|\bНЕК\b|\bЕСО\b|\bБНЕБ\b", re.I)
_DROP = re.compile(r"конкурс|щатна бройка|годишният ремонт|планов\w+ ремонт|съвета на директорите|"
                   r"обществена поръчка", re.I)

_BODY: dict[str, str] = {}


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("Bulgarian ministry feed returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"Bulgarian ministry feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("Bulgarian ministry feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        lead = " ".join((item.findtext("description") or "").split())
        post = re.search(r"-(\d+)\.html", link)
        if not title or not post:
            continue
        if _DROP.search(title) or not _ELECTRICITY.search(f"{title} {lead}"):
            continue
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "") \
                .astimezone(_SOFIA).date().isoformat()
        except (TypeError, ValueError):
            when = None
        sid = f"bg_gov-{post.group(1)}"
        body = html_to_text(BeautifulSoup(
            item.findtext("content:encoded", default="", namespaces=_NS) or "", "html.parser"))
        _BODY[sid] = "\n\n".join(p for p in (lead, body) if p)
        found.setdefault(sid, Candidate(sid, title, when, link))
        if len(found) >= MAX_ITEMS:
            break
    # A dozen releases with nothing on electricity among them is a quiet week.
    if not found:
        raise UpstreamUnavailable("No electricity item in the Bulgarian ministry feed this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    body = _BODY.get(candidate.source_id, "").strip()
    if len(body) < 150:
        # The feed gave only a lead: read the release itself.
        r = get_with_retry(session, candidate.url, timeout=45)
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one("main") or soup.select_one("article") or soup.body or soup
        body = html_to_text(main)
    text = f"{candidate.title}\n\n{body}"
    if len(text) < 200:
        raise CollectorError(f"Bulgarian ministry release yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
