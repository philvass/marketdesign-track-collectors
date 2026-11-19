"""VREG, since 2025 the Vlaamse Nutsregulator (VNR) — the Flemish regulator
for electricity and gas distribution, now also heat, water and CO2 transport.

Discovery: the two JSON endpoints behind the site's own listings on
vlaamsenutsregulator.be. The news and publication pages are drawn by a script
that asks /api/search/news and /api/search/document for cards; reading those
endpoints directly gives the same lists without a browser. robots.txt is the
stock Drupal one and leaves /api open.

1. Publications, restricted to the electricity-and-gas domain: numbered
   decisions (BESL), advice to the Flemish government (ADV), consultations
   (CONS), reports (RAPP) and communications (MEDE). This is where the
   distribution tariff methodology and the allowed incomes, the technical
   regulations, and the rules for energy sharing and flexibility appear.
2. News, where the regulator explains those decisions and publishes its
   responses to Elia and CREG consultations.

Dropped by title: items that are only about gas, heat, water or CO2, price
comparison campaigns and recruitment.

Content: a news article's own page; for a publication, the page plus the text
of its PDF. Dutch is the only complete edition.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "VREG / Vlaamse Nutsregulator"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.vlaamsenutsregulator.be"
DOCUMENTS = f"{BASE}/api/search/document?page=0&items_per_page=20&facets[]=domain%3A158"
NEWS = f"{BASE}/api/search/news?page=0&items_per_page=20"
PER_LIST = (("pub", DOCUMENTS, "/publicaties/", 14), ("news", NEWS, "/nieuws-en-persoverzicht/", 10))

_MONTHS = {"januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7,
           "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12}
_DATE = re.compile(r"\b(\d{1,2}) (" + "|".join(_MONTHS) + r") (20\d{2})\b", re.I)
_REF = re.compile(r"^[A-Z]{3,5}-20\d{2}-\d+$")
_ELECTRICITY = re.compile(r"elektricit|stroom|energie|nettarie|netbeheer|flexibilit|capaciteitstarief|"
                          r"Elia|CREG|aansluiting|digitale meter|certificat|garanties van oorsprong", re.I)
_OTHER_SECTOR = re.compile(r"aardgas|\bgas\b|gasvolumes|waterstof|warmte|\bwater|drinkwater|riool|CO2", re.I)
_SKIP = re.compile(r"V-check|V-test|kandidaatstelling|vacature|dashboard|maandelijkse cijfers|"
                   r"hoe denkt de vlaming|overdracht van de energiecontracten", re.I)


def _date(text: str) -> str | None:
    m = _DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    except ValueError:
        return None


def _wanted(title: str) -> bool:
    if _SKIP.search(title):
        return False
    return not (_OTHER_SECTOR.search(title) and not re.search(r"elektricit|stroom", title, re.I))


def discover(session):
    found: dict[str, Candidate] = {}
    cards_seen = 0
    errors = []
    for kind, url, prefix, cap in PER_LIST:
        try:
            results = get_with_retry(session, url, timeout=45).json().get("results") or []
        except (CollectorError, ValueError) as exc:
            errors.append(f"{kind}: {exc}")
            continue
        n = 0
        for row in results:
            soup = BeautifulSoup("".join(row.get("teaser") or []), "html.parser")
            for svg in soup("svg"):
                svg.decompose()
            a = soup.find("a", href=lambda h: h and h.startswith(prefix))
            lines = [" ".join(s.split()) for s in soup.get_text("\n", strip=True).split("\n")]
            lines = [s for s in lines if s and s not in ("Nieuw", "Nieuwsartikel", "Persbericht")]
            if not a or not lines:
                continue
            cards_seen += 1
            head = soup.find(["h2", "h3"])
            title = " ".join(head.get_text(" ", strip=True).split()) if head else lines[0]
            title = title.replace("​", "").strip()
            if kind == "pub" and _REF.match(lines[0]) and len(lines) > 1:
                # A publication card is headed by its reference; the line under it says what it is.
                title = f"{lines[0]}: {lines[1]}".replace("\u200b", "")
            if not _wanted(title) or (kind == "news" and not _ELECTRICITY.search(" ".join(lines))):
                continue
            sid = f"vreg-{kind}-{slugify(a['href'].rstrip('/').split('/')[-1])}"
            if sid in found:
                continue
            found[sid] = Candidate(sid, title, _date(" ".join(lines)), urljoin(BASE, a["href"]))
            n += 1
            if n >= cap:
                break
    if not cards_seen:
        raise CollectorError("Vlaamse Nutsregulator search endpoints returned no cards: format changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise UpstreamUnavailable("No electricity item among the newest Vlaamse Nutsregulator publications")
    return f"{DOCUMENTS} + {NEWS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "svg", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup
    pdf = next((a["href"] for a in body.find_all("a", href=True)
                if a["href"].startswith("https://assets.vlaamsenutsregulator.be/")
                and ".pdf" in a["href"].lower()), None)
    text = html_to_text(body).strip()
    if not candidate.publication_date:
        candidate.publication_date = _date(text[:1500])
    parts = [candidate.title, text]
    if pdf and "-pub-" in candidate.source_id:
        try:
            doc = extract_pdf_text(get_with_retry(session, pdf, timeout=90).content).strip()
        except Exception:        # the page still names the decision if the PDF does not open
            doc = ""
        if doc:
            parts.append(f"--- Document ---\n{doc}")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
