"""Swedish Government Offices — energy (regeringen.se).

Discovery: the RSS feed regeringen.se offers for the policy area "Energi"
(taxonomy 1226), allowed by robots.txt. It carries everything the Government
Offices tag as energy: press releases, referrals for comment (remisser),
government commissions to agencies (regeringsuppdrag), bills, memoranda and
committee reports, most of them from the Ministry of Climate and Enterprise,
which is responsible for energy. The site has no English edition of this
material.

Swedish electricity-market law is made here: the new Electricity Market Act,
the commissions to Svenska kraftnät and Energimarknadsinspektionen on
congestion income, tariffs and connection, the high-cost protection for
electricity bills, and the referrals of the agencies' proposals.

The energy tag also covers fuel, heating, efficiency grants and ministers'
travel, so a title-and-lead filter keeps the electricity items, and visits,
press briefings and agendas are dropped by title. The feed is not strictly in
date order (a referral moves up when replies are added), so items are sorted
by their publication date.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "Swedish Government Offices (Energy)"
DOCUMENT_TYPE = "GOVERNMENT"
# Referrals are announced days after the texts are dated.
MAX_AGE_DAYS = 7

BASE = "https://www.regeringen.se"
FEED = (f"{BASE}/Filter/RssFeed?filterType=Taxonomy&filterByType=FilterablePageBase"
        "&preFilteredCategories=1226&rootPageReference=0&format=rss")
MAX_ITEMS = 25

_ELECTRICITY = re.compile(
    r"\bel\b|\bel(en|nät|marknad|handel|pris|område|lag|försörjning|system|kund|använd|produ|"
    r"räkning|stöd|beredskap|certifikat|ektrifiering)|högkostnadsskydd|svenska kraftnät|"
    r"energimarknadsinspektionen|flaskhals|kärnkraft|vindkraft|vattenkraft|kraftvärme|"
    r"effektreserv|strategisk reserv|kapacitetsmekanism|stödtjänst|flexibilit|nätavgift|"
    r"nätkoncession|transmissionsnät|stamnät|ursprungsgaranti|energilag|planerbar", re.I)
_DROP = re.compile(
    r"\breser till|\bdeltar\b|\bdeltog\b|\bbesök|pressträff|pressbriefing|pressinbjudan|"
    r"kommenterad dagordning|\btar emot\b|överdirektör|generaldirektör|\bny ordförande", re.I)
# Content-type categories seen in the feed, used to say what kind of document an item is.
_KINDS = {"1334",   # Pressmeddelande
          "2099",   # Remiss
          "1342",   # Regeringsuppdrag
          "1325",   # Departementsserien och promemorior
          "2540"}   # Faktapromemoria


def discover(session):
    r = get_with_retry(session, FEED, timeout=60)
    if not r.content.strip():
        raise UpstreamUnavailable("regeringen.se energy feed returned an empty response")
    try:
        root = ET.fromstring(r.content.lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError as exc:
        raise CollectorError(f"regeringen.se energy feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("regeringen.se energy feed carried no items: format changed")

    rows = []
    for item in items:
        guid = (item.findtext("guid") or "").strip().lower()
        link = (item.findtext("link") or "").strip()
        title = " ".join((item.findtext("title") or "").split())
        lead = " ".join(BeautifulSoup(item.findtext("description") or "", "html.parser")
                        .get_text(" ", strip=True).split())
        if not guid or not link or not title or _DROP.search(title):
            continue
        if not _ELECTRICITY.search(f"{title} {lead}"):
            continue
        try:
            day = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            day = None
        kinds = [c.text for c in item.findall("category") if c.get("domain") in _KINDS]
        if kinds:
            title = f"{kinds[0]}: {title}" if not title.lower().startswith(kinds[0].lower()) else title
        rows.append((day or "", Candidate(f"se_gov-{guid}", title, day, link)))
    # No electricity item among a hundred energy items is a quiet spell, not a fault.
    if not rows:
        raise UpstreamUnavailable("No electricity item in the regeringen.se energy feed this run")
    rows.sort(key=lambda row: row[0], reverse=True)
    return FEED, [c for _, c in rows[:MAX_ITEMS]]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    # After the share links come the page's tags and a "Relaterat" list of other
    # recent items, which changes without the document changing.
    text = html_to_text(body).split("\nDela\n")[0]
    if len(text.strip()) < 200:
        raise CollectorError(f"regeringen.se page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
