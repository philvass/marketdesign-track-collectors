"""DESNZ — the UK Department for Energy Security and Net Zero.

Discovery: GOV.UK's public search API, filtered to the department and to the
document types in which policy is made: consultations and their outcomes,
calls for evidence, policy papers, statutory guidance, notices, written
statements and press releases. GOV.UK publishes this API for reuse and its
robots.txt leaves /api open.

The department writes the rules that Ofgem, NESO and LCCC then administer: the
Contracts for Difference and Capacity Market regulations, the Renewables
Obligation, the review of electricity market arrangements, network and
connections policy, licensing of flexibility providers. It also publishes on
heat, oil and gas, nuclear decommissioning, climate diplomacy and household
schemes, so a filter on the title and the official summary keeps the
electricity items only. Statistics, privacy notices, lists of grant winners
and individual planning consents are dropped.

Content: the Content API record for the page (summary, body, the outcome of a
consultation, the list of attachments), followed by the text of the first PDF
attachment, which for a consultation is the consultation document itself.
The date is GOV.UK's public timestamp, which moves when a page is
substantively updated, for instance when a consultation gets its response.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, extract_pdf_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Department for Energy Security and Net Zero (DESNZ)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://www.gov.uk"
_TYPES = ("open_consultation", "closed_consultation", "consultation_outcome",
          "open_call_for_evidence", "closed_call_for_evidence", "call_for_evidence_outcome",
          "policy_paper", "statutory_guidance", "guidance", "notice", "regulation",
          "written_statement", "press_release", "news_story", "impact_assessment")
SEARCH = (f"{BASE}/api/search.json?filter_organisations=department-for-energy-security-and-net-zero"
          + "".join(f"&filter_content_store_document_type={t}" for t in _TYPES)
          + "&order=-public_timestamp&count=100"
            "&fields=title,link,public_timestamp,description,content_store_document_type")
MAX_ITEMS = 25

_ELECTRICITY = re.compile(
    r"electricit|capacity market|contracts? for difference|\bCfDs?\b|wholesale|balancing|"
    r"\bREMA\b|market arrangements|renewables obligation|\bRO schemes?\b|feed-in tariff|"
    r"network charg|grid connection|network connection|connections reform|transmission|"
    r"interconnector|flexibilit|load control|energy smart|smart secure|half-hourly|"
    r"long duration|energy storage|\bNESO\b|system operator|supplier obligation|"
    r"energy code|licence exemption|licence condition|energy independence bill|"
    r"great british (grid|energy)|power cable|energy bills|standing charge", re.I)
_NOISE = re.compile(
    r"privacy notice|successful projects|development consent|S3[67] consent|overhead line|"
    r"condition discharge|jobs fair|statistics|public attitudes|IPCC|COP\d\d|"
    r"warm home|boiler upgrade|heat network|clean power alliance|heating oil", re.I)

_META: dict[str, dict] = {}


def discover(session):
    r = get_with_retry(session, SEARCH, timeout=45)
    try:
        results = r.json().get("results")
    except ValueError:
        raise UpstreamUnavailable("GOV.UK search API did not return JSON")
    if not results:
        raise CollectorError("GOV.UK search API returned no DESNZ results: query or format changed")

    found: dict[str, Candidate] = {}
    for item in results:
        title = " ".join((item.get("title") or "").split())
        link = item.get("link") or ""
        lead = " ".join((item.get("description") or "").split())
        if not title or not link.startswith("/"):
            continue
        if _NOISE.search(title) or not _ELECTRICITY.search(f"{title} {lead}"):
            continue
        sid = f"desnz-{slugify(link.rstrip('/').split('/')[-1])}"
        _META[sid] = {"path": link, "kind": item.get("content_store_document_type") or ""}
        found.setdefault(sid, Candidate(sid, title, (item.get("public_timestamp") or "")[:10] or None,
                                        BASE + link))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise UpstreamUnavailable("No electricity item among the latest 100 DESNZ publications")
    return SEARCH, list(found.values())


def _text(html: str | None) -> str:
    return html_to_text(BeautifulSoup(html or "", "html.parser")).strip()


def fetch_content(session, candidate: Candidate) -> str:
    meta = _META.get(candidate.source_id) or {}
    path = meta.get("path") or candidate.url.removeprefix(BASE)
    doc = get_with_retry(session, f"{BASE}/api/content{path}", timeout=45).json()
    details = doc.get("details") or {}

    parts = [candidate.title]
    kind = (doc.get("document_type") or meta.get("kind") or "").replace("_", " ")
    if kind:
        parts.append(f"Document type: {kind}")
    for label, key in (("Opened", "opening_date"), ("Closes", "closing_date")):
        if details.get(key):
            parts.append(f"{label}: {str(details[key])[:10]}")
    if doc.get("description"):
        parts.append(doc["description"].strip())
    for key in ("final_outcome_detail", "public_feedback_detail", "body"):
        text = _text(details.get(key)) if isinstance(details.get(key), str) else ""
        if text:
            parts.append(text)

    attachments = [a for a in details.get("attachments") or [] if a.get("title")]
    if attachments:
        parts.append("Attachments:\n" + "\n".join(f"- {a['title']}" for a in attachments))
    pdf = next((a for a in attachments
                if (a.get("content_type") == "application/pdf" or str(a.get("url", "")).lower().endswith(".pdf"))
                and str(a.get("url", "")).startswith("https://assets.publishing.service.gov.uk/")), None)
    if pdf:
        try:
            body = extract_pdf_text(get_with_retry(session, pdf["url"], timeout=90).content).strip()
        except Exception:        # the page record stands on its own if the attachment does not open
            body = ""
        if body:
            parts.append(f"--- {pdf['title']} ---\n{body}")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
