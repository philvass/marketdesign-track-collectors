"""CWaPE — the Walloon energy regulator (Commission wallonne pour l'Energie).

Discovery: the "Actualités" listing at /documents-recents, a server-rendered
page of the forty newest announcements, each with its date. Every decision,
opinion, consultation and report the commission publishes is announced there
with a link to the document, so the one page covers the publication database
as well. robots.txt is the stock Drupal one and allows it.

CWaPE sets the distribution tariff methodology and the allowed revenues of
the Walloon network operators, writes the technical regulation for the
distribution grids, authorises energy communities and energy sharing, and
advises the Walloon government on draft decrees. French is the complete
edition; the Dutch, German and English ones are partial.

Dropped by title: individual supply licences and single energy-sharing
authorisations, which are case decisions about one company; recruitment and
mandates; the monthly price-comparator update; quarterly statistics; and
items that concern gas only.

Content: the announcement and, when it links one, the text of the first
attached document.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "CWaPE"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.cwape.be"
LISTING = f"{BASE}/documents-recents"
MAX_ITEMS = 25

_SKIP = re.compile(
    r"licences? (générales? )?de fourniture|recrutement|appel public à candidatures|mandat|"
    r"comparateur de prix|statistiques relatives|indicateurs de performance|colloque|"
    r"partage d.énergie \(.*autorisée|^GRD de gaz|^Marché du gaz|newsletter", re.I)


def discover(session):
    r = get_with_retry(session, LISTING, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("CWaPE listing returned an empty response")
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    cards = 0
    for when in soup.select("time[datetime]"):
        card = when.find_parent(class_="layout") or when.parent.parent.parent
        a = card.select_one('a[href^="/documents-recents/"]') if card else None
        if not a:
            continue
        cards += 1
        # Titles are often given in French and German, separated by a dash or a slash.
        title = " ".join(a.get_text(" ", strip=True).split())
        if _SKIP.search(title):
            continue
        sid = f"cwape-{slugify(a['href'].rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, when["datetime"][:10], urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not cards:
        raise CollectorError("CWaPE listing carried no dated announcements: markup changed")
    if not found:
        raise UpstreamUnavailable("CWaPE listing held only licences and notices this run")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    pdf = next((urljoin(BASE, a["href"]) for a in body.find_all("a", href=True)
                if a["href"].startswith("/sites/default/files/") and a["href"].lower().endswith(".pdf")), None)
    parts = [html_to_text(body).strip()]
    if pdf:
        try:
            doc = extract_pdf_text(get_with_retry(session, pdf, timeout=90).content).strip()
        except Exception:        # the announcement stands on its own if the document does not open
            doc = ""
        if doc:
            parts.append(f"--- Document ---\n{doc}")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
