"""Public Utility Commission of Texas — the rulemakings that change ERCOT.

ERCOT itself cannot be collected: its site refuses every automated request.
But the decisions that change ERCOT's market design are made by the Public
Utility Commission of Texas, so the commission's rulemakings are the route.

This adapter used to read them from the Texas Register, the Secretary of
State's weekly publication. In late October 2026 the Secretary of State moved
sos.state.tx.us behind AWS WAF, which now answers every request from a CI
runner — robots.txt included — with HTTP 405 and a "Human Verification"
CAPTCHA. A CAPTCHA is an explicit humans-only gate, so it is not rendered
around, solved or routed past, and the Register's replacement portal is a
form-driven application with no listing to read. The source key is still
`texas-register` so the state cache, the workflow matrix and the source-health
history carry on unbroken.

The commission publishes the same decisions itself, earlier and more usefully,
and its robots.txt allows every agent (`User-agent: * / Allow: /`):

1. Proposed Rule Changes: the plain-language summary the commission must post
   when it files a proposal (Tex. Gov. Code 2001.023), one card per project.
2. Recent Rule Changes: every adopted rule with its project number and
   effective date, linking the rule text as adopted.

puc.texas.gov answers only from inside the United States. The CI runners are
there, so it works in the workflow; from a European machine it returns 403,
which is why an earlier test recorded the site as refusing. Run it on CI.

Electricity rules are Title 16 of the Texas Administrative Code, chapter 25.
Water (24), telecoms (26) and procedure (22) share both pages and are dropped.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  slugify, MAX_CONTENT_CHARS)
from sources.us_common import REGION  # noqa: F401

INSTITUTION = "Public Utility Commission of Texas"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.puc.texas.gov"
PROPOSED = f"{BASE}/agency/rulesnlaws/language/"
RECENT = f"{BASE}/agency/rulesnlaws/recent/"
DOCKET = ("https://interchange.puc.texas.gov/search/filings/?UtilityType=A"
          "&ControlNumber={project}&ItemMatch=Equal&DocumentType=ALL&SortOrder=Ascending")

# The recent-changes table keeps two years; only its head can ever be fresh.
MAX_ADOPTED = 12
MAX_RULE_PDFS = 3

_ELECTRIC_RULE = re.compile(r"§+\s*25\.\d")
_OTHER_RULE = re.compile(r"§+\s*2[2-46]\.\d")
_ELECTRIC_WORDS = re.compile(
    r"\bERCOT\b|electric|large load|transmission service|ancillary|"
    r"retail electric|generation resource|energy storage", re.I)
_SPANISH = re.compile(r"\bSpanish summary\s*:", re.I)

_CACHE: dict[str, dict] = {}


def _us_date(raw: str) -> str | None:
    raw = (raw or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _clean(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def _proposed(session) -> list[Candidate]:
    r = get_with_retry(session, PROPOSED, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    heads = soup.select('[id^="PRJ-"]')
    out = []
    for h in heads:
        project = h["id"].split("-", 1)[1].strip()
        heading = _clean(h)
        subject = heading.split("|", 1)[1].strip() if "|" in heading else heading
        body = h.find_parent(class_="card-body") or h.parent
        text = body.get_text("\n", strip=True)
        # The Spanish summary restates the English one; the analysis needs one.
        m = _SPANISH.search(text)
        english = (text[:m.start()] if m else text).strip()
        if not (_ELECTRIC_RULE.search(heading) or
                (_ELECTRIC_WORDS.search(english) and not _OTHER_RULE.search(heading))):
            continue
        sid = f"puct-proposed-{slugify(project)}"
        _CACHE[sid] = {"text": (
            f"Public Utility Commission of Texas — proposed rule change, Project {project}\n"
            f"{subject}\n\n"
            f"Status: proposal for publication, open for comment. Plain-language summary "
            f"published by the commission under Tex. Gov. Code 2001.023.\n"
            f"Docket: {DOCKET.format(project=project)}\n\n{english}")}
        # The page carries no dates. An undated candidate is never over-age, so
        # a proposal is reported once, when its card first appears.
        out.append(Candidate(sid, f"PUCT proposed rule, Project {project}: {subject}",
                             None, f"{PROPOSED}#PRJ-{project}"))
    return out


def _adopted(session) -> list[Candidate]:
    r = get_with_retry(session, RECENT, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select("table tbody tr")
    if not rows:
        raise CollectorError("PUCT Recent Rule Changes has no table rows: markup changed")

    # One rulemaking amends several rules on one date; report it as one item.
    projects: dict[tuple[str, str], dict] = {}
    for tr in rows:
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        project, rule, title = _clean(cells[0]), _clean(cells[1]), _clean(cells[2]).rstrip(". ")
        effective = _us_date(_clean(cells[3]))
        if not project or not rule:
            continue
        link = cells[1].find("a", href=True)
        entry = projects.setdefault((project, effective or ""), {
            "project": project, "effective": effective, "rules": []})
        entry["rules"].append((rule, title, urljoin(RECENT, link["href"]) if link else None))

    out = []
    for entry in projects.values():
        electric = [x for x in entry["rules"] if _ELECTRIC_RULE.search(x[0])]
        if not electric:
            continue
        entry["rules"] = electric
        project = entry["project"]
        sid = f"puct-adopted-{slugify(project)}-{entry['effective'] or 'undated'}"
        _CACHE[sid] = entry
        subject = "; ".join(f"{rule} {title}" for rule, title, _ in electric[:3])
        if len(electric) > 3:
            subject += f"; and {len(electric) - 3} more"
        out.append(Candidate(sid, f"PUCT adopted rule, Project {project}: {subject}",
                             entry["effective"], DOCKET.format(project=project)))
        if len(out) >= MAX_ADOPTED:
            break
    return out


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    for name, route in (("proposed", _proposed), ("adopted", _adopted)):
        try:
            for c in route(session):
                found.setdefault(c.source_id, c)
        except CollectorError as exc:
            errors.append(f"{name}: {exc}")
    if not found:
        # The adopted table always holds chapter 25 rows, so nothing at all
        # means the pages failed or changed, not that the commission was quiet.
        raise CollectorError("PUCT discovery found nothing. " + " | ".join(errors)[:300])
    return f"{PROPOSED} + {RECENT}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    entry = _CACHE.get(candidate.source_id)
    if entry is None:
        raise CollectorError(f"No discovery record for {candidate.source_id}")
    if "text" in entry:
        return entry["text"][:MAX_CONTENT_CHARS]

    rules = entry["rules"]
    parts = [
        f"Public Utility Commission of Texas — adopted rule change, Project {entry['project']}",
        f"Effective / reviewed date: {entry['effective'] or 'not stated'}",
        "Rules adopted or amended in this project (16 Texas Administrative Code, chapter 25, "
        "the commission's substantive rules for electric service providers):",
        "\n".join(f"- {rule} {title}" for rule, title, _ in rules),
        f"Docket: {DOCKET.format(project=entry['project'])}",
        "The text below is each rule as it now stands after adoption.",
    ]
    budget = (MAX_CONTENT_CHARS - 1500) // min(len(rules), MAX_RULE_PDFS)
    for rule, title, url in rules[:MAX_RULE_PDFS]:
        if not url:
            continue
        try:
            pdf = get_with_retry(session, url, timeout=90)
            text = extract_pdf_text(pdf.content, max_chars=budget).strip()
        except Exception:
            continue                # the header alone still reports the adoption
        if text:
            parts.append(f"===== {rule} {title} =====\n{text[:budget]}")
    return "\n\n".join(parts)[:MAX_CONTENT_CHARS]
