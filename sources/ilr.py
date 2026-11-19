"""ILR — Institut Luxembourgeois de Régulation, the Luxembourg regulator.

Discovery: the site's own WordPress JSON API, asked for the electricity sector
only. ILR also regulates gas, telecoms, post, rail, the airport and radio
spectrum, and every item is filed under a "secteur"; filtering on the
institute's own classification is more reliable than keywords. robots.txt
allows every path except uploaded form files. French is the site's language.

Three lists are read, newest first:

1. Cadre légal: the institute's decisions and regulations (network tariffs and
   their methodology, approval of the capacity-calculation and balancing
   methodologies that Creos submits with the neighbouring operators, market
   rules), and the laws it files alongside.
2. Consultations: its public consultations.
3. Actualités: news that is not merely the announcement of a decision already
   listed under 1, such as the results of the renewable tenders.

The API gives the title and date but not the text of decisions and
consultations, so the item's page is read and, where the page links a PDF, the
first one (the decision or the consultation document itself) is appended.
Annexes are not read.
"""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ILR (Institut Luxembourgeois de Régulation)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.ilr.lu"
API = f"{BASE}/wp-json/wp/v2"
SECTOR_ELECTRICITY = 49                      # term id of "electricite" in the secteur taxonomy
LISTS = (("cadre-legal", 10), ("consultation", 6), ("actualite", 8))
_FIELDS = "id,date,slug,link,title"
_ALREADY_LISTED = re.compile(r"^\s*((Décision|Règlement)\s+ILR/|Consultation publique)", re.I)
_PAGE_FURNITURE = re.compile(
    r"^(Imprimer|Partager|Partager cette page .*|Télécharger.*|Voir autres documents liés)$", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    for base, limit in LISTS:
        try:
            r = get_with_retry(session, f"{API}/{base}", timeout=45, params={
                "secteur": SECTOR_ELECTRICITY, "per_page": limit, "_fields": _FIELDS})
            posts = r.json()
        except (CollectorError, ValueError) as exc:
            errors.append(f"{base}: {exc}")
            continue
        if not isinstance(posts, list):
            errors.append(f"{base}: not a list")
            continue
        for post in posts:
            title = " ".join(html.unescape((post.get("title") or {}).get("rendered") or "").split())
            link = post.get("link") or ""
            if not title or not link or not post.get("id"):
                continue
            if base == "actualite" and _ALREADY_LISTED.search(title):
                continue
            day = (post.get("date") or "")[:10]
            sid = f"ilr-{base}-{post['id']}"
            found.setdefault(sid, Candidate(
                sid, title[:300], day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None, link))
    if not found:
        raise CollectorError("ILR API listed no electricity items. " + " | ".join(errors)[:300])
    return f"{API}/cadre-legal?secteur={SECTOR_ELECTRICITY}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    pdf = None
    for a in body.select('a[href*="/wp-content/uploads/"]'):
        if a["href"].lower().split("?")[0].endswith(".pdf"):
            pdf = a["href"]
            break
    lines = [ln for ln in html_to_text(body).splitlines() if not _PAGE_FURNITURE.match(ln)]
    # Decisions and consultations are titled by number or period alone; the page's
    # next line says what they are about, and the record is more use with it.
    short = candidate.title.lower()
    for ln in lines[:6]:
        if ln.lower().startswith(short) and len(ln) > len(short) + 15:
            candidate.title = ln[:300]
            break
    parts = [candidate.title, "\n".join(lines)]
    if pdf and "/actualite/" not in candidate.url:
        try:
            doc = extract_pdf_text(get_with_retry(session, pdf, timeout=90).content).strip()
        except Exception:                             # a scanned or broken PDF must not lose the page text
            doc = ""
        if doc:
            parts.append(f"--- Document ({pdf}) ---\n{doc}")
    text = "\n\n".join(parts)
    if len(text) < 200:
        raise CollectorError(f"ILR page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
