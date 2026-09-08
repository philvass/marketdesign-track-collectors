"""FERC — US federal regulator of wholesale power markets.

Two listings. News releases and headlines (ferc.gov) announce the orders that
decide market design: capacity market reforms, price formation rules, storage
and DER participation. The site sits behind a Cloudflare challenge that only a
browser clears, so it is read through a rendered fetch. The Federal Register
API adds FERC's rulemakings (final rules and NOPRs), which are the landmark
documents and are served as plain JSON without any protection.

Only titles that name a market-design subject survive discovery; see
us_common. Gas, hydro, pipeline and environmental matters are FERC's larger
docket and are dropped by title.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, render_html, slugify, MAX_CONTENT_CHARS)
from sources.us_common import REGION, title_in_scope  # noqa: F401

INSTITUTION = "FERC"
DOCUMENT_TYPE = "REGULATOR"
NEEDS_BROWSER = True

BASE = "https://www.ferc.gov"
LISTING = f"{BASE}/news-events/news/news-releases-headlines"
FEDREG = ("https://www.federalregister.gov/api/v1/documents.json"
          "?conditions[agencies][]=federal-energy-regulatory-commission"
          "&conditions[type][]=RULE&conditions[type][]=PRORULE"
          "&order=newest&per_page=20"
          "&fields[]=title&fields[]=publication_date&fields[]=type"
          "&fields[]=html_url&fields[]=abstract&fields[]=body_html_url"
          "&fields[]=document_number&fields[]=docket_ids")

_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|"
                   r"October|November|December)\s+(\d{1,2}),\s+(20\d{2})", re.I)


def _date(text: str) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def discover(session):
    found: dict[str, Candidate] = {}
    diagnostics = []

    try:
        soup = BeautifulSoup(render_html(LISTING, timeout=120, virtual_time_ms=15000), "html.parser")
        rows = soup.select("div.views-row")
        if not rows:
            diagnostics.append("news listing rendered without rows")
        for row in rows:
            a = row.select_one("h2 a[href], .content-feed__title a[href]")
            if not a:
                continue
            title = " ".join(a.get_text(" ", strip=True).split())
            date_el = row.select_one(".content-feed__date")
            url = urljoin(BASE, a["href"])
            sid = f"ferc-{slugify(url.rstrip('/').split('/')[-1])}"
            found.setdefault(sid, Candidate(sid, title, _date(date_el.get_text() if date_el else ""), url))
    except UpstreamUnavailable as exc:
        diagnostics.append(f"news listing: {exc}")

    try:
        r = get_with_retry(session, FEDREG, timeout=60)
        for item in (r.json().get("results") or []):
            title = " ".join(str(item.get("title") or "").split())
            url = item.get("html_url")
            if not title or not url:
                continue
            kind = "Final rule" if item.get("type") == "Rule" else "Proposed rule"
            sid = f"ferc-fr-{slugify(item.get('document_number') or url.rstrip('/').split('/')[-1])}"
            found.setdefault(sid, Candidate(sid, f"{kind}: {title}", item.get("publication_date"), url))
    except (CollectorError, ValueError) as exc:
        diagnostics.append(f"federal register: {exc}")

    if not found:
        raise UpstreamUnavailable("FERC discovery returned no candidates: " + "; ".join(diagnostics))
    return f"{LISTING} + Federal Register", list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    return not title_in_scope(candidate.title)


def fetch_content(session, candidate: Candidate) -> str:
    if "federalregister.gov" in candidate.url:
        # The API's body_html_url is the full text; the document page itself is
        # a shell. Re-read the record for the body link and abstract.
        num = candidate.source_id.replace("ferc-fr-", "")
        r = get_with_retry(session, f"https://www.federalregister.gov/api/v1/documents/{num}.json", timeout=60)
        item = r.json()
        parts = [item.get("abstract") or ""]
        body_url = item.get("body_html_url")
        if body_url:
            try:
                br = get_with_retry(session, body_url, timeout=90)
                parts.append(html_to_text(BeautifulSoup(br.text, "html.parser")))
            except CollectorError:
                pass
        text = "\n\n".join(p for p in parts if p)
        return text[:MAX_CONTENT_CHARS]

    soup = BeautifulSoup(render_html(candidate.url, timeout=120, virtual_time_ms=12000), "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.get_text(" ", strip=True).split())
        if len(title) > 8:
            candidate.title = title
    main = soup.find("main") or soup.find("article") or soup
    text = html_to_text(main)
    if not candidate.publication_date:
        candidate.publication_date = _date(text[:3000])
    return text[:MAX_CONTENT_CHARS]
