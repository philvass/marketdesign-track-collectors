"""Red Eléctrica (REE) — the Spanish transmission system operator.

Discovery: the press room listing on ree.es ("Actualidad"), which is
server-rendered: each card carries the publication date, the headline and the
link to the release. robots.txt allows the press room for every agent; it
forbids the site's feed paths, so no feed is read.

Red Eléctrica operates the Spanish system, so its releases are where changes
to the adjustment services, the reinforced operation that followed the April
2025 blackout, demand response, access and connection capacity, and the
interconnections are announced in plain language. The binding texts (operating
procedures, CNMC resolutions) reach the monitor through the `cnmc` adapter.

Dropped by title before anything is fetched: Redeia group corporate items
(results, board, sponsorship, awards) and restoration-of-supply notices. The
monthly demand bulletin is kept: it is short and sometimes carries the first
statement of a change in operation.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, get_with_retry, html_to_text,
                  slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Red Eléctrica (REE)"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.ree.es"
NEWS = f"{BASE}/es/sala-de-prensa/actualidad"
MAX_ITEMS = 20

_ITEM = re.compile(r"/actualidad/nota-de-prensa[^/]*/(20\d{2})/(\d{2})/([^/?#]+)")
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d{2})")
_DROP = re.compile(
    r"resultados|beneficio|junta general|consejo de administraci|nombra|dividendo|bonos?\b|"
    r"financiar[áa]|patrocin|premio|galard|fundaci[óo]n|voluntariado|exposici[óo]n|"
    r"re(e)?stablecido el suministro|restablece el suministro", re.I)


def discover(session):
    r = get_with_retry(session, NEWS, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    found: dict[str, Candidate] = {}
    for a in soup.select('a[href*="/nota-de-prensa"]'):
        m = _ITEM.search(a.get("href", ""))
        card = a.find_parent(class_="card")
        if not m or card is None:
            continue
        head = card.select_one(".field--name-field-listing-title")
        title = " ".join(head.get_text(" ", strip=True).split()) if head else ""
        if not title or _DROP.search(title):
            continue
        when = card.select_one(".field--name-field-pub-date")
        d = _DATE.search(when.get_text(" ", strip=True)) if when else None
        pub = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else None
        sid = f"ree-{m.group(1)}{m.group(2)}-{slugify(m.group(3))}"
        found.setdefault(sid, Candidate(sid, title, pub, urljoin(BASE, a["href"])))
        if len(found) >= MAX_ITEMS:
            break
    if not found:
        raise CollectorError("Red Eléctrica press room listed no releases: markup changed")
    return NEWS, list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.select_one("article") or soup.select_one("main") or soup
    text = html_to_text(body)
    if len(text) < 200:
        raise CollectorError(f"Red Eléctrica release yielded too little text: {candidate.url}")
    return text[:MAX_CONTENT_CHARS]
