"""Energy Community Secretariat — the Vienna-based institution that extends
the EU's energy acquis to the Western Balkans, Ukraine, Moldova and Georgia.

Discovery: the JSON delivery endpoint that the Secretariat's own news page
calls to fill its list (/.rest/delivery/newsEntries), newest first, with the
title, date, lead and subject categories of each item. The news page itself
renders only the four newest items without scripts, which is why the
endpoint is read instead. The site's robots.txt carries a notice about
content signals but no rule and no signal, so nothing is forbidden.

The news is where the Secretariat reports the decisions that matter here:
Ministerial Council and Permanent High Level Group decisions on the
electricity integration package, market coupling with the EU, CBAM and
carbon pricing for electricity trade, infringement cases, ECRB positions,
and its implementation reports. An item is kept when the Secretariat itself
files it under Electricity or Renewable energy, or when its title or lead
speaks of electricity markets; fund-raising for Ukraine's energy support
fund, vacancies, awards and gas- or oil-only items are dropped.

The article page is fetched for the text. Not read: the legal-acts database
and the events calendar; decisions reach the monitor through the news item
that announces them.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Energy Community Secretariat"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.energy-community.org"
API = f"{BASE}/.rest/delivery/newsEntries?" + urlencode({
    "orderBy": "date desc", "offset": 0, "limit": 25,
    "mgnl:template[eq]": "enc-module-templating:pages/batNews"})
LISTING = f"{BASE}/news/Energy-Community-News.html"
_PATH = re.compile(r"^/enc(/news/Energy-Community-News/(20\d{2})/(\d{1,2})/([0-9a-z]+))$", re.I)

_KEEP_CATEGORIES = {"electricity", "renewable energy", "renewable-energy"}
_ELECTRICITY = re.compile(
    r"electricit|power market|power sector|market coupling|coupling|balancing|capacity mechanism|"
    r"\bCBAM\b|carbon pric|renewable|guarantees? of origin|Ministerial Council|"
    r"Permanent High Level Group|\bPHLG\b|\bECRB\b|infringement|dispute settlement|"
    r"electricity integration package|bidding zone|day-ahead|intraday", re.I)
_DROP = re.compile(
    r"Energy Support Fund|vacanc|award|internship|summer school|traineeship|call for tender|"
    r"procurement", re.I)

_OTHER_FUEL = re.compile(r"\bgas\b|\boil\b|hydrogen|transport", re.I)

_LEAD: dict[str, str] = {}


def _clean(raw) -> str:
    return " ".join(html.unescape(BeautifulSoup(str(raw or ""), "html.parser")
                                  .get_text(" ", strip=True)).split())


def discover(session):
    r = get_with_retry(session, API, timeout=60, headers={"Accept": "application/json"})
    try:
        results = r.json().get("results")
    except ValueError:
        raise UpstreamUnavailable("Energy Community news endpoint did not return JSON")
    if not isinstance(results, list) or not results:
        raise CollectorError("Energy Community news endpoint returned no results: API changed")

    found: dict[str, Candidate] = {}
    parsed = 0
    for row in results:
        m = _PATH.match(str(row.get("@path") or ""))
        title = _clean(row.get("title"))
        if not m or not title:
            continue
        parsed += 1
        lead = _clean(row.get("startIntro"))
        cats = {str((c or {}).get("name") or "").strip().lower()
                for c in (row.get("newsCateg") or []) if isinstance(c, dict)}
        text = f"{title} {lead}"
        if _DROP.search(title):
            continue
        if _OTHER_FUEL.search(title) and not re.search(r"electric|power", title, re.I):
            continue
        if not (cats & _KEEP_CATEGORIES) and not _ELECTRICITY.search(text):
            continue
        day = str(row.get("date") or "")[:10]
        date = day if re.match(r"20\d{2}-\d{2}-\d{2}$", day) else None
        sid = f"energy_community-{m.group(2)}-{int(m.group(3)):02d}-{slugify(m.group(4))}"
        _LEAD[sid] = lead
        found.setdefault(sid, Candidate(sid, title, date, f"{BASE}{m.group(1)}.html"))
    if not parsed:
        raise CollectorError("Energy Community news results had no usable path or title: API changed")
    # Twenty-five items, all on gas or the Ukraine fund, is possible and is
    # not a fault.
    if not found:
        raise QuietRun("No electricity item among the latest Energy Community news")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".news-article") or soup.select_one(".news-content")
    if body is None:
        raise CollectorError(f"Energy Community article has no body: {candidate.url}")
    parts = [candidate.title, _LEAD.get(candidate.source_id, ""), html_to_text(body)]
    text = "\n\n".join(p for p in parts if p)
    if len(text) < 200:
        raise CollectorError(f"Energy Community article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
