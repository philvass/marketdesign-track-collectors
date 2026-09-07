"""URE (ure.gov.pl) — Polish energy regulator.

Discovery: the server-rendered "aktualnosci" listing, whose article links carry
a numeric id and a slugged title. URE sets the tariffs, runs the renewable
auctions and publishes the president's positions on market rules.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "URE"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.ure.gov.pl"
LISTING = f"{BASE}/pl/urzad/informacje-ogolne/aktualnosci"
ARTICLE = re.compile(r"/aktualnosci/(\d+),")


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("URE listing returned an empty response")
    soup = BeautifulSoup(r.text, "html.parser")

    found: dict[str, Candidate] = {}
    for a in soup.find_all("a", href=True):
        m = ARTICLE.search(a["href"])
        title = " ".join(a.get_text(" ", strip=True).split())
        if not m or len(title) < 20:
            continue
        sid = f"ure-{m.group(1)}"
        found.setdefault(sid, Candidate(sid, title, None, urljoin(BASE, a["href"])))

    if not found:
        raise UpstreamUnavailable("URE listing carried no article links")
    return LISTING, list(found.values())


# The listing gives no dates; they are read from the article page, so the
# freshness gate has to wait until after the fetch.
DATE_REFINED_ON_FETCH = True

PL_MONTHS = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5,
             "czerwca": 6, "lipca": 7, "sierpnia": 8, "września": 9, "wrzesnia": 9,
             "października": 10, "pazdziernika": 10, "listopada": 11, "grudnia": 12}
_DATE_PL = re.compile(r"(\d{1,2})\s+(" + "|".join(PL_MONTHS) + r")\s+(20\d{2})", re.I)


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.find("main") or soup.find("article") or soup
    text = html_to_text(body)

    if not candidate.publication_date:
        # URE writes dates in Polish words and appends them to the headline,
        # which is more reliable than the first numeric string in the body.
        m = _DATE_PL.search(candidate.title) or _DATE_PL.search(text[:1500])
        if m:
            try:
                candidate.publication_date = datetime(
                    int(m.group(3)), PL_MONTHS[m.group(2).lower()],
                    int(m.group(1))).date().isoformat()
            except (ValueError, KeyError):
                pass
    if len(text.strip()) < 300:
        raise CollectorError(f"URE page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
