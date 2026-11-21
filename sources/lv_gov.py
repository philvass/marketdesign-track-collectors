"""Latvian Ministry of Climate and Energy (Klimata un enerģētikas ministrija, KEM).

Discovery: the server-rendered news listing on kem.gov.lv, first two pages, in
Latvian because the English edition translates only a selection. Each card
carries the date and a lead. robots.txt allows the listing and the articles
(it closes admin, search and the print-to-PDF paths).

Latvian electricity law is announced here: amendments to the Electricity
Market Law and the Energy Law, the rules on renewable support, network
development, storage, capacity and security of supply. The ministry also
covers climate, environment and support programmes, and it tags its news too
unevenly for the site's own "Elektroenerģija" filter to be trusted, so a
title-and-lead keyword filter keeps the electricity items.

Not read: the legislation portal (tapportals.mk.gov.lv), a separate
government system where the draft texts themselves are consulted.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (QuietRun, Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Latvian Ministry of Climate and Energy (KEM)"
DOCUMENT_TYPE = "GOVERNMENT"
# Ministries announce consultations days after the texts are dated.
MAX_AGE_DAYS = 7

BASE = "https://www.kem.gov.lv"
LISTING = f"{BASE}/lv/jaunumi"
PAGES = 2
MAX_ITEMS = 20

_ITEM = re.compile(r"/lv/jaunums/([^/?#]+)")
# Title words that mark an electricity item on their own.
_ELECTRICITY = re.compile(
    r"elektroenerģ|elektrotīkl|elektrostacij|elektroapgād|pārvades|sadales tīkl|Sadales tīkls|\bAST\b|"
    r"Augstsprieguma|atjaunīg\w* energ|atjaunojam\w* energ|vēja park|vēja energ|saules park|"
    r"enerģētikas likum|enerģētikas ministru|energoapgād|enerģētisk\w* droš|enerģētisk\w* krīz|"
    r"uzkrātuv|akumulāc|jaudas|balansēšan|izcelsmes apliecinājum|\bOIK\b|obligātā iepirkum|"
    r"neto uzskait|neto norēķin|tīkla tarif|energokopien|kodolenerģ|starpsavienojum", re.I)
# The lead mentions energy in passing far more often, so there the test is narrower.
_LEAD = re.compile(
    r"elektroenerģijas tirgu|Elektroenerģijas tirgus likum|pārvades sistēm|sadales sistēm|"
    r"elektroenerģijas ražo|elektroenerģijas cen", re.I)


def discover(session):
    found: dict[str, Candidate] = {}
    rows_seen = 0
    for page in range(PAGES):
        url = LISTING if page == 0 else f"{LISTING}?page={page}"
        try:
            r = get_with_retry(session, url, timeout=45)
        except CollectorError:
            if page == 0:
                raise
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select(".views-row"):
            a = row.select_one("h2 a[href]")
            m = _ITEM.search(a["href"]) if a else None
            if not m:
                continue
            rows_seen += 1
            title = " ".join(a.get_text(" ", strip=True).split())
            lead_el = row.select_one(".text")
            lead = " ".join(lead_el.get_text(" ", strip=True).split()) if lead_el else ""
            if not (_ELECTRICITY.search(title) or _LEAD.search(lead)):
                continue
            stamp = row.select_one("time[datetime]")
            day = (stamp["datetime"][:10] if stamp else "")
            sid = f"lv-gov-{slugify(m.group(1))}"
            found.setdefault(sid, Candidate(
                sid, title, day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
                urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not rows_seen:
        raise CollectorError("KEM news listing showed no article cards: markup changed")
    # Two pages of ministry news with nothing on electricity is a quiet spell.
    if not found:
        raise QuietRun("No electricity item on the KEM news pages this run")
    return LISTING, list(found.values())[:MAX_ITEMS]


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("article") or soup.select_one("main") or soup.select_one("#main-content") or soup
    text = html_to_text(body)
    if len(text.strip()) < 200:
        raise CollectorError(f"KEM page yielded too little text: {candidate.url}")
    return f"{candidate.title}\n\n{text}"[:MAX_CONTENT_CHARS]


# Small administration, one press channel: keep only titles that name a
# market-design instrument. See sources/gov_common.py for the test and why.
from sources.gov_common import market_design_only  # noqa: E402

discover = market_design_only(discover, INSTITUTION)
