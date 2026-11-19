"""HOPS — the Croatian transmission system operator.

Discovery: two server-rendered lists on hops.hr, each entry with a date and a
headline. The site publishes no robots.txt (the path answers 404), so nothing
is forbidden; only the first page of each list is read.

1. Obavijesti, notices to market participants: bidding rules for aFRR and
   mFRR reserves, public consultations on those rules, long-term capacity
   calculation and flow-based go-lives, the balancing platform.
2. Vijesti, the company news: amendments to the balancing rules, Core
   capacity-calculation milestones, the ten-year network development plan.

Croatian is read because the English edition omits most notices. Scholarships,
workshops, records, construction contracts and the recurring invitations to
tender for network losses are dropped by title.

Not read: the "Radovi na prijenosnoj mreži" page of planned outages.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "HOPS"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.hops.hr"
LISTS = (f"{BASE}/obavijesti", f"{BASE}/vijesti")
MAX_ITEMS = 20

_ITEM = re.compile(r"^/(obavijesti|vijesti)/([^/?#]+)$")
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_DROP = re.compile(
    r"stipendij|radionic|rekordno|ptica|potpisali ugovor|natječaj\w* za (?:dodjelu|radno)|"
    r"gubitaka u prijenosnoj|godišnje izvješće|financijsk|skupštin|nadzorn\w+ odbor|"
    r"donacij|sponzor|konferencij|čestit|obilježen|radovi na", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    entries = 0
    for url in LISTS:
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError as exc:
            errors.append(str(exc))
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".news--page__item"):
            head = item.find("h5")
            a = head.find_parent("a", href=True) if head else None
            m = _ITEM.match(a["href"]) if a else None
            if not m:
                continue
            entries += 1
            title = " ".join(head.get_text(" ", strip=True).split())
            if not title or _DROP.search(title):
                continue
            when = item.select_one(".news--page__date")
            d = _DATE.search(when.get_text() if when else "")
            # Slugs run past 120 characters and near-duplicates differ only at
            # the end, so the id keeps a digest of the whole path.
            digest = hashlib.sha1(a["href"].encode()).hexdigest()[:8]
            sid = f"hops-{m.group(1)}-{slugify(m.group(2), 50)}-{digest}"
            found.setdefault(sid, Candidate(
                sid, title,
                f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None,
                urljoin(BASE, a["href"])))
    if not entries:
        raise CollectorError("HOPS lists yielded no entries: markup changed. "
                             + " | ".join(errors)[:300])
    if not found:
        raise CollectorError("HOPS: every entry was filtered out; check the title filter")
    items = sorted(found.values(), key=lambda c: c.publication_date or "", reverse=True)
    return " + ".join(LISTS), items[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("main .styled-text") or soup.select_one("main")
    if body is None:
        raise CollectorError(f"HOPS page has no body: {candidate.url}")
    text = f"{candidate.title}\n\n{html_to_text(body)}"
    if len(text) < 200:
        raise CollectorError(f"HOPS page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
