"""YPEN — the Greek Ministry of Environment and Energy.

Discovery: the WordPress JSON API of ypen.gov.gr, restricted to the press
release category. One request returns the newest releases with their dates
and full bodies, so nothing else is fetched. robots.txt forbids only PDF
files, and none are requested.

Greek electricity policy is announced through these releases: storage and
renewable support schemes and their auctions, measures on retail electricity
cost, grid connection priority rules, interconnections (Great Sea
Interconnector, the islands), the national energy and climate plan, and the
ministry's positions at the Energy Council. Draft laws themselves are
consulted on opengov.gr, which is not read here.

The ministry also covers spatial planning, forests, waste, water and
hydrocarbons, and much of the press output is ministerial travel. Only
releases whose title or opening lines mention electricity matters pass. The
other categories of the site (procurement notices, environmental permitting
postings, zoning studies) are left out by the category in the query.
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  MAX_CONTENT_CHARS)

INSTITUTION = "YPEN (Greek Ministry of Environment and Energy)"
DOCUMENT_TYPE = "GOVERNMENT"
MAX_AGE_DAYS = 7

BASE = "https://ypen.gov.gr"
PRESS_CATEGORY = 7
API = (f"{BASE}/wp-json/wp/v2/posts?categories={PRESS_CATEGORY}&per_page=40"
       "&_fields=id,date,link,title,excerpt,content")
MAX_ITEMS = 20

# Matched against title and lead with accents removed and lower-cased.
_ELECTRICITY = re.compile(
    r"ηλεκτρικ|ηλεκτρισμ|ηλεκτροπαραγωγ|ρευματος|ρευμα\b|αποθηκευσ|\bαπε\b|ανανεωσιμ|φωτοβολταικ|"
    r"αιολικ|υπερακτι|διασυνδε|δικτυ\w+ (μεταφορας|διανομης)|ηλεκτρικου χωρου|ορων συνδεσης|"
    r"τιμολογι|αγορα\w* ενεργειας|χονδρεμπορικ|εξισορροπησ|μηχανισμ\w+ (ισχυος|επαρκειας)|"
    r"εσεκ|αδμηε|δεδδηε|δαπεεπ|ραα?ευ|ενεργειακ\w+ κοινοτητ|αυτοπαραγωγ|αυτοκαταναλωσ|"
    r"συμβουλιο\w* (υπουργων )?ενεργειας|κοστους ενεργειας|καλωδιο|gsi\b|target model|ppa")
_DROP = re.compile(r"\bcop ?\d+|επιδοτηση καυσιμων|σεισμικ\w+ ερευν|υδρογονανθρακ|navtex")

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
        raise UpstreamUnavailable("YPEN API returned an empty response")
    try:
        posts = r.json()
    except ValueError:
        raise UpstreamUnavailable("YPEN API returned invalid JSON")
    if not isinstance(posts, list) or not posts:
        raise CollectorError("YPEN API returned no posts: category or route changed")

    found: dict[str, Candidate] = {}
    for post in posts:
        try:
            pid, link, day = int(post["id"]), post["link"], post["date"][:10]
            title = " ".join(_text(post["title"]["rendered"]).split())
            lead = " ".join(_text(post["excerpt"]["rendered"]).split())
            body = _text(post["content"]["rendered"])
        except (KeyError, TypeError, ValueError):
            continue
        probe = _norm(f"{title} {lead}")
        if not title or _DROP.search(probe) or not _ELECTRICITY.search(probe):
            continue
        sid = f"gr-gov-{pid}"
        _BODIES[sid] = body
        found[sid] = Candidate(sid, title, day if re.match(r"\d{4}-\d{2}-\d{2}$", day) else None, link)
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise QuietRun("No electricity release among the newest YPEN posts this run")
    return f"{BASE}/category/grafeio-typou/", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    body = _BODIES.get(candidate.source_id) or ""
    text = f"{candidate.title}\n\n{body}"
    if len(body) < 200:
        raise CollectorError(f"YPEN release yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
