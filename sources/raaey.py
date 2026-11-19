"""RAAEY (formerly RAE) — the Greek Regulatory Authority for Waste, Energy and
Water. Its energy branch regulates electricity and gas.

Discovery: the WordPress JSON API of the energy site (raaey.gr/energeia),
which robots.txt allows. One request returns the newest posts in three
categories, with their dates and full bodies:

- Αποφάσεις (decisions of the energy branch),
- Διαβουλεύσεις (public consultations and their results),
- Γενικά νέα (announcements).

The licensing sub-categories are excluded in the query: they hold dozens of
individual producer certificates a day, which would bury everything else.
The site is Greek only for these lists.

Decisions are posted under their number alone, with a one-line subject and
the signed PDF. The subject is added to the title, and when the post body is
short the first attached PDF is read for the text. Entries about gas,
hydrogen, CO2 storage or heat only, and the routine licensing tables that
still appear among the announcements, are dropped.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  extract_pdf_text, MAX_CONTENT_CHARS)

INSTITUTION = "RAAEY (Greek Regulatory Authority for Energy)"
DOCUMENT_TYPE = "REGULATOR"

BASE = "https://www.raaey.gr"
API = (f"{BASE}/energeia/wp-json/wp/v2/posts?categories=28,109,20"
       "&categories_exclude=180,181,182&per_page=40&_fields=id,date,link,title,content")
LISTING = f"{BASE}/energeia/"
MAX_ITEMS = 25
SHORT_BODY = 600

# Matched against text with accents removed and lower-cased.
_OTHER_SECTOR = re.compile(
    r"φυσικ\w+ αερι|αεριου|εσφα|δεσφα|\bεδα\b|enaon|υδρογον|βιομεθαν|ccs|co2|θερμικ\w+ ενεργει|"
    r"υδρογονανθρακ|εδευεπ|τηλεθερμανσ|πετρελαιο|διοξειδιου του ανθρακα|διαιτητ")
_POWER = re.compile(r"ηλεκτρ|εσμηε|αδμηε|δεδδηε|εχε\b|απε\b|δαπεεπ|εξισορροπησ|διασυνδε")
_LICENSING = re.compile(
    r"αιτησ\w+ (χορηγησης|αδειας)|πινακας αδειων|κυκλος αιτησεων|βεβαιωσ\w+ παραγωγ|"
    r"προκαταρκτικη διερευνηση|πινακας παυσ")
_BARE = re.compile(r"^(ανακοινωση( της)? ρ\.?α\.?α\.?ε\.?υ\.?|αποφαση .*αριθμ\.? [\w./-]+)\s*$")

_POSTS: dict[str, dict] = {}


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in plain if unicodedata.category(c) != "Mn").lower().replace("’", "'")


def _wanted(text: str) -> bool:
    n = _norm(text)
    if _LICENSING.search(n):
        return False
    return not _OTHER_SECTOR.search(n) or bool(_POWER.search(n))


def discover(session):
    r = get_with_retry(session, API, timeout=60)
    if not r.content.strip():
        raise UpstreamUnavailable("RAAEY API returned an empty response")
    try:
        posts = r.json()
    except ValueError:
        raise UpstreamUnavailable("RAAEY API returned invalid JSON")
    if not isinstance(posts, list) or not posts:
        raise CollectorError("RAAEY API returned no posts: categories or route changed")

    found: dict[str, Candidate] = {}
    for post in posts:
        try:
            pid, link, day = int(post["id"]), post["link"], post["date"][:10]
            title = BeautifulSoup(post["title"]["rendered"], "html.parser").get_text(" ", strip=True)
            body = BeautifulSoup(post["content"]["rendered"], "html.parser")
        except (KeyError, TypeError, ValueError):
            continue
        title = " ".join(title.split())
        text = "\n".join(l.strip() for l in body.get_text("\n").splitlines() if l.strip())
        lead = " ".join(text.split())[:300]
        if not title or not _wanted(f"{title} {lead}"):
            continue
        if _BARE.match(_norm(title)) and lead:
            cut = lead[:160].rsplit(" ", 1)[0] if len(lead) > 160 else lead
            title = f"{title}: {cut}"
        sid = f"raaey-{pid}"
        pdfs = [urljoin(BASE, a["href"]) for a in body.select("a[href]")
                if a["href"].lower().split("?")[0].endswith(".pdf")]
        _POSTS[sid] = {"text": text, "pdfs": pdfs}
        found[sid] = Candidate(sid, title, day if re.match(r"\d{4}-\d{2}-\d{2}$", day) else None, link)
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise UpstreamUnavailable("No electricity item among the newest RAAEY posts this run")
    return LISTING, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    post = _POSTS.get(candidate.source_id)
    if post is None:
        raise CollectorError(f"RAAEY post body missing for {candidate.source_id}")
    parts = [candidate.title, post["text"]]
    if len(post["text"]) < SHORT_BODY and post["pdfs"]:
        # A decision: the post is a one-line subject, the text is in the signed PDF.
        try:
            r = get_with_retry(session, post["pdfs"][0], timeout=90)
            pdf_text = extract_pdf_text(r.content).strip()
            if pdf_text:
                parts.append(f"[Συνημμένο / attachment: {post['pdfs'][0]}]\n{pdf_text}")
        except CollectorError:
            pass
    text = "\n\n".join(p for p in parts if p)
    if len(text) < 200:
        raise CollectorError(f"RAAEY post yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
