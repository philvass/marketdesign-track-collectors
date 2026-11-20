"""TSOC (ΔΣΜΚ) — the Transmission System Operator of Cyprus, which is also
the island's electricity market operator.

Discovery: the WordPress JSON API of tsoc.org.cy. One request returns the
newest posts with their dates and full bodies, so nothing else is fetched.
The site publishes no robots.txt (the path answers 404), so no path is
restricted. The posts are in Greek; the English site is not kept up to date.

Cyprus started its competitive electricity market in October 2025 and TSOC
writes its rules: consultations on the Market Rules and their manuals, new
versions of the Transmission Rules, the end of transitional arrangements,
portfolio and settlement rules, and statements on system adequacy and load
shedding on an isolated system.

Dropped by title: tenders, vacancies and examination results, short service
notices to participants (invoices, access interruptions, postings of
historical results), and corporate items (branding, ceremonies).
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  MAX_CONTENT_CHARS)

INSTITUTION = "TSOC (Transmission System Operator Cyprus)"
DOCUMENT_TYPE = "TSO"

BASE = "https://tsoc.org.cy"
API = f"{BASE}/wp-json/wp/v2/posts?per_page=40&_fields=id,date,link,title,content"
LISTING = f"{BASE}/category/announcements/"
MAX_ITEMS = 20

# Matched against the title with accents removed and lower-cased.
_DROP = re.compile(
    r"διαγωνισμ|κεν\w+ θεσ|εξετασ|προκηρυξ|εξεταστεας υλης|τιμολογιων|διακοπη προσβασης|"
    r"οπτικη ταυτοτητα|τελετη|παρουσιαση διευθυντη|αναρτηση ιστορικων|αργι|ωρες λειτουργιας")

_BODIES: dict[str, str] = {}


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()


def _text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return "\n".join(l.strip() for l in soup.get_text("\n").splitlines() if l.strip())


def discover(session):
    r = get_with_retry(session, API, timeout=60)
    if not r.content.strip():
        raise UpstreamUnavailable("TSOC API returned an empty response")
    try:
        posts = r.json()
    except ValueError:
        raise UpstreamUnavailable("TSOC API returned invalid JSON")
    if not isinstance(posts, list) or not posts:
        raise CollectorError("TSOC API returned no posts: route changed")

    found: dict[str, Candidate] = {}
    for post in posts:
        try:
            pid, link, day = int(post["id"]), post["link"], post["date"][:10]
            title = " ".join(_text(post["title"]["rendered"]).split())
            body = _text(post["content"]["rendered"])
        except (KeyError, TypeError, ValueError):
            continue
        if not title or _DROP.search(_norm(title)):
            continue
        text = f"{title}\n\n{body}"
        if len(text) < 200:          # a headline with a download link and nothing to read
            continue
        sid = f"tsoc-{pid}"
        _BODIES[sid] = text
        found[sid] = Candidate(sid, title, day if re.match(r"\d{4}-\d{2}-\d{2}$", day) else None, link)
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise QuietRun("No system or market announcement among the newest TSOC posts")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    text = _BODIES.get(candidate.source_id)
    if not text:
        raise CollectorError(f"TSOC post body missing for {candidate.source_id}")
    return text[:MAX_CONTENT_CHARS]
