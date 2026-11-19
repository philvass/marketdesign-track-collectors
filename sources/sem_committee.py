"""SEM Committee — the decision-making body of the all-island Single
Electricity Market, formed by CRU (Ireland), the Utility Regulator (Northern
Ireland) and independent members.

Discovery: the server-rendered publications list on semcommittee.com, newest
first, each row with its title and date. Everything the committee issues is
filed there: SEM-numbered decisions, consultation papers and information notes
on the capacity remuneration mechanism, system services (DS3 and its
successor), the trading and settlement code, directed contracts and market
power mitigation. robots.txt allows the list and the publication pages (it
closes only the filtered views of the list, which are not used).

A publication page is a short summary with the paper attached as a PDF; the
summary and the text of the first attached document are read together.
Further attachments (annexes, response templates) are not read.

Dropped by title: the Market Monitoring Unit's weekly and monthly reports,
which are recurring price commentary, and meeting minutes.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "SEM Committee"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.semcommittee.com"
LISTING = f"{BASE}/publications"
MAX_ITEMS = 20
# Twenty rows a page, more than half of them routine monitoring reports.
PAGES = 2

_ITEM = re.compile(r"^/publications/([^/?#]+)$")
_ROUTINE = re.compile(
    r"market monitoring unit weekly|MMU weekly|MMU monthly|market monitoring unit monthly|"
    r"meeting minutes|minutes of|committee meeting", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    rows = 0
    for page in range(PAGES):
        try:
            r = get_with_retry(session, LISTING if page == 0 else f"{LISTING}?page={page}", timeout=45)
        except CollectorError:
            if page == 0:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("article.search-result"):
            a = row.select_one("h3 a[href]")
            m = _ITEM.match(a["href"]) if a else None
            if not m:
                continue
            rows += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            if _ROUTINE.search(title):
                continue
            stamp = row.select_one("time[datetime]")
            day = stamp["datetime"][:10] if stamp else ""
            sid = f"sem-committee-{slugify(m.group(1))}"
            found.setdefault(sid, Candidate(
                sid, title, day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
                urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not rows:
        raise CollectorError("SEM Committee publications list showed no rows: markup changed")
    return LISTING, list(found.values())[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    pdf = None
    for a in body.select('a[href*="/files/"]'):
        if a["href"].lower().split("?")[0].endswith(".pdf"):
            pdf = urljoin(BASE, a["href"])
            break
    parts = [candidate.title, html_to_text(body)]
    if pdf:
        try:
            doc = extract_pdf_text(get_with_retry(session, pdf, timeout=90).content).strip()
        except Exception:                             # a scanned or broken PDF must not lose the summary
            doc = ""
        if doc:
            parts.append(f"--- Document ({pdf}) ---\n{doc}")
    text = "\n\n".join(parts)
    if len(text) < 200:
        raise CollectorError(f"SEM Committee page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
