"""CERA (ΡΑΕΚ) — the Cyprus Energy Regulatory Authority.

Discovery: three server-rendered listings on cera.org.cy, in Greek (the
English edition is partial):

1. Αποφάσεις, the authority's numbered decisions, newest first. Most are
   individual licence applications and are dropped by title; what remains are
   approvals of the transmission and market rules, regulatory decisions, the
   market operator's fees and tariff matters. The listing has no dates; each
   decision page states its date ("Ημερομηνία: dd/mm/yyyy"), read at fetch.
2. Ανακοινώσεις, announcements, with dates: regulatory decisions published in
   the gazette, results of consultations.
3. Διαβουλεύσεις, public consultations on draft regulatory decisions. Neither
   the listing nor the page carries a publication date, so it is left empty;
   only the newest few are considered.

Cyprus opened its competitive electricity market in October 2025, so these
texts are the rules of a market still being built. Staff announcements
(resignations, examinations) are dropped.

robots.txt allows every path used here for all agents. It also carries
content signals (search=yes, ai-train=no, use=reference) and forbids named
AI-training crawlers; this collector does not train on the content.
The decisions page embeds the whole archive and weighs about 1 MB, as does
each decision page, so few decisions are fetched per run.
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "CERA (Cyprus Energy Regulatory Authority)"
DOCUMENT_TYPE = "REGULATOR"
# Decision and consultation dates are only on (or absent from) the detail page.
DATE_REFINED_ON_FETCH = True

BASE = "https://www.cera.org.cy"
DECISIONS = f"{BASE}/el-gr/apofasis"
ANNOUNCEMENTS = f"{BASE}/el-gr/anakoinoseis"
CONSULTATIONS = f"{BASE}/el-gr/diavoulefseis"
DECISION_HEAD = 40       # newest decisions considered before the licence filter
MAX_DECISIONS = 8
MAX_ANNOUNCEMENTS = 8
MAX_CONSULTATIONS = 4

_DETAIL = re.compile(r"/el-gr/(apofasis|anakoinoseis|diavoulefseis)/details/([^/?#]+)")
_MONTHS = {"ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4, "μαιου": 5,
           "ιουνιου": 6, "ιουλιου": 7, "αυγουστου": 8, "σεπτεμβριου": 9, "οκτωβριου": 10,
           "νοεμβριου": 11, "δεκεμβριου": 12}
_DATE_WORDS = re.compile(r"(\d{1,2})\s+([α-ω]+)\s+(20\d{2})")
_DATE_DECISION = re.compile(r"Ημερομηνία:?\s*(\d{1,2})/(\d{1,2})/(20\d{2})")
# Matched against titles with accents removed and lower-cased.
_LICENCE = re.compile(r"αιτη(ση|μα)\w* (της |του |των )?(εταιρ|κοινοπραξ|δημου|κ\.|κας|κου)|"
                      r"χορηγηση\w* αδειας|εξαιρεσ\w+ απο (την υποχρεωση|αδεια)|"
                      r"ανακληση\w* (της )?αδειας")
_STAFF = re.compile(r"παραιτηση|γραπτ\w+ εξετασ|εξετασεις για τη θεση|προκηρυξη θεσ|πληρωση θεσ|διορισμ")


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()


def _url(href: str) -> str:
    m = _DETAIL.search(href)
    return f"{BASE}/el-gr/{m.group(1)}/details/{m.group(2)}"


def _page(session, url, errors):
    try:
        return BeautifulSoup(get_with_retry(session, url, timeout=90).text, "html.parser")
    except CollectorError as exc:
        errors.append(str(exc))
        return None


def discover(session):
    found: dict[str, Candidate] = {}
    errors: list[str] = []
    links_seen = 0

    soup = _page(session, ANNOUNCEMENTS, errors)
    n = 0
    for box in (soup.select("div.ListCont") if soup else []):
        a = box.select_one('a[href*="/anakoinoseis/details/"]')
        if a is None:
            continue
        links_seen += 1
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or _STAFF.search(_norm(title)) or n >= MAX_ANNOUNCEMENTS:
            continue
        when = box.select_one(".PubDate")
        d = _DATE_WORDS.search(_norm(when.get_text(" ", strip=True))) if when else None
        month = _MONTHS.get(d.group(2)) if d else None
        pub = f"{d.group(3)}-{month:02d}-{int(d.group(1)):02d}" if month else None
        sid = f"cera-{slugify(_DETAIL.search(a['href']).group(2))}"
        found.setdefault(sid, Candidate(sid, title, pub, _url(a["href"])))
        n += 1

    soup = _page(session, CONSULTATIONS, errors)
    n = 0
    for a in (soup.select('.TTl-link a[href*="/diavoulefseis/details/"]') if soup else []):
        links_seen += 1
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or n >= MAX_CONSULTATIONS:
            continue
        sid = f"cera-{slugify(_DETAIL.search(a['href']).group(2))}"
        if sid not in found:
            found[sid] = Candidate(sid, f"Δημόσια Διαβούλευση ΡΑΕΚ: {title}", None, _url(a["href"]))
            n += 1

    soup = _page(session, DECISIONS, errors)
    n = 0
    for a in (soup.select('li[class^="Article-"] a[href*="/apofasis/details/"]')[:DECISION_HEAD]
              if soup else []):
        links_seen += 1
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or _LICENCE.search(_norm(title)) or n >= MAX_DECISIONS:
            continue
        sid = f"cera-{slugify(_DETAIL.search(a['href']).group(2))}"
        if sid not in found:
            found[sid] = Candidate(sid, f"Απόφαση ΡΑΕΚ {title}", None, _url(a["href"]))
            n += 1

    if not found:
        why = "markup changed" if not links_seen else "every entry was filtered out"
        raise CollectorError(f"CERA listings yielded nothing ({why}). " + " | ".join(errors)[:300])
    return f"{ANNOUNCEMENTS} + {CONSULTATIONS} + {DECISIONS}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=90)
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".ArticleBody")
    if body is None:
        raise CollectorError(f"CERA article body not found: {candidate.url}")
    text = html_to_text(body)
    if not candidate.publication_date:
        m = _DATE_DECISION.search(text[:400])
        if m:
            candidate.publication_date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    text = f"{candidate.title}\n\n{text}"
    if len(text) < 200:
        raise CollectorError(f"CERA article yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
