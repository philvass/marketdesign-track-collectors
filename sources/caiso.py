"""CAISO — California ISO.

Discovery: the news-release listing, server-rendered as cards with a topic
label and a dated <time>. Only the market topics are kept (Markets, Extended
Day-Ahead Market, Western Energy Markets, Regulatory); membership
announcements and quarterly benefit reports are dropped by title.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, get_with_retry, html_to_text, slugify, MAX_CONTENT_CHARS
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "CAISO"
DOCUMENT_TYPE = "ISO"

BASE = "https://www.caiso.com"
LISTING = f"{BASE}/about/news/news-releases"
TOPICS = {"markets", "extended day-ahead market", "western energy markets", "regulatory"}


def _date(raw: str) -> str | None:
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for card in soup.select("a.card-post-news-release[href]"):
        h3 = card.select_one("h3.card-title")
        label = card.select_one(".card-body .text-muted")
        time_el = card.find("time")
        if not h3:
            continue
        topic = ""
        if label:
            topic = label.get_text(" ", strip=True).split("|")[-1].strip().lower()
        if topic and topic not in TOPICS:
            continue
        title = " ".join(h3.get_text(" ", strip=True).split())
        url = urljoin(BASE, card["href"])
        sid = f"caiso-{slugify(url.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, _date(time_el.get("datetime", "") if time_el else ""), url))
    if not found:
        raise UpstreamUnavailable("CAISO news listing carried no market-topic releases")
    return LISTING, list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    return not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.get_text(" ", strip=True).split())
        if len(title) > 8:
            candidate.title = title
    time_el = soup.find("time", attrs={"datetime": True})
    if time_el and not candidate.publication_date:
        candidate.publication_date = _date(time_el["datetime"])
    main = soup.find("main") or soup
    return html_to_text(main)[:MAX_CONTENT_CHARS]
