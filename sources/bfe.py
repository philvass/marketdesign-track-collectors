"""Swiss Federal Office of Energy (BFE/SFOE) and its ministry, DETEC/UVEK.

Discovery: the federal administration's news service feed for the energy
office (organisation 808), in German because that edition is complete; the
English one carries only the items that were translated. The same feed
includes releases issued by the ministry itself and by the Federal Council on
energy matters, and ElCom's media releases, which is why they are read here.

Swiss electricity law (the Electricity Supply Act and Energy Act revisions,
the winter reserve, market opening, the electricity agreement with the EU) is
made through these announcements. Everything else the office publishes, from
building programmes to nuclear diplomacy, is dropped by a title-and-lead
filter before the document is submitted.

Teaser-only: the article pages on admin.ch refuse automated requests, so the
record carries the title and the official lead paragraph from the feed, with
the article linked for the reader. The feed is fetched once per run and never
polled across organisation numbers; the service drops connections quickly.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Swiss Federal Office of Energy (BFE)"
DOCUMENT_TYPE = "REGULATOR"

FEED = "https://www.newsd.admin.ch/newsd/feeds/rss?lang=de&org-nr=808"
MAX_ITEMS = 25

_AUTHORS = re.compile(
    r"Bundesamt für Energie|UVEK|Umwelt, Verkehr, Energie und Kommunikation|Bundesrat|"
    r"Elektrizitätskommission|ElCom", re.I)
_ELECTRICITY = re.compile(
    r"\bStrom|Elektrizit|Stromversorgung|Versorgungssicherheit|Winterreserve|Stromreserve|"
    r"Reservekraftwerk|Wasserkraftreserve|Netzzuschlag|Netznutzung|Übertragungsnetz|Verteilnetz|"
    r"Stromabkommen|Marktöffnung|Grundversorgung|Regelenergie|Systemdienstleistung|"
    r"Herkunftsnachweis|Einspeisevergütung|Marktprämie|Auktion|Speicher|Flexibilität|"
    r"Energiegesetz|Mantelerlass|ElCom", re.I)

_META: dict[str, dict] = {}


def _date(raw: str | None) -> str | None:
    try:
        return parsedate_to_datetime(raw).date().isoformat() if raw else None
    except (TypeError, ValueError):
        return None


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("Swiss federal news feed returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"Swiss federal news feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("Swiss federal news feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        author = " ".join((item.findtext("author") or "").split())
        lead = " ".join(BeautifulSoup(item.findtext("description") or "", "html.parser")
                        .get_text(" ", strip=True).split())
        if not title or not link:
            continue
        if author and not _AUTHORS.search(author):
            continue
        if not _ELECTRICITY.search(f"{title} {lead}"):
            continue
        sid = f"bfe-{slugify(link.rstrip('/').split('/')[-1])}"
        _META[sid] = {"author": author, "lead": lead}
        found.setdefault(sid, Candidate(sid, title, _date(item.findtext("pubDate")), link))
        if len(found) >= MAX_ITEMS:
            break
    # A feed with no electricity item in it is a quiet week, not an outage, and
    # reporting it as one would cry wolf: return what there is, even nothing.
    if not found:
        raise UpstreamUnavailable("No electricity-market item in the Swiss federal energy feed this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    meta = _META.get(candidate.source_id) or {}
    parts = [candidate.title]
    if meta.get("author"):
        parts.append(f"Herausgeber: {meta['author']}")
    if meta.get("lead"):
        parts.append(meta["lead"])
    parts.append("Hinweis: Die Artikelseiten von admin.ch sind nur für Browser abrufbar; dieser Eintrag "
                 "enthält den offiziellen Lead der Medienmitteilung. Volltext unter der Quell-URL. "
                 "(Note: admin.ch article pages are served only to browsers; this record carries the "
                 "official lead of the release. Full text at the source URL.)")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
