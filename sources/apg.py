"""Austrian Power Grid (APG) — the Austrian transmission system operator.

Discovery: two lists, both filled by the site's own JSON endpoints. Each list
page names two addresses in its markup, one returning the item ids newest
first and one returning the teaser (link, date, title) for the ids asked for;
the addresses carry a signature, so they are read from the page on every run
rather than written down here. robots.txt on both hosts closes only /typo3/.

1. Marktnews on markt.apg.at: notices to market participants about market
   coupling go-lives, capacity auctions, balancing and reserve procurement.
   Everything on it is collected.
2. News & Presse on www.apg.at: the press releases, most of which are about
   substations, lines and monthly statistics. Only those whose title speaks of
   the market, tariffs, reserves, redispatch or legislation are kept.

Some Marktnews entries are a headline and a link to JAO or ENTSO-E and nothing
else; the record then says so rather than pretending there is a body.

German pages: the English edition of the press list is a subset, and Marktnews
is a single list in which entries stand in whichever language they were written.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Austrian Power Grid (APG)"
DOCUMENT_TYPE = "TSO"

MARKET = ("https://markt.apg.at", "/marktnews/", 15)
PRESS = ("https://www.apg.at", "/news-presse/", 18)

_MONTHS = {"jänner": 1, "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
           "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
_NUM_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
_WORD_DATE = re.compile(r"(\d{1,2})\.\s*(" + "|".join(_MONTHS) + r")\s+(20\d{2})", re.I)
_MARKET_TOPIC = re.compile(
    r"Strommarkt|Stromhandel|Markt(?:kopplung|design|modell|integration)|Regelreserve|Regelenergie|"
    r"Netzreserve|Redispatch|Engpass|Kapazitätsberechnung|Berechnungsmethode|Netzentgelt|Netztarif|"
    r"Intraday|Day[- ]Ahead|Ausgleichsenergie|Flexibilit|ElWG|Elektrizitätswirtschaftsgesetz|"
    r"Gebotszone|Preiszone|Netzentwicklungsplan|Versorgungssicherheit|Auktion|PICASSO|MARI\b", re.I)
_CORPORATE = re.compile(
    r"Vorstand|Aufsichtsrat|Geschäftsbericht|Bilanz|Jahresergebnis|Lehrling|Sponsor|Auszeichnung|"
    r"Straßensperre|Infomesse|Spatenstich", re.I)


def _date(text: str) -> str | None:
    m = _NUM_DATE.search(text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = _WORD_DATE.search(text)
    if m:
        return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


def _list(session, base: str, path: str, limit: int, keep) -> list[Candidate]:
    page = get_with_retry(session, base + path, timeout=45).text
    ids_url = re.search(r'get-items-url="([^"]+)"', page)
    content_url = re.search(r'get-items-content-url="([^"]+)"', page)
    if not ids_url or not content_url:
        raise CollectorError(f"APG {path}: list addresses not in the page, markup changed")
    try:
        ids = get_with_retry(session, base + html.unescape(ids_url.group(1)), timeout=45).json()
        uids = [str(i["uid"]) for i in ids[:limit]]
        if not uids:
            raise UpstreamUnavailable(f"APG {path}: the list is empty")
        teasers = get_with_retry(session, base + html.unescape(content_url.group(1)),
                                 params={"uids": ",".join(uids)}, timeout=45).json()
    except (ValueError, KeyError, TypeError) as exc:
        raise CollectorError(f"APG {path}: list endpoint changed shape: {exc}")
    out = []
    for entry in teasers:
        soup = BeautifulSoup(html.unescape(entry.get("content") or ""), "html.parser")
        a = soup.find("a", href=True)
        head = soup.find("h3")
        day = soup.select_one('[class*="teaser-date"]')
        if not a or not head:
            continue
        title = " ".join(head.get_text(" ", strip=True).split())
        slug = a["href"].rstrip("/").split("/")[-1]
        if not title or not slug or not keep(title):
            continue
        out.append(Candidate(f"apg-{slugify(slug, 160)}", title,
                             _date(day.get_text(" ", strip=True)) if day else None,
                             urljoin(base, a["href"])))
    if not out and not teasers:
        raise CollectorError(f"APG {path}: teasers came back empty, markup changed")
    return out


def discover(session):
    found: dict[str, Candidate] = {}
    errors = []
    routes = ((MARKET, lambda t: True),
              (PRESS, lambda t: bool(_MARKET_TOPIC.search(t)) and not _CORPORATE.search(t)))
    for (base, path, limit), keep in routes:
        try:
            for c in _list(session, base, path, limit, keep):
                found.setdefault(c.source_id, c)
        except CollectorError as exc:
            errors.append(str(exc))
    if not found:
        raise CollectorError("APG lists yielded nothing. " + " | ".join(errors)[:300])
    return f"{MARKET[0]}{MARKET[1]} + {PRESS[0]}{PRESS[1]}", list(found.values())


def fetch_content(session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = html_to_text(soup.find("main") or soup)
    if candidate.title not in text:
        text = f"{candidate.title}\n{text}"
    if len(text) < 400:
        text += ("\n\nHinweis: Diese APG-Marktnews besteht nur aus der Überschrift und dem obigen Verweis "
                 "auf die Mitteilung der zuständigen Stelle (meist JAO oder ENTSO-E). "
                 "(Note: this APG market notice consists only of its headline and the link above to the "
                 "announcement of the body in charge.)")
    return text[:MAX_CONTENT_CHARS]
