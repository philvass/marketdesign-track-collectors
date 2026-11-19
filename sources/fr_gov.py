"""French energy ministry (DGEC) — public consultations on draft regulations.

Discovery: the "Energies et climat" section of the ministry's public
consultation site, consultations-publiques.developpement-durable.gouv.fr.
French law requires draft decrees and orders with an environmental effect to
be put to the public there before signature, so this is where the texts that
change the electricity market first appear in full: the multi-year energy
programme, tender specifications and support schemes for renewables, the
capacity mechanism, demand response, storage, grid connection rules, the
post-ARENH nuclear arrangements. The site's robots.txt allows everything but
its editing area and asks for one second between requests, which is observed.

The section is mostly energy-savings certificates, label methods and building
rules, so a filter on the title keeps the electricity items only. The three
newest pages of the section are read (24 consultations); the date is the day
the consultation opened.

Not read: the ministry's own site, ecologie.gouv.fr. It answered every
request, robots.txt included, with a 503 maintenance page on the day this
adapter was written (19 November 2026), so its press listing could not be
examined. CRE's deliberations, which the `cre` adapter reads, cover the
regulator's side.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "French Ministry for Energy (DGEC)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://www.consultations-publiques.developpement-durable.gouv.fr/"
SECTION = f"{BASE}energies-et-climat-r4.html"
PAGES = (0, 8, 16)               # the section shows eight consultations per page
MAX_ITEMS = 20

_ARTICLE = re.compile(r"-a(\d+)\.html")
_OPENED = re.compile(r"Consultation du (\d{2})/(\d{2})/(\d{4})")
_ELECTRICITY = re.compile(
    r"électricité|electricite|électrique|réseaux? publics? d|réseau de transport|"
    r"mécanisme de capacité|garanties? de capacité|effacement|flexibilité|stockage|"
    r"programmation pluriannuelle de l.énergie|\bPPE\b|énergies? renouvelables?|"
    r"complément de rémunération|obligation d.achat|appels? d.offres|garanties? d.origine|"
    r"photovolta|éolien|hydroélectri|nucléaire|\bARENH\b|tarifs? réglementés?|\bTURPE\b|"
    r"raccordement|interconnexion|fournisseurs? d|marché de l.énergie|autoconsommation|"
    r"code de l.énergie", re.I)
_NOT_MARKET = re.compile(
    r"certificats d.économies d.énergie|fiches? d.opérations? standardisée|label bas.carbone|"
    r"véhicules?|audit énergétique|score environnemental|Natura 2000|performance énergétique|"
    r"installations? nucléaires? de base|déchets", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    cards_seen = 0
    for n, start in enumerate(PAGES):
        if n:
            time.sleep(1.2)      # robots.txt: Crawl-Delay 1
        url = SECTION if not start else f"{SECTION}?lang=fr&debut_listearticles={start}"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if not n:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("div.item-liste-articles"):
            a = card.select_one("a.fr-card__link[href]")
            m = _ARTICLE.search(a["href"]) if a else None
            if not m:
                continue
            cards_seen += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            if _NOT_MARKET.search(title) or not _ELECTRICITY.search(title):
                continue
            when = card.select_one(".dateart")
            d = _OPENED.search(when.get_text(" ", strip=True)) if when else None
            sid = f"fr_gov-consultation-{m.group(1)}"
            found.setdefault(sid, Candidate(
                sid, title[0].upper() + title[1:],
                f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
                urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not cards_seen:
        raise CollectorError("French consultation site listed no consultations: markup changed")
    if not found:
        raise UpstreamUnavailable(
            f"No electricity text among the {cards_seen} newest energy and climate consultations")
    return SECTION, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    time.sleep(1.2)
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "form"]):
        tag.decompose()
    parts = [candidate.title]
    for selector in (".date-article", ".texte-article", ".listedocuments"):
        node = soup.select_one(selector)
        text = html_to_text(node).strip() if node else ""
        if text:
            parts.append(("Documents joints :\n" if selector == ".listedocuments" else "") + text)
    if len(parts) < 3:
        raise CollectorError(f"French consultation page yielded no text: {candidate.url}")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
