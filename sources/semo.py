"""SEMO and SEMOpx — the market operator of the all-island Single Electricity
Market (balancing market and capacity market) and its day-ahead and intraday
exchange. Both are run jointly by EirGrid and SONI.

Discovery: the three modification registers, which are server-rendered tables
with one row per proposal, newest first:

1. sem-o.com, Balancing Market Modifications: proposals to change the Trading
   and Settlement Code (Mod_NN_YY).
2. sem-o.com, Capacity Market Modifications: proposals to change the Capacity
   Market Code (CMC_NN_YY).
3. semopx.com, Modifications Under Consideration: proposals to change the
   exchange rules and operating procedures (SPX_NN_YY).

Each row gives the proposal's id, title, status, stage, the code sections
affected, the effective date, the date it was raised and its documents. One
record is kept per proposal, dated by the day it was raised; the record's text
is the row plus the proposal document and, once they exist, the final
recommendation report or decision letter. As the status moves and documents
are added the text changes, which the collector notices on its next visit.
robots.txt on both sites allows these pages and the files.

Deliberately not read: market messages (operational notices on pricing,
settlement and invoicing runs), the monthly market reports, auction results,
and the general publications library.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "SEMO / SEMOpx"
DOCUMENT_TYPE = "MARKET_OPERATOR"

REGISTERS = (
    ("Trading and Settlement Code modification",
     "https://www.sem-o.com/rules-and-modifications/balancing-market-modifications"),
    ("Capacity Market Code modification",
     "https://www.sem-o.com/rules-and-modifications/capacity-market-modifications"),
    ("SEMOpx rules modification",
     "https://www.semopx.com/rules-and-monitoring/modifications/modifications-under-consideration"),
)
PER_REGISTER = 8
_OUTCOME = re.compile(r"decision|final recommendation|FRR", re.I)
_PER_DOC_CHARS = 25000

_ROWS: dict[str, dict] = {}


def _cell(row, name: str) -> str:
    td = row.select_one(f"td.views-field-{name}")
    return " ".join(td.get_text(" ", strip=True).split()) if td else ""


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    rows_seen = 0
    for kind, url in REGISTERS:
        try:
            r = get_with_retry(session, url, timeout=90)
        except CollectorError as exc:
            errors.append(f"{kind}: {exc}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for row in soup.select("tr.expandable-row"):
            mod_id = _cell(row, "field-mod-id")
            title_td = row.select_one("td.views-field-title")
            if not mod_id or not title_td:
                continue
            rows_seen += 1
            files = [(urljoin(url, a["href"]), " ".join(a.get_text(" ", strip=True).split()))
                     for a in title_td.select("a.file-link[href]")]
            head = title_td.find("a", attrs={"data-toggle": "collapse"})
            title = " ".join((head.get_text(" ", strip=True) if head else "").split())
            if not title:
                continue
            stamp = row.select_one("td.views-field-created time[datetime]")
            day = stamp["datetime"][:10] if stamp else ""
            sid = f"semo-{slugify(mod_id)}"
            _ROWS[sid] = {
                "kind": kind, "register": url, "files": files,
                "status": _cell(row, "field-mod-status"), "stage": _cell(row, "field-mod-stage"),
                "sections": _cell(row, "field-mod-section-affected"),
                "effective": _cell(row, "field-mod-effective-date"),
                "raised": _cell(row, "created"),
            }
            # The proposal document is the stable address of a modification; the
            # registers have no page per proposal.
            link = files[0][0] if files else f"{url}#{slugify(mod_id)}"
            found.setdefault(sid, Candidate(
                sid, f"{mod_id}: {title} ({kind})",
                day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None, link))
            n += 1
            if n >= PER_REGISTER:
                break
    if not rows_seen:
        raise CollectorError("SEMO modification registers showed no rows. " + " | ".join(errors)[:300])
    return " + ".join(u for _, u in REGISTERS), list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    row = _ROWS.get(candidate.source_id)
    if row is None:
        raise CollectorError(f"SEMO modification not in this run's registers: {candidate.source_id}")
    parts = [
        candidate.title,
        f"Register: {row['register']}",
        f"Status: {row['status'] or 'not stated'} | Stage: {row['stage'] or 'not stated'}",
        f"Sections affected: {row['sections'] or 'not stated'}",
        f"Raised: {row['raised'] or 'not stated'} | Effective date: {row['effective'] or 'not set'}",
        "Documents on the register:\n" + "\n".join(f"- {name} <{u}>" for u, name in row["files"]),
    ]
    pdfs = [(u, name) for u, name in row["files"] if unquote(u).lower().split("?")[0].endswith(".pdf")]
    wanted = pdfs[:1]
    outcome = [f for f in pdfs[1:] if _OUTCOME.search(f[1])]
    if outcome:
        wanted.append(outcome[-1])                   # the latest report or decision letter
    for u, name in wanted:
        try:
            doc = extract_pdf_text(get_with_retry(session, u, timeout=90).content).strip()
        except Exception:                             # one unreadable file must not lose the record
            doc = ""
        if doc:
            parts.append(f"--- {name} ---\n{doc[:_PER_DOC_CHARS]}")
    text = "\n\n".join(parts)
    if len(text) < 200:
        raise CollectorError(f"SEMO modification yielded too little text: {candidate.source_id}")
    return text[:MAX_CONTENT_CHARS]
