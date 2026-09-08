"""MISO — Midcontinent ISO.

Discovery: the site's sitemap, which lists every news release with a lastmod
date. The listing pages themselves rate-limit aggressively (HTTP 429 after a
handful of requests) and sit behind a Cloudflare challenge, so the sitemap
is both cheaper and more reliable. Titles are derived from the slug and
replaced by the page heading on fetch.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core import Candidate, UpstreamUnavailable, get_with_retry, html_to_text, slugify, MAX_CONTENT_CHARS
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "MISO"
DOCUMENT_TYPE = "ISO"

BASE = "https://www.misoenergy.org"
SITEMAP = f"{BASE}/sitemap.xml"
_ENTRY = re.compile(r"<url>\s*<loc>([^<]*/media-center/\d{4}---news-releases/[^<]+/)</loc>"
                    r"\s*(?:<lastmod>(\d{4}-\d{2}-\d{2})[^<]*</lastmod>)?", re.I)


def _slug_title(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    return " ".join(slug.replace("--", "-").split("-")).strip().capitalize()


def discover(session):
    r = get_with_retry(session, SITEMAP, timeout=60)
    found: dict[str, Candidate] = {}
    for url, lastmod in _ENTRY.findall(r.text):
        sid = f"miso-{slugify(url.rstrip('/').split('/')[-1])}"
        found.setdefault(sid, Candidate(sid, _slug_title(url), lastmod or None, url))
    if not found:
        raise UpstreamUnavailable("MISO sitemap carried no news releases")
    # Newest first so the run limit reaches current releases.
    items = sorted(found.values(), key=lambda c: c.publication_date or "", reverse=True)
    return SITEMAP, items


def is_out_of_scope(candidate: Candidate) -> bool:
    return not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.get_text(" ", strip=True).split())
        if len(title) > 8:
            candidate.title = title
    main = soup.find("main") or soup
    return html_to_text(main)[:MAX_CONTENT_CHARS]
