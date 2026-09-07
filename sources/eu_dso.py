"""EU DSO Entity (eudsoentity.eu) — the EU body of distribution system operators.

Discovery: the WordPress REST posts feed. The Entity co-drafts network codes
with ENTSO-E (the demand response code among them) and publishes positions on
flexibility, tariffs and connection rules, which no TSO or NRA source covers.
"""
from __future__ import annotations

import html as html_mod
from datetime import datetime

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "EU DSO Entity"
DOCUMENT_TYPE = "MARKET_OPERATOR"

BASE = "https://eudsoentity.eu"
POSTS = f"{BASE}/wp-json/wp/v2/posts"

_CONTENT: dict[str, str] = {}


def _date(raw) -> str | None:
    try:
        return datetime.fromisoformat(str(raw).replace(" ", "T")).date().isoformat()
    except (ValueError, AttributeError):
        return None


def discover(session):
    r = get_with_retry(session, POSTS, params={"per_page": 25}, timeout=45)
    if not r.content.strip():
        raise UpstreamUnavailable("EU DSO Entity returned an empty response")
    try:
        posts = r.json()
    except ValueError as exc:
        raise CollectorError(f"EU DSO Entity posts feed returned invalid JSON: {exc}")

    found: dict[str, Candidate] = {}
    for post in posts if isinstance(posts, list) else []:
        pid = post.get("id")
        link = post.get("link") or ""
        raw_title = (post.get("title") or {}).get("rendered") or ""
        title = " ".join(BeautifulSoup(html_mod.unescape(raw_title), "html.parser")
                         .get_text(" ", strip=True).split())
        if pid is None or not link or not title:
            continue
        sid = f"eudso-{pid}"
        _CONTENT[sid] = (post.get("content") or {}).get("rendered") or ""
        found.setdefault(sid, Candidate(sid, title, _date(post.get("date_gmt")), link))

    if not found:
        raise UpstreamUnavailable("EU DSO Entity posts feed returned no items")
    return POSTS, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    raw = _CONTENT.get(candidate.source_id, "")
    if not raw:
        raw = get_with_retry(session, candidate.url, timeout=45).text
    return html_to_text(BeautifulSoup(raw, "html.parser"))[:MAX_CONTENT_CHARS]
