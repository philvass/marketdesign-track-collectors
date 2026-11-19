"""Elering — the Estonian electricity and gas transmission system operator.

Discovery: the content API of the site's own publishing system. elering.ee is
a script-built site whose news list is filled in by the browser from a public,
read-only Prismic repository; the same repository is asked directly here, which
needs no rendering and returns each item whole (title, dates, body). The site
publishes no robots.txt, and the API is the route its own pages use.

Two kinds of document are read, in Estonian because that is the master
edition:

1. Consultations: Elering's public consultations on balancing and reserve
   methodologies, the capacity mechanism, connection terms and the network
   development plan, dated by the day the consultation opens.
2. Articles: news releases and the market commentary blog.

Elering also runs the gas grid, so gas and hydrogen items are dropped by
title, along with corporate news. Not read: the static explainer pages and the
data dashboard.
"""
from __future__ import annotations

import re

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Elering"
DOCUMENT_TYPE = "TSO"

SITE = "https://www.elering.ee"
API = "https://eleringweb.cdn.prismic.io/api/v2"
KINDS = (("consultation", "konsultatsioon", 10), ("article", "artikkel", 15))

_GAS = re.compile(r"gaas|vesinik|LNG|biometaan", re.I)
_POWER = re.compile(r"elekt", re.I)
_CORPORATE = re.compile(
    r"juhatuse|nõukogu liige|nõukogu esimees|majandustulemus|kasum|võlakir|sponsor|stipend|"
    r"toetab|tööle|praktika|aastaaruan|auhin|konkurss", re.I)

_DOCS: dict[str, dict] = {}


def _texts(node, out: list[str]) -> None:
    """Collect the rich-text paragraphs of a Prismic document in reading order."""
    if isinstance(node, dict):
        text = node.get("text")
        if isinstance(text, str) and "spans" in node:
            if text.strip():
                out.append(" ".join(text.split()))
            return
        for value in node.values():
            _texts(value, out)
    elif isinstance(node, list):
        for value in node:
            _texts(value, out)


def _plain(value) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    out: list[str] = []
    _texts(value, out)
    return " ".join(out)


def discover(session):
    r = get_with_retry(session, API, timeout=45)
    try:
        ref = next(x["ref"] for x in r.json()["refs"] if x.get("isMasterRef"))
    except (ValueError, KeyError, StopIteration) as exc:
        raise CollectorError(f"Elering content API gave no master ref: {exc!r}")

    found: dict[str, Candidate] = {}
    for kind, path, limit in KINDS:
        r = get_with_retry(session, f"{API}/documents/search", timeout=45, params={
            "ref": ref, "q": f'[[at(document.type,"{kind}")]]', "lang": "et-ee",
            "orderings": "[document.first_publication_date desc]", "pageSize": limit + 10})
        try:
            results = r.json()["results"]
        except (ValueError, KeyError) as exc:
            raise CollectorError(f"Elering content API returned no result list for {kind}: {exc!r}")
        n = 0
        for doc in results:
            data = doc.get("data") or {}
            uid = doc.get("uid") or ""
            title = _plain(data.get("title"))
            if not uid or not title:
                continue
            if _CORPORATE.search(title) or (_GAS.search(title) and not _POWER.search(title)):
                continue
            # The site moved to this system in September 2026, so the system's own
            # first-publication stamp is the migration day for everything older;
            # the editorial dates are the true ones.
            day = (data.get("start_date") or data.get("published_date")
                   or doc.get("first_publication_date") or "")[:10]
            sid = f"elering-{kind}-{slugify(uid)}"
            label = "Avalik konsultatsioon: " if kind == "consultation" else ""
            _DOCS[sid] = data
            found.setdefault(sid, Candidate(
                sid, f"{label}{title}",
                day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
                f"{SITE}/{path}/{uid}"))
            n += 1
            if n >= limit:
                break
    if not found:
        raise CollectorError("Elering content API listed no consultations or articles: schema changed")
    return f"{API}/documents/search", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    data = _DOCS.get(candidate.source_id)
    if data is None:
        raise UpstreamUnavailable(f"Elering document not in this run's listing: {candidate.source_id}")
    parts = [candidate.title]
    if data.get("start_date") or data.get("end_date"):
        parts.append(f"Konsultatsiooni periood: {data.get('start_date') or '?'} – {data.get('end_date') or '?'}")
    if isinstance(data.get("lead"), str) and data["lead"].strip():
        parts.append(" ".join(data["lead"].split()))
    body: list[str] = []
    _texts(data.get("slices"), body)
    parts.extend(body)
    text = "\n\n".join(parts)
    if len(text) < 200:
        raise CollectorError(f"Elering document yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
