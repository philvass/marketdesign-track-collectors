"""Litgrid — the Lithuanian electricity transmission system operator.

Discovery: two server-rendered listings on litgrid.eu, in Lithuanian because
that is the complete edition:

1. Naujienos, the news cards, each with its date and title (two pages).
2. Viešosios konsultacijos, the public consultations on balancing and
   ancillary-service contracts, connection terms and network methodologies.
   These cards show only a status ("Vykstanti"), so the date is read from the
   consultation page when it is fetched.

robots.txt allows every path to general agents (it closes only wp-admin and
names a list of AI-training crawlers, which this collector is not); it also
carries a content signal of search=yes, ai-train=no. The site's WordPress API
answers only to logged-in users, so the pages are read instead.

Dropped by title: the weekly price review, interconnector trip notices,
corporate items (results, bonds, appointments, awards) and procurement notes.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Litgrid"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.litgrid.eu"
NEWS = f"{BASE}/naujienos"
CONSULTATIONS = f"{BASE}/naujienos/viesos-konsultacijos"
NEWS_PAGES = 2
MAX_ITEMS = 25

# Consultation cards carry no date; it is on the page itself.
DATE_REFINED_ON_FETCH = True

_MONTHS = {"sausio": 1, "vasario": 2, "kovo": 3, "balandžio": 4, "gegužės": 5, "birželio": 6,
           "liepos": 7, "rugpjūčio": 8, "rugsėjo": 9, "spalio": 10, "lapkričio": 11, "gruodžio": 12}
_DATE = re.compile(r"(20\d{2})\s*m\.\s*(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\s*d\.", re.I)
_DATE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_SLUG = re.compile(r"/naujienos/(?:viesos-konsultacijos/)?([^/?#]+)/?$")
_DROP = re.compile(
    r"praėjusią savaitę|savaitės apžvalga|finansini|pelno|pelnas|obligacij|valdybos nar|valdybos pirminink|"
    r"vadov\w+ paskirt|generalin\w+ direktor|param\w+ |apdovanoj|geriausi\w+ darbdav|stažuot|"
    r"karjer|rangos darb|rangov|mėnesių rezultatai|metų rezultatai|pusmečio rezultatai|"
    r"^Įjungta|^Atsijungė|\bperka\b", re.I)


def _date(text: str) -> str | None:
    m = _DATE.search(text or "")
    if m:
        return f"{m.group(1)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(3)):02d}"
    return None


def discover(session):
    found: dict[str, Candidate] = {}
    cards_seen = 0

    r = get_with_retry(session, CONSULTATIONS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for card in soup.select(".public-consultation-card"):
        a = card.select_one("a[href]")
        head = card.select_one(".public-consultation-card__title")
        m = _SLUG.search(a["href"]) if a else None
        if not m or not head:
            continue
        cards_seen += 1
        sid = f"litgrid-konsultacija-{slugify(m.group(1))}"
        found.setdefault(sid, Candidate(sid, " ".join(head.get_text(" ", strip=True).split()),
                                        None, a["href"]))

    for page in range(1, NEWS_PAGES + 1):
        url = NEWS if page == 1 else f"{NEWS}?sf_paged={page}"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if page == 1:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("article.article-card"):
            head = card.select_one("h3")
            a = head.find_parent("a", href=True) if head else None
            m = _SLUG.search(a["href"]) if a else None
            if not m:
                continue
            cards_seen += 1
            title = " ".join(head.get_text(" ", strip=True).split())
            if _DROP.search(title):
                continue
            stamp = card.select_one(".article-card__date")
            sid = f"litgrid-{slugify(m.group(1))}"
            found.setdefault(sid, Candidate(
                sid, title, _date(stamp.get_text(" ", strip=True) if stamp else ""), a["href"]))
            if len(found) >= MAX_ITEMS:
                break
    if not cards_seen:
        raise CollectorError("Litgrid listings showed no news or consultation cards: markup changed")
    return f"{NEWS} + {CONSULTATIONS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    if not candidate.publication_date:
        meta = soup.select_one('meta[property="article:published_time"]')
        iso = _DATE_ISO.search(meta.get("content", "")) if meta else None
        if iso:
            candidate.publication_date = iso.group(0)
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = (soup.select_one(".elementor-widget-theme-post-content") or soup.select_one("main")
            or soup.select_one("article") or soup)
    text = html_to_text(body)
    if not candidate.publication_date:
        candidate.publication_date = _date(html_to_text(soup)[:3000])
    if len(text.strip()) < 200:
        raise CollectorError(f"Litgrid page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
