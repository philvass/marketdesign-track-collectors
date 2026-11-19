"""ADMIE / IPTO — the Independent Power Transmission Operator, the Greek TSO.

Discovery: two server-rendered listings on admie.gr, which robots.txt allows:

1. Διαβουλεύσεις, the operator's public consultations. These are the working
   texts of the Greek balancing market: the "technical decisions" on
   integrated scheduling, dispatch instructions, prequalification of
   balancing service providers and automatic reserve activation, the ten-year
   network development plan, and joint consultations with neighbouring TSOs
   on cross-border capacity rules. Each entry has its posting date.
2. Δελτία Τύπου, the press releases, for interconnector milestones and
   statements on system operation.

The Greek site is read; the English one carries fewer consultations.

Not read: the "Ενημερώσεις" and urgent-notice lists, which are operational
(unit maintenance schedules, interconnector capacity availability), and the
procurement notices. Corporate press releases (training academy, memoranda,
appointments, results, sponsorship) are dropped by title.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ADMIE (IPTO)"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.admie.gr"
LISTS = (("consultation", f"{BASE}/anakoinoseis/diaboyleyseis", "/anakoinoseis/diaboyleyseis/"),
         ("press", f"{BASE}/kentro-typoy/deltia-typoy", "/kentro-typoy/deltia-typoy/"))
PER_LIST = 12

_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
# Matched against the title with accents removed and lower-cased.
_CORPORATE = re.compile(
    r"εκπαιδευτικ|ακαδημ|academy|μνημονι|αντιπροεδρος|εξελεγη|οικονομικα αποτελεσματα|"
    r"αποτελεσματα (εξαμηνου|εννεαμηνου|τριμηνου|χρησης)|χορηγ|βραβε|εθελοντ|ομολογ|"
    r"γενικη συνελευση|εταιρικ\w+ υπευθυνοτητ|skills")


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    for kind, url, prefix in LISTS:
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError as exc:
            errors.append(f"{kind}: {exc}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for a in soup.select(f'.views-field-title a[href*="{prefix}"]'):
            slug = a["href"].split(prefix, 1)[1].strip("/")
            title = " ".join(a.get_text(" ", strip=True).split())
            if not slug or not title:
                continue
            if kind == "press" and _CORPORATE.search(_norm(title)):
                continue
            cell = a.find_parent(class_="views-col") or a.find_parent(class_="views-row")
            pub = None
            if cell is not None:
                stamp = cell.select_one("time[datetime]")
                posted = cell.select_one(".views-field-field-imerominia-anartisis .field-content")
                if stamp and re.match(r"\d{4}-\d{2}-\d{2}", stamp["datetime"]):
                    pub = stamp["datetime"][:10]
                elif posted:
                    d = _DATE.search(posted.get_text(" ", strip=True))
                    pub = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None
            sid = f"admie-{kind}-{slugify(slug)}"
            found.setdefault(sid, Candidate(sid, title, pub, urljoin(BASE, a["href"])))
            n += 1
            if n >= PER_LIST:
                break
        if not n:
            errors.append(f"{kind}: no entries")
    if not found:
        raise CollectorError("ADMIE listings yielded nothing: markup changed. " + " | ".join(errors)[:300])
    return " + ".join(u for _, u, _ in LISTS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one("article") or soup.select_one(".region-content")
    if body is None:
        raise CollectorError(f"ADMIE page body not found: {candidate.url}")
    text = f"{candidate.title}\n\n{html_to_text(body)}"
    if len(text) < 200:
        raise CollectorError(f"ADMIE page yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
