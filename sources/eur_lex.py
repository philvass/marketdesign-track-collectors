"""EUR-Lex — EU legislation as published in the Official Journal.

Discovery: the Publications Office SPARQL endpoint (CELLAR), which is the
official machine interface to the OJ. Acts are selected by their EUR-Lex
directory code: everything under 12 is energy. CELEX numbers beginning with
3 are secondary legislation; consolidated texts (0…) are versions of acts
already published and are deliberately excluded.

CELLAR indexes directory codes some weeks after publication, so this source
runs behind the OJ rather than with it. The freshness gate in core.py is set
against publication date, so the window here is wide and the state cache does
the deduplication.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import date, timedelta

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "EUR-Lex"
DOCUMENT_TYPE = "REGULATOR"

# The one exception to the site-wide "today or yesterday" rule, and it exists
# because of how EUR-Lex works rather than as a preference: CELLAR indexes the
# Official Journal days after the act is published, so a one-day window would
# baseline nearly every act instead of reporting it. A week is the smallest
# window that still catches them. The worker honours this because the payload
# carries it; see build_payload in core.py.
MAX_AGE_DAYS = 7

SPARQL = "http://publications.europa.eu/webapi/rdf/sparql"
BASE = "https://eur-lex.europa.eu"
DIRECTORY_ENERGY = "http://publications.europa.eu/resource/authority/dir-eu-legal-act/12"
WINDOW_DAYS = 180
LIMIT = 40

# CELLAR runs weeks behind the Official Journal, so the default 30-day gate
# would baseline almost every act instead of reporting it. TRACK should still
# carry an act it first learns about six weeks after publication.

QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?title WHERE {
  ?work cdm:resource_legal_id_celex ?celex ;
        cdm:work_date_document ?date ;
        cdm:resource_legal_is_about_concept_directory-code ?dir .
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
        cdm:expression_title ?title .
  FILTER(STRSTARTS(STR(?dir), "%s"))
  FILTER(STRSTARTS(STR(?celex), "3"))
  FILTER(?date >= "%s"^^xsd:date)
} ORDER BY DESC(?date) LIMIT %d"""

# Directory codes are assigned some time after the record itself appears, so a
# second pass catches recent acts by subject words in the title. The union is
# deduplicated on CELEX.
QUERY_KEYWORD = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?title WHERE {
  ?work cdm:resource_legal_id_celex ?celex ;
        cdm:work_date_document ?date .
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
        cdm:expression_title ?title .
  FILTER(STRSTARTS(STR(?celex), "3"))
  FILTER(?date >= "%s"^^xsd:date)
  FILTER(CONTAINS(LCASE(STR(?title)), "electricity")
      || CONTAINS(LCASE(STR(?title)), "energy market")
      || CONTAINS(LCASE(STR(?title)), "guarantees of origin")
      || CONTAINS(LCASE(STR(?title)), "emission allowance"))
} ORDER BY DESC(?date) LIMIT %d"""


def discover(session):
    since = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
    query = QUERY % (DIRECTORY_ENERGY, since, LIMIT)

    def ask(sparql_query: str) -> list:
        u = f"{SPARQL}?" + urllib.parse.urlencode({
            "query": sparql_query, "format": "application/sparql-results+json"})
        r = get_with_retry(session, u, timeout=120)
        if not r.content.strip():
            raise UpstreamUnavailable("CELLAR SPARQL endpoint returned an empty response")
        try:
            return r.json()["results"]["bindings"]
        except (ValueError, KeyError) as exc:
            raise UpstreamUnavailable(f"CELLAR SPARQL returned no usable result set: {exc}")

    rows = ask(query)
    try:
        rows += ask(QUERY_KEYWORD % (since, LIMIT))
    except UpstreamUnavailable:
        pass

    found: dict[str, Candidate] = {}
    for b in rows:
        celex = (b.get("celex") or {}).get("value") or ""
        title = " ".join(((b.get("title") or {}).get("value") or "").split())
        published = ((b.get("date") or {}).get("value") or "")[:10] or None
        if not celex or not title:
            continue
        sid = f"eurlex-{celex}"
        url_doc = f"{BASE}/legal-content/EN/TXT/?uri=CELEX:{celex}"
        found.setdefault(sid, Candidate(sid, title, published, url_doc))

    if not found:
        raise UpstreamUnavailable(
            f"no energy acts indexed in CELLAR since {since}")
    return f"{SPARQL} (directory code 12, since {since})", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=90)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    # The act text sits in the document panel; the page around it is EUR-Lex
    # chrome (language pickers, procedure links) that would otherwise dominate.
    body = (soup.select_one("#docHtml") or soup.select_one(".eli-container")
            or soup.select_one("#text") or soup.select_one("#TexteOnly")
            or soup.find("main") or soup)
    text = html_to_text(body)
    if len(text.strip()) < 400:
        raise CollectorError(f"EUR-Lex page yielded no act text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
