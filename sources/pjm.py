"""PJM — the largest US wholesale market.

Discovery: the Inside Lines RSS feed, which carries full article bodies in
content:encoded, so a release needs no second request. PJM's own newsroom
page is a JavaScript shell whose only usable links are release PDFs, and the
feed reaches the same announcements, so the feed is the whole source.

The feed is dominated by hot-weather and operations notices. Those are what
the shared US title filter exists to drop; what survives is capacity-market,
governance and FERC-filing news.
"""
from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, get_with_retry, html_to_text, slugify, MAX_CONTENT_CHARS
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "PJM"
DOCUMENT_TYPE = "ISO"

FEED = "https://insidelines.pjm.com/feed/"
_ITEM = re.compile(r"<item>(.*?)</item>", re.S)


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", block, re.S)
    return " ".join(m.group(1).split()) if m else ""


def _body(block: str) -> str:
    m = re.search(r"<content:encoded>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</content:encoded>", block, re.S)
    if not m:
        m = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.S)
    return m.group(1) if m else ""


def _date(raw: str) -> str | None:
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return None


# Bodies come from the feed, so nothing is fetched twice; keep them here.
_BODIES: dict[str, str] = {}


def _diagnose(r) -> str:
    """Describe what actually came back.

    "carried no items" is useless when the same request returns ten items
    from a laptop and none from a runner, which is what PJM does. Recording
    the status, size and opening bytes turns the next failure into evidence
    instead of another round of guessing.
    """
    head = " ".join(r.text[:160].split())
    title = re.search(r"<title[^>]*>([^<]{0,80})", r.text, re.I)
    return (f"HTTP {r.status_code}, {len(r.text)}B, "
            f"type={r.headers.get('content-type', '?')}, "
            f"title={title.group(1).strip() if title else 'none'}, starts={head!r}")


def discover(session):
    """Read the feed, retrying an empty one.

    The feed flaps: two runs three minutes apart returned ten items and then
    none, from the same runner. An empty body arrives as HTTP 200, so
    get_with_retry has nothing to react to and the collector declared the
    source unavailable on roughly half its runs. Under a one-day freshness
    window those are not delays, they are losses, so an empty read is retried
    rather than believed first time.
    """
    r = None
    for attempt in range(3):
        r = get_with_retry(session, FEED, timeout=45)
        found: dict[str, Candidate] = {}
        for block in _ITEM.findall(r.text):
            title = _tag(block, "title")
            link = _tag(block, "link")
            if not title or not link:
                continue
            sid = f"pjm-{slugify(link.rstrip('/').split('/')[-1])}"
            found.setdefault(sid, Candidate(sid, title, _date(_tag(block, "pubDate")), link))
            _BODIES[sid] = _body(block)
        if found:
            return FEED, list(found.values())
        if attempt + 1 < 3:
            time.sleep(5.0 * (attempt + 1))

    raise UpstreamUnavailable(
        f"PJM Inside Lines feed carried no items on 3 attempts — {_diagnose(r)}")


def is_out_of_scope(candidate: Candidate) -> bool:
    return not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    html = _BODIES.get(candidate.source_id)
    if html:
        text = html_to_text(BeautifulSoup(html, "html.parser"))
        if len(text) >= 200:
            return text[:MAX_CONTENT_CHARS]
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.select_one(".entry-content") or soup.find("article") or soup.find("main") or soup
    return html_to_text(main)[:MAX_CONTENT_CHARS]
