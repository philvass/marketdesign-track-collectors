"""Brugel — the Brussels-Capital regulator for electricity, gas and water.

Discovery: server-rendered pages on brugel.brussels, whose robots.txt
restricts nothing.

1. The document lists for decisions, opinions (avis) and proposals. Each
   entry is a PDF with its title, a summary, the adoption and publication
   dates and subject tags. Brugel approves Sibelga's tariffs and technical
   regulations, sets green-certificate quotas and support levels, and advises
   the Brussels government on energy ordinances.
2. The news page and the consultations page, where those texts are announced
   and put out for comment.

French is read; every document also exists in Dutch under a parallel path.

Dropped: documents tagged only water, gas, internal organisation or
individual complaints, or about gas alone; accreditations of certification bodies; videos and
conference reports.

Content: for a document, the summary from the list and the text of the PDF;
for a news item, the article page.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Brugel"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://brugel.brussels"
DOCUMENT_LISTS = (f"{BASE}/documents/decisions/rechercher",
                  f"{BASE}/documents/recommendations/rechercher",
                  f"{BASE}/documents/proposals/rechercher")
NEWS_LISTS = (f"{BASE}/actualites", f"{BASE}/actualites/consultations")
PER_LIST = 6

_PUBLISHED = re.compile(r"Parution:\s*(\d{2})\.(\d{2})\.(\d{4})")
_DOTTED = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_NEWS_ID = re.compile(r"/actualites/(?:consultations/)?[^/]*?-(\d+)$")
_OFF_TOPIC_TAGS = {"water", "gas", "regulators", "claims"}
_SKIP = re.compile(r"agrément|organigramme|désignation de membres|^vidéo|conférence|cahiers thématiques|"
                   r"énergie thermique|\beau\b|recrutement|Vivaqua|Hydria", re.I)


def _skip(title: str) -> bool:
    gas_only = re.search(r"\bgaz\b", title, re.I) and not re.search(r"électricité|énergie", title, re.I)
    return bool(gas_only or _SKIP.search(title))

_META: dict[str, str] = {}


def _documents(html: str) -> tuple[int, list[Candidate]]:
    soup = BeautifulSoup(html, "html.parser")
    out, cards = [], 0
    for card in soup.select("div.document"):
        head = card.select_one("a.post-title")
        pdf = card.select_one('a[href*="/publication/document/"]')
        if not head or not pdf:
            continue
        cards += 1
        title = " ".join(head.get_text(" ", strip=True).split())
        tags = {c[4:] for c in card.get("class", []) if c.startswith("tag-")}
        if (tags and tags <= _OFF_TOPIC_TAGS) or "water" in tags or _skip(title):
            continue
        flat = " ".join(card.get_text(" ", strip=True).split())
        d = _PUBLISHED.search(flat) or _DOTTED.search(flat)
        sid = f"brugel-doc-{slugify(pdf['href'].rsplit('/', 1)[-1].rsplit('.', 1)[0])}"
        desc = card.select_one(".document-description")
        _META[sid] = " ".join(desc.get_text(" ", strip=True).split()) if desc else ""
        out.append(Candidate(sid, title, f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
                             urljoin(BASE, pdf["href"])))
        if len(out) >= PER_LIST:
            break
    return cards, out


def _news(html: str) -> tuple[int, list[Candidate]]:
    soup = BeautifulSoup(html, "html.parser")
    out, cards = [], 0
    for head in soup.select('a.post-title[href^="/actualites/"]'):
        m = _NEWS_ID.search(head["href"])
        if not m:
            continue
        cards += 1
        title = " ".join(head.get_text(" ", strip=True).split())
        if not title or _skip(title):
            continue
        box = head.find_parent(class_="article-details") or head.parent.parent
        d = _DOTTED.search(box.get_text(" ", strip=True)) if box else None
        out.append(Candidate(f"brugel-news-{m.group(1)}", title,
                             f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
                             urljoin(BASE, head["href"])))
        if len(out) >= PER_LIST:
            break
    return cards, out


def discover(session):
    found: dict[str, Candidate] = {}
    cards_seen = 0
    errors = []
    for parser, urls in ((_documents, DOCUMENT_LISTS), (_news, NEWS_LISTS)):
        for url in urls:
            try:
                cards, items = parser(get_with_retry(session, url, timeout=60).text)
            except CollectorError as exc:
                errors.append(f"{url.rsplit('/', 2)[-2]}: {exc}")
                continue
            cards_seen += cards
            for c in items:
                found.setdefault(c.source_id, c)
    if not cards_seen:
        raise CollectorError("Brugel lists yielded no entries: markup changed. " + " | ".join(errors)[:300])
    if not found:
        raise QuietRun("Brugel lists held no electricity item this run")
    return " + ".join(DOCUMENT_LISTS + NEWS_LISTS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=90)
    if candidate.source_id.startswith("brugel-doc-"):
        text = extract_pdf_text(r.content).strip()
        summary = _META.get(candidate.source_id) or ""
        return "\n\n".join(p for p in (candidate.title, summary, text) if p)[:MAX_CONTENT_CHARS]
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.select_one("main") or soup).strip()
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
