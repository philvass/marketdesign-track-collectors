"""Slovenian Ministry of Infrastructure and Energy (Ministrstvo za
infrastrukturo in energetiko), on the government portal gov.si.

Discovery: the portal's news feed for the ministry (organisation 4450), in
Slovenian. Energy moved to this ministry in the 2026 government; the former
ministry for the environment, climate and energy no longer carries it. The
portal's robots.txt forbids only its admin, resources and help paths.

Electricity legislation and support schemes are announced here: public
hearings on decrees (the renewables contribution, network and storage
support), the Electricity Supply Act and its amendments, state-aid approvals,
the JEK2 nuclear project's legal framework. The same ministry runs roads,
rail, aviation and weekly fuel-price notices, so a title-and-lead filter keeps
only electricity items before anything is fetched.

The article pages are served to plain requests, so the full text is read.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Ministry of Infrastructure and Energy (Slovenia)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

FEED = "https://www.gov.si/novice/rss/?orgID%5B0%5D=4450"
MAX_ITEMS = 25

_ELECTRICITY = re.compile(
    r"električn\w+ energij|elektrik|elektroenerget|oskrb\w+ z električno|omrežnin|"
    r"prenosn\w+ (?:in distribucijsk\w+ )?(?:električn\w+ )?omrežj|distribucijsk\w+ omrežj|"
    r"obnovljiv\w+ vir|prispevk\w+ za (?:spodbujanje|obnovljive)|hranilnik|shranjevanj\w+ energij|"
    r"samooskrb|skupnost\w* obnovljivih|JEK ?2|jedrsk|sončn\w+ elektrarn|vetrn\w+ elektrarn|"
    r"hidroelektrarn|energetsk\w+ (?:zakon|okvir|prehod|koncept)|trg\w* z elektri|"
    r"zmogljivostn|prožnost|NEPN|agrofotovolt|fotovolt|Borzen|ELES\b", re.I)
_NOT = re.compile(
    r"električn\w+ (?:vozil|koles|avtobus|polniln)|pnevmatik|bencin|dizl|kolesarsk|"
    r"taksi|železni|lažn\w+ spletn", re.I)


def discover(session):
    r = get_with_retry(session, FEED, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("gov.si news feed returned an empty response")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        raise CollectorError(f"gov.si news feed did not parse: {exc}")
    items = root.findall(".//item")
    if not items:
        raise CollectorError("gov.si ministry feed carried no items: format changed")

    found: dict[str, Candidate] = {}
    for item in items:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        lead = " ".join(BeautifulSoup(item.findtext("description") or "", "html.parser")
                        .get_text(" ", strip=True).split())
        if not title or not link:
            continue
        if _NOT.search(title) or not _ELECTRICITY.search(f"{title} {lead}"):
            continue
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            when = None
        sid = f"si_gov-{slugify(link.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, title, when, link))
        if len(found) >= MAX_ITEMS:
            break
    # The feed holds four months of every transport and energy release; none
    # of them being about electricity is a quiet spell, not a defect.
    if not found:
        raise UpstreamUnavailable("No electricity item in the Slovenian ministry feed this run")
    return FEED, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("main") or soup.select_one("article")
    if body is None:
        raise CollectorError(f"gov.si article has no body: {candidate.url}")
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"gov.si article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
