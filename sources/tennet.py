"""TenneT (tennet.eu) — Dutch/German TSO.

Discovery: /news carries all news items in its __NEXT_DATA__ JSON, with teaser,
themes and timestamps. Article pages are bot-blocked, so the teaser (plus
title/themes/keywords) is the submitted content — enough for the TRACK
relevance gate and resolver; editors follow the link for the full text.

/news now sits behind a Cloudflare managed challenge (HTTP 403,
cf-mitigated: challenge) that a plain request can no longer clear, so discovery
renders it — the same headless-Chrome path Terna and EEX use — and reads the
__NEXT_DATA__ out of the hydrated DOM.

Why rendering is permitted here, where the Elia adapter refuses it: this is a
robots.txt call, and the two files differ. Elia disallows
CloudflareBrowserRenderingCrawler by name, so rendering is the one thing it
asks us not to do. TenneT's robots.txt names no rendering crawler and, under
`User-agent: *`, disallows only /api/ — /news is allowed. It does name-ban a
long list of AI crawlers (ClaudeBot, GPTBot, PerplexityBot, …); we are none of
them, matching `*`. So rendering /news is within the site's stated policy. If
that policy changes to disallow rendering, this adapter must stop rendering,
exactly as Elia's docstring instructs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, render_html,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "TenneT"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.tennet.eu"
NEWS = f"{BASE}/news"
MAX_ITEMS = 30

_META_CACHE: dict[str, dict] = {}

# Cloudflare's managed challenge clears for a residential browser but flaps on
# shared CI-runner IPs. When it does not clear, the rendered fetch returns the
# ~5KB "Just a moment" interstitial instead of the news page: big enough to pass
# render_html's empty-document guard, but with no __NEXT_DATA__. That is an
# upstream block, not a structural change on our side, so it is reported as
# upstream_unavailable (a soft "backing off", exit 0) rather than a hard error
# that reddens the monitor. A missing payload on a page that is NOT a challenge
# still raises the hard error it should.
_CHALLENGE_MARKERS = re.compile(
    r"just a moment|enable javascript|cf-mitigated|attention required|"
    r"cf-browser-verification|challenge-platform", re.I)


def _looks_challenged(html: str) -> bool:
    return len(html) < 20000 and bool(_CHALLENGE_MARKERS.search(html))


def _epoch_ms_date(raw) -> str | None:
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def discover(session):
    html = render_html(NEWS, timeout=90, virtual_time_ms=12000)
    soup = BeautifulSoup(html, "html.parser")
    script = soup.select_one("script#__NEXT_DATA__")
    if not script or not script.string:
        if _looks_challenged(html):
            raise UpstreamUnavailable(
                "TenneT served a Cloudflare challenge to the rendered fetch "
                "instead of /news. The managed challenge flaps on shared CI IPs; "
                "runs where it clears still collect. Backing off, not a bypass.")
        raise CollectorError("TenneT /news has no __NEXT_DATA__ payload")
    try:
        data = json.loads(script.string)
        edges = data["props"]["pageProps"]["news"]["edges"]
    except (ValueError, KeyError, TypeError) as exc:
        raise CollectorError(f"TenneT __NEXT_DATA__ shape changed: {exc}")

    found: dict[str, Candidate] = {}
    items = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        items.append(node)
    items.sort(key=lambda n: n.get("publishedAt") or 0, reverse=True)

    for node in items[:MAX_ITEMS]:
        path = node.get("path") or ""
        title = " ".join(str(node.get("title") or "").split())
        if not path or not title:
            continue
        url = urljoin(BASE, path)
        slug = path.strip("/").split("/")[-1]
        sid = f"tennet-{slugify(slug)}"
        _META_CACHE[sid] = node
        found.setdefault(sid, Candidate(sid, title, _epoch_ms_date(node.get("publishedAt")), url))

    if not found:
        raise CollectorError("TenneT discovery returned no candidates")
    return NEWS, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    node = _META_CACHE.get(candidate.source_id) or {}
    parts = [candidate.title]
    desc = " ".join(str(node.get("description") or "").split())
    if desc:
        parts.append(desc)
    for key, label in (("newsType", "Type"), ("themes", "Themes"),
                       ("keywords", "Keywords"), ("tags", "Tags")):
        v = node.get(key)
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v if x)
        if v:
            parts.append(f"{label}: {v}")
    updated = _epoch_ms_date(node.get("updatedAt"))
    if updated:
        parts.append(f"Last updated: {updated}")
    parts.append(
        "Note: TenneT article pages are served only to browsers; this record "
        "carries the official teaser. Full text at the source URL."
    )
    text = "\n\n".join(parts)
    if len(text) < 200:
        text = text + "\n" + re.sub(r"\s+", " ", json.dumps(node)[:500])
    return text[:MAX_CONTENT_CHARS]


def is_out_of_scope(candidate: Candidate) -> bool:
    t = candidate.title.lower()
    return any(x in t for x in ("half-year", "annual report", "financial", "appoint", "vacanc", "hydrogen"))
