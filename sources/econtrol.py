"""E-Control — the Austrian regulator for electricity, gas and hydrogen.

Discovery: two server-rendered pages on e-control.at. The site's robots.txt
closes /services, /suche and /home* to every agent; neither page is there.

1. Begutachtungsentwürfe, one long page on which every draft ordinance and
   consultation is a section of its own: the system-charges ordinances, the
   capacity-calculation method, congestion-management remuneration, exemptions
   for ancillary services, the guarantee-of-origin price. Each section is a
   Liferay web-content article with its own numeric id, which is the source id.
   The record carries the section text and the text of its first PDF, the draft
   itself. A section has no publication date; the upload stamp of its first
   document is used where the link carries one, otherwise the date stays empty.
   Sections whose comment period the text says has ended are closed files and
   are not collected, and so are the gas-only ones.
2. Aktuelle Pressemeldungen, the press releases of the running year. The date
   stands in the lead of most entries and at the head of every article, so it
   is completed on fetch.

German only: the English site carries a fraction of this.

Not read: the Verordnungen and Marktregeln pages, which hold the texts in force
rather than changes to them (a new ordinance appears first as a draft and then
as a press release), and the consumer newsletters.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, extract_pdf_text,
                  html_to_text, MAX_CONTENT_CHARS)

INSTITUTION = "E-Control"
DOCUMENT_TYPE = "REGULATOR"
# Press dates are completed from the article, so the freshness gate runs after the fetch.
DATE_REFINED_ON_FETCH = True

BASE = "https://www.e-control.at"
DRAFTS = f"{BASE}/bereich-recht/aktuelle-begutachtungsentwuerfe"
PRESS = f"{BASE}/presse/pressemeldungen"
MAX_DRAFTS = 12
MAX_PRESS = 10

_MONTHS = {"jänner": 1, "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
           "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
_WORD_DATE = re.compile(r"(\d{1,2})\s*\.\s*(" + "|".join(_MONTHS) + r")\s+(20\d{2})", re.I)
_NUM_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
_DEADLINE = re.compile(r"\bbis\s+(?:spätestens\s+)?(?:zum\s+)?(.{0,40})", re.I)
_EXPIRED = re.compile(r"frist\s+ist\s+(?:am\s+.{0,25}\s+)?(?:bereits\s+)?abgelaufen", re.I)
_GAS_ONLY = re.compile(r"\bGas-|\bGMMO|Referenzpreismethode|TAR NC|Wasserstoff-", re.I)
_PRESS_HREF = re.compile(r"/asset_publisher/(\w+)/content/([^?]+)\?p_r_p_assetEntryId=(\d+)")
_OFF_TOPIC = re.compile(r"Spritpreis|Treibstoff|Vorstandsduo|Schlichtungsverfahren", re.I)

_SECTIONS: dict[str, dict] = {}


def _first_date(text: str) -> str | None:
    """The earliest-placed date in the text, written in words or in figures."""
    best = None
    m = _WORD_DATE.search(text)
    if m:
        best = (m.start(), int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    n = _NUM_DATE.search(text)
    if n and (best is None or n.start() < best[0]):
        best = (n.start(), int(n.group(3)), int(n.group(2)), int(n.group(1)))
    if not best:
        return None
    try:
        return date(best[1], best[2], best[3]).isoformat()
    except ValueError:
        return None


def _closed(text: str) -> bool:
    if _EXPIRED.search(text):
        return True
    for m in _DEADLINE.finditer(text):
        day = _first_date(m.group(1))
        if day:
            return day < date.today().isoformat()
    return False


def _drafts(session) -> list[Candidate]:
    r = get_with_retry(session, DRAFTS, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    sections = soup.select("div.journal-content-article[data-analytics-asset-id]")
    if not sections:
        raise CollectorError("E-Control Begutachtungsentwürfe: no content sections, markup changed")
    out = []
    for sec in sections:
        title = " ".join((sec.get("data-analytics-asset-title") or "").split())
        text = html_to_text(sec)
        pdfs = [a["href"] for a in sec.find_all("a", href=True)
                if re.search(r"\.pdf(/|\?|$)|-pdf$", a["href"], re.I)]
        if not title or not pdfs or _GAS_ONLY.search(title) or _closed(" ".join(text.split())):
            continue
        sid = f"econtrol-entwurf-{sec['data-analytics-asset-id']}"
        stamp = re.search(r"[?&]t=(\d{13})\b", pdfs[0])
        day = (datetime.fromtimestamp(int(stamp.group(1)) / 1000, tz=timezone.utc).date().isoformat()
               if stamp else None)
        _SECTIONS[sid] = {"text": text, "pdf": urljoin(BASE, pdfs[0])}
        out.append(Candidate(sid, title, day, f"{DRAFTS}#{sec['data-analytics-asset-id']}"))
        if len(out) >= MAX_DRAFTS:
            break
    return out


def _press(session) -> list[Candidate]:
    r = get_with_retry(session, PRESS, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    links = soup.find_all("a", href=_PRESS_HREF)
    if not links:
        raise CollectorError("E-Control Pressemeldungen: no release links, markup changed")
    found: dict[str, Candidate] = {}
    for a in links:
        m = _PRESS_HREF.search(a["href"])
        sid = f"econtrol-presse-{m.group(3)}"
        row = a.find_parent("tr")
        head = row.find("h2") if row else None
        title = " ".join((head.get_text(" ", strip=True) if head else a.get("aria-label", "")).split())
        if sid in found or not title or _OFF_TOPIC.search(title):
            continue
        lead = " ".join(row.get_text(" ", strip=True).split()) if row else ""
        stated = re.search(r"\(([^()]{0,30}20\d{2})\)\s*$", lead)
        url = (f"{BASE}/aktuelle-pressemeldungen/-/asset_publisher/{m.group(1)}/content/"
               f"{m.group(2)}?p_r_p_assetEntryId={m.group(3)}")
        found[sid] = Candidate(sid, title, _first_date(stated.group(1)) if stated else None, url)
        if len(found) >= MAX_PRESS:
            break
    return list(found.values())


def discover(session):
    found, errors = [], []
    for name, route in (("Begutachtungsentwürfe", _drafts), ("Pressemeldungen", _press)):
        try:
            found.extend(route(session))
        except CollectorError as exc:
            errors.append(f"{name}: {exc}")
    if not found:
        raise CollectorError("E-Control yielded nothing. " + " | ".join(errors)[:300])
    return f"{DRAFTS} + {PRESS}", found


def fetch_content(session, candidate: Candidate) -> str:
    section = _SECTIONS.get(candidate.source_id)
    if section:
        parts = [section["text"]]
        try:
            r = get_with_retry(session, section["pdf"], timeout=90)
            parts.append(f"--- Entwurf ({section['pdf']}) ---\n" + extract_pdf_text(r.content).strip())
        except Exception as exc:  # the section text alone still describes the consultation
            parts.append(f"(Entwurfsdokument nicht lesbar: {exc})")
        return "\n\n".join(parts)[:MAX_CONTENT_CHARS]

    r = get_with_retry(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    articles = soup.select("div.journal-content-article") or [soup.select_one("#main-content") or soup]
    text = html_to_text(max(articles, key=lambda d: len(d.get_text())))
    if not candidate.publication_date:
        m = re.search(r"\(\s*Wien,([^()]{0,30})\)", text)
        candidate.publication_date = _first_date(m.group(1)) if m else _first_date(text[:1500])
    if len(text) < 300:
        raise CollectorError(f"E-Control release yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
