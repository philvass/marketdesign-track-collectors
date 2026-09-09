"""Texas Register — the official publication for Texas rulemakings.

ERCOT itself cannot be collected: its site refuses every automated request.
But the decisions that change ERCOT's market design are made by the Public
Utility Commission of Texas, and a PUCT rulemaking is not effective until it
is published here. So the Texas Register is to ERCOT what the Federal
Register is to FERC, and it is published in the open by the Secretary of
State with no protection of any kind.

Electricity rules are Title 16 of the Texas Administrative Code (Economic
Regulation), chapter 25. The commission does not file every week, so
discovery reads the last few weekly issues rather than only the current one:
an issue with no utility item is normal, not a failure.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, UpstreamUnavailable, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)
from sources.us_common import REGION  # noqa: F401

INSTITUTION = "Public Utility Commission of Texas"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.sos.state.tx.us"
ARCHIVE = f"{BASE}/texreg/archive/index.shtml"
ISSUES = 6                      # weekly, so about six weeks of cover

_ISSUE = re.compile(r"/archive/([A-Za-z]+\d{1,2}\d{4})/index\.html", re.I)
_ISSUE_DATE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})")
# The commission's own name, and its rules, which are Title 16 chapter 25.
_PUC = re.compile(r"public utility commission", re.I)
_RULE_CITE = re.compile(r"16\s+TAC\s+§+\s*25\.", re.I)
# Electricity sits in Title 16 alongside other economic regulation.
_ECON_SECTION = re.compile(r"16\.ECONOMIC", re.I)


def _issue_date(label: str) -> str | None:
    m = _ISSUE_DATE.search(label or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def discover(session):
    r = get_with_retry(session, ARCHIVE, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")

    issues = []
    for a in soup.select("a[href]"):
        m = _ISSUE.search(a["href"])
        if m:
            issues.append((urljoin(BASE, a["href"]), _issue_date(a.get_text(" ", strip=True)), m.group(1)))
    if not issues:
        raise UpstreamUnavailable("Texas Register archive listed no issues")

    found: dict[str, Candidate] = {}
    for url, published, slug in issues[:ISSUES]:
        try:
            ir = get_with_retry(session, url, timeout=60)
        except Exception:
            continue
        isoup = BeautifulSoup(ir.text, "html.parser")
        anchors = isoup.select("a[href]")
        cites, agency = [], []
        for i, a in enumerate(anchors):
            href = a["href"]
            label = " ".join(a.get_text(" ", strip=True).split())
            if _ECON_SECTION.search(href) and _RULE_CITE.search(label):
                # The index runs agency, then subject, then rule number, so
                # the two entries above a citation name what it is about.
                context = [" ".join(anchors[j].get_text(" ", strip=True).split())
                           for j in range(max(0, i - 2), i)]
                subject = " — ".join(c for c in context if c and not _RULE_CITE.search(c))
                cites.append((label, subject, urljoin(url, href)))
            elif _PUC.search(label):
                agency.append((label, "", urljoin(url, href)))

        # A rule citation says what actually changed; the agency heading is
        # the same page with a vaguer name, so it is only a fallback.
        for label, subject, target in (cites or agency):
            title = f"Texas Register: {subject} ({label})" if subject else f"Texas Register: {label}"
            sid = f"texreg-{slug.lower()}-{slugify(label)[:60]}"
            found.setdefault(sid, Candidate(sid, title, published, target))

    if not found:
        # Six quiet weeks is unusual but not an error: the commission simply
        # did not file. Reporting an outage here would cry wolf.
        raise UpstreamUnavailable(
            f"No Public Utility Commission items in the last {ISSUES} Texas Register issues")
    return ARCHIVE, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    page, _, anchor = candidate.url.partition("#")
    r = get_with_retry(session, page, timeout=90)
    soup = BeautifulSoup(r.text, "html.parser")
    text = html_to_text(soup)

    # A section page holds every agency that filed under that title, so slice
    # to the commission's own part rather than handing the analysis the lot.
    m = _PUC.search(text)
    if m:
        start = max(0, m.start() - 200)
        text = text[start:start + MAX_CONTENT_CHARS]
    return text[:MAX_CONTENT_CHARS]
