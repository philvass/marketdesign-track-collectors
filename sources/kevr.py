"""KEVR (EWRC) — the Bulgarian Energy and Water Regulatory Commission.

Discovery: two server-rendered pages on dker.bg, whose robots.txt is empty:

1. Новини, the commission's news: invitations to public discussions (price
   decisions, the transmission network development plan), announcements of
   adopted prices and rules. Each entry has the full headline, a date and a
   numeric id.
2. Решения за <year>, the list of this year's decisions as PDFs, with the
   decision number and date in the link text. The year in the address is
   taken from the calendar; in the first days of January the new page may not
   exist yet, and then only the news is read.

Bulgarian is read because the English site is a partial translation.

The commission also regulates gas, heat and water, and most of its decisions
concern single companies. News is dropped when the headline is about gas,
heat or water and not electricity. Decisions are kept only outside the
individual series: licences (Л, И-Л, Пр-Л), permissions (Р), business plans
(БП), certificates of origin (С), the monthly household compensations (КБК),
procedural terminations and corrections; what remains (prices, tariffs,
network plans, stranded costs, general conditions) passes the same sector
filter.

Not read: the event calendar of open sessions and the registers on
portal.dker.bg.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  extract_pdf_text, looks_like_pdf, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "KEVR (Bulgaria)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.dker.bg/"
NEWS = f"{BASE}novini"
DECISIONS = BASE + "bg/resheniya/resheniya-za-{year}-g.html"
SCAN_DECISIONS = 400      # one page holds the whole year; scanning it costs no request
MAX_DECISIONS = 10

_NEWS_ID = re.compile(r"/news/(\d+)/")
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_DECISION = re.compile(r"Решение\s*№\s*(.+?)\s*-\s*(\d+)\s+от\s+(\d{1,2})\.(\d{1,2})\.(20\d{2})", re.I)
_INDIVIDUAL = re.compile(r"^(С|Л|Р|И\d*-Л|Пр-Л|БП|БП-Ц|ПП|САП|ОФГ|ФГ|ПК|КБК)$", re.I)
_OTHER_SECTOR = re.compile(
    r"природ\w+ газ|газ\w*\b|ВиК|водоснаб|канализац|топлинн|топлофикац|парно|вода\b", re.I)
# The operators' initials are matched with their case: "есо" also occurs inside
# ordinary words such as "заинтересованите".
_ELECTRICITY = re.compile(r"(?i:електр|възобновяем|балансиращ)|\bЕСО\b|\bНЕК\b")


def _iso(d, m, y) -> str:
    return f"{y}-{int(m):02d}-{int(d):02d}"


def _off_topic(title: str) -> bool:
    return bool(_OTHER_SECTOR.search(title)) and not _ELECTRICITY.search(title)


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    entries = 0

    try:
        soup = BeautifulSoup(get_with_retry(session, NEWS, timeout=45).text, "html.parser")
        for box in soup.select(".news-container-custom"):
            a = box.select_one(".NewsSummaryLink a[href]")
            m = _NEWS_ID.search(a["href"]) if a else None
            if not m:
                continue
            entries += 1
            title = " ".join((a.get("title") or a.get_text(" ", strip=True)).split())
            if not title or _off_topic(title):
                continue
            when = box.select_one(".NewsSummaryPostdate")
            d = _DATE.search(when.get_text() if when else "")
            sid = f"kevr-news-{m.group(1)}"
            found.setdefault(sid, Candidate(sid, title, _iso(*d.groups()) if d else None,
                                            a["href"]))
    except CollectorError as exc:
        errors.append(f"news: {exc}")

    url = DECISIONS.format(year=date.today().year)
    try:
        soup = BeautifulSoup(get_with_retry(session, url, timeout=60).text, "html.parser")
        kept = 0
        for n, a in enumerate(soup.select("a.pdf[href], .content-custom a[href$='.pdf']")):
            if n >= SCAN_DECISIONS or kept >= MAX_DECISIONS:
                break
            title = " ".join(a.get_text(" ", strip=True).split())
            m = _DECISION.search(title)
            if not m:
                continue
            entries += 1
            series = re.sub(r"\s+", "", m.group(1))
            if _INDIVIDUAL.match(series) or _off_topic(title):
                continue
            sid = f"kevr-res-{m.group(5)}-{slugify(a['href'].split('/')[-1].rsplit('.', 1)[0])}"
            if sid in found:
                continue
            found[sid] = Candidate(sid, title[:300], _iso(m.group(3), m.group(4), m.group(5)),
                                   urljoin(BASE, a["href"]))
            kept += 1
    except CollectorError as exc:
        errors.append(f"decisions: {exc}")

    if not entries:
        raise CollectorError("KEVR pages yielded no entries: markup changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise CollectorError("KEVR: every entry was filtered out; check the sector filter")
    return f"{NEWS} + {url}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=120)
    if looks_like_pdf(r):
        text = extract_pdf_text(r.content).strip()
        if len(text) < 150:
            text += ("\n\nБележка: решението е сканиран документ без извличаем текст; пълният "
                     "текст е на адреса на източника. (Note: the decision is a scanned document "
                     "with no extractable text; see the source URL.)")
        return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".content-custom") or soup.select_one(".inner-page")
    if body is None:
        raise CollectorError(f"KEVR news page has no body: {candidate.url}")
    text = f"{candidate.title}\n\n{html_to_text(body)}"
    if len(text) < 200:
        raise CollectorError(f"KEVR news page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
