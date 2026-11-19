"""ElCom — the Swiss Federal Electricity Commission, the national regulator.

Discovery: two server-rendered document lists on elcom.admin.ch, whose
robots.txt allows every agent:

1. Mitteilungen, the commission's communications: positions and
   recommendations on market rules (unbundling, the price limit for control
   reserves, the treatment of imbalance costs).
2. Weisungen, its directives: binding instructions to market participants and
   network operators, numbered by year.

Each entry is a PDF with its title and publication date in the link itself.
The German pages are read because they are the complete ones; the English
site carries a subset.

Not read: the Verfügungen page. It lists every individual ruling since 2008,
several thousand tariff and cost disputes between named parties, which is case
law rather than market design. ElCom's media releases appear on the federal
news service, which the `bfe` adapter reads.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ElCom"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.elcom.admin.ch"
LISTS = (("Mitteilung", f"{BASE}/de/mitteilungen"),
         ("Weisung", f"{BASE}/de/weisungen"))
# Both lists run newest first and go back years; only the head can be fresh.
PER_LIST = 12

_MONTHS = {"januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
           "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
_DATE = re.compile(r"(\d{1,2})\.\s*([A-Za-zäÄ]+)\s+(20\d{2})\s*$")
_LABEL = re.compile(r"^Download\s+(.*?)\.\s*PDF,\s*[\d.,]+\s*[kM]B,\s*(.+)$", re.S)
_DAM_ID = re.compile(r"/dam/[a-z]{2}/sd-web/([^/]+)/")


def _date(raw: str) -> str | None:
    m = _DATE.search((raw or "").strip())
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower())
    return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}" if month else None


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    for kind, url in LISTS:
        try:
            r = get_with_retry(session, url, timeout=60)
        except CollectorError as exc:
            errors.append(f"{kind}: {exc}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for a in soup.select("a.download-item[href]"):
            href = a["href"]
            idm = _DAM_ID.search(href)
            lab = _LABEL.match(" ".join((a.get("aria-label") or "").split()))
            if not idm or not lab or ".pdf" not in unquote(href).lower():
                continue
            title = lab.group(1).strip()
            sid = f"elcom-{slugify(idm.group(1))}"
            if sid in found:
                continue
            found[sid] = Candidate(sid, f"ElCom {kind}: {title}", _date(lab.group(2)), href)
            n += 1
            if n >= PER_LIST:
                break
    if not found:
        raise CollectorError("ElCom lists yielded no documents. " + " | ".join(errors)[:300])
    return " + ".join(u for _, u in LISTS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=90)
    text = extract_pdf_text(r.content).strip()
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]
