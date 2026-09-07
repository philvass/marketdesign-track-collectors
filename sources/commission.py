"""European Commission, DG ENER (energy.ec.europa.eu) — consultations and policy
documents.

Discovery: the consultations listing plus the energy sitemap, which together
catch both formal consultations and the documents published beside them.
"""
from __future__ import annotations

import html
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  extract_pdf_text, html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "European Commission"
DOCUMENT_TYPE = "REGULATOR"

COMMISSION_CONSULTATIONS_URL = "https://energy.ec.europa.eu/resources/consultations_en"
COMMISSION_SITEMAP_URL = "https://energy.ec.europa.eu/sitemap.xml"
COMMISSION_PAST_PAGES = 3

DATE_RE = re.compile(
    r"\b(?:Opened|Closes|Closed)\s+(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(20\d{2})\b",
    re.I,
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def normalise_commission_date(day: str, month: str, year: str) -> str:
    return datetime.strptime(
        f"{day} {month} {year}",
        "%d %B %Y",
    ).date().isoformat()


def source_id_from_url(url: str) -> str:
    path = url.split("?", 1)[0].strip("/").split("/")
    slug = "-".join(path[-2:]).lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    return f"commission-consultation-{slug}"


def parse_listing_candidates(html: str, base_url: str) -> list[Candidate]:
    """Parse consultation cards from the DG ENER consultation listing."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Candidate] = {}

    for article in soup.select("article.ecl-content-item"):
        link = article.select_one("a[data-ecl-title-link][href]")
        if not link:
            continue

        url = urljoin(base_url, link["href"])
        title = " ".join(link.get_text(" ", strip=True).split())

        if not title or "have-your-say" not in url:
            continue

        times = article.find_all("time")
        publication_date = None

        if times:
            raw_date = times[0].get_text(" ", strip=True)
            m = re.search(
                r"^(\d{1,2})\s+"
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
                r"(20\d{2})$",
                raw_date,
                re.I,
            )
            if m:
                publication_date = normalise_commission_date(
                    m.group(1), m.group(2), m.group(3)
                )

        sid = source_id_from_url(url)

        found.setdefault(
            sid,
            Candidate(
                source_id=sid,
                title=title,
                publication_date=publication_date,
                url=url,
            ),
        )

    return list(found.values())


def parse_sitemap_candidates(xml_text: str) -> list[Candidate]:
    """Historical fallback for consultation pages present in the Energy sitemap."""
    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    found: dict[str, Candidate] = {}

    for loc in root.findall(".//sm:loc", ns):
        if not loc.text:
            continue

        url = loc.text.strip()

        if "/resources/consultations/" not in url:
            continue
        if not url.endswith("_en"):
            continue

        sid = source_id_from_url(url)

        found.setdefault(
            sid,
            Candidate(
                source_id=sid,
                title="",
                publication_date=None,
                url=url,
            ),
        )

    return list(found.values())


def discover(session: requests.Session) -> tuple[str, list[Candidate]]:
    found: dict[str, Candidate] = {}

    # Current/upcoming consultations.
    upcoming_url = (
        COMMISSION_CONSULTATIONS_URL
        + "?f%5B0%5D=oe_consultation_status%3Aupcoming"
    )
    r = get_with_retry(session, upcoming_url)

    for candidate in parse_listing_candidates(r.text, r.url):
        found[candidate.source_id] = candidate

    # Most recent closed consultations. Three pages currently cover roughly
    # the newest 30 items while avoiding a full 23-page crawl every run.
    for page in range(COMMISSION_PAST_PAGES):
        past_url = (
            COMMISSION_CONSULTATIONS_URL
            + f"?f%5B0%5D=oe_consultation_status%3Apast&page={page}"
        )
        past = get_with_retry(session, past_url)

        for candidate in parse_listing_candidates(past.text, past.url):
            found[candidate.source_id] = candidate

        time.sleep(1.0)

    # Keep historical sitemap candidates as a fallback. Existing source IDs
    # are preserved so previously bootstrapped items remain duplicates.
    try:
        sitemap = get_with_retry(session, COMMISSION_SITEMAP_URL)

        for candidate in parse_sitemap_candidates(sitemap.text):
            found.setdefault(candidate.source_id, candidate)

    except CollectorError:
        pass

    candidates = list(found.values())

    if not candidates:
        raise CollectorError(
            "European Commission consultation discovery returned no candidates"
        )

    return COMMISSION_CONSULTATIONS_URL, candidates


def is_out_of_scope(candidate: Candidate) -> bool:
    """Return True for Commission consultations clearly outside electricity market design."""
    excluded_topics = (
        "candidate hydrogen projects",
        "gas network codes and guidelines",
        "long-term gas products",
    )
    title_lower = candidate.title.lower()
    return any(topic in title_lower for topic in excluded_topics)


def fetch_content(session: requests.Session, candidate: Candidate) -> str:
    # Have Your Say pages are JavaScript shells. Use the Commission BRP API.
    if "better-regulation/have-your-say/initiatives/" in candidate.url:
        m = re.search(r"/initiatives/(\d+)", candidate.url)
        if not m:
            raise CollectorError(
                f"Could not extract Commission initiative ID from {candidate.url}"
            )

        initiative_id = m.group(1)
        api_url = (
            "https://ec.europa.eu/info/law/better-regulation/brpapi/"
            f"groupInitiatives/{initiative_id}"
        )

        r = get_with_retry(
            session,
            api_url + "?language=EN",
            timeout=45,
        )

        try:
            data = r.json()
        except ValueError as exc:
            raise CollectorError(
                f"Commission BRP API returned invalid JSON for initiative {initiative_id}: {exc}"
            )

        short_title = data.get("shortTitle")
        if short_title:
            candidate.title = " ".join(str(short_title).split())

        parts = []

        if data.get("reference"):
            parts.append(f"Reference: {data['reference']}")

        if data.get("unit"):
            parts.append(f"Unit: {data['unit']}")

        if data.get("shortTitle"):
            parts.append(f"Initiative: {data['shortTitle']}")

        if data.get("dossierSummary"):
            parts.append(f"Summary: {data['dossierSummary']}")

        publications = data.get("publications") or []

        for publication in publications:
            p = []

            for key, label in (
                ("id", "Publication ID"),
                ("type", "Type"),
                ("stage", "Stage"),
                ("title", "Title"),
                ("publishedDate", "Published"),
                ("modifiedDate", "Modified"),
                ("adoptionDate", "Adoption date"),
                ("endDate", "End date"),
                ("initiativeStatus", "Initiative status"),
                ("receivingFeedbackStatus", "Feedback status"),
                ("feedbackPeriod", "Feedback period"),
                ("consultationObjective", "Consultation objective"),
                ("targetGroups", "Target groups"),
            ):
                value = publication.get(key)
                if value not in (None, "", [], {}):
                    p.append(f"{label}: {value}")

            attachments = publication.get("attachments") or []
            for attachment in attachments:
                bits = ["Attachment"]
                for key, label in (
                    ("title", "title"),
                    ("language", "language"),
                    ("type", "type"),
                    ("reference", "reference"),
                    ("documentId", "documentId"),
                    ("modifiedDate", "modified"),
                ):
                    value = attachment.get(key)
                    if value not in (None, ""):
                        bits.append(f"{label}={value}")
                p.append("; ".join(bits))

            if p:
                parts.append("\n".join(p))

        text = "\n\n".join(parts).strip()[:60000]

    else:
        # Historical Commission Energy consultation pages.
        r = get_with_retry(session, candidate.url, timeout=45)
        content_type = (r.headers.get("content-type") or "").lower()

        if "pdf" in content_type or candidate.url.lower().endswith(".pdf"):
            text = extract_pdf_text(r.content)
        else:
            soup = BeautifulSoup(r.text, "html.parser")

            page_text = soup.get_text(" ", strip=True)

            h1 = soup.find("h1")
            if h1:
                candidate.title = " ".join(h1.get_text(" ", strip=True).split())

            opening = re.search(
                r"\bOpening date\s+(\d{1,2})\s+"
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
                r"(20\d{2})\b",
                page_text,
                re.I,
            )
            if opening:
                candidate.publication_date = normalise_commission_date(
                    opening.group(1),
                    opening.group(2),
                    opening.group(3),
                )

            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            text = "\n".join(
                line.strip()
                for line in soup.get_text("\n").splitlines()
                if line.strip()
            )
            text = text[:60000]

    if len(text) < 200:
        raise CollectorError(f"Too little source text extracted from {candidate.url}")

    return text
