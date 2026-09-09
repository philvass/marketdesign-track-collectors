"""Elia — Belgian TSO.

Elia's robots.txt is served without any challenge and grants ordinary
crawling to every agent:

    User-agent: *
    Content-Signal: search=yes,ai-train=no,use=reference
    Allow: /

So this adapter exists, and it crawls the way that permission describes: a
plain HTTP request, an honestly declared user agent, no impersonation of a
browser and no rate beyond one page at a time.

TWO RULES FROM THE SAME FILE, WHICH THIS ADAPTER DELIBERATELY OBEYS.

1. `User-agent: CloudflareBrowserRenderingCrawler / Disallow: /`. Elia
   disallows browser-rendering crawlers by name. Rendering is the only
   technique that could clear the challenge now sitting in front of these
   pages, and it is the technique their robots.txt refuses. So this adapter
   must never call render_html(). If a future maintainer reaches for it to
   "fix" this source, that is not a fix; it is doing the one thing the site
   asked us not to do.

2. `ai-train=no`, and named AI crawlers are disallowed. TRACK analyses and
   links, and never trains on collected text, which `use=reference` permits.
   Keep it that way.

Today every path except robots.txt returns 403 from an over-broad WAF, so
discovery raises UpstreamUnavailable and the run exits cleanly rather than
failing. That is deliberate: this is a standing, honest, permitted request
that costs one HTTP call per run and starts working by itself the day Elia's
firewall stops refusing the crawler its own policy allows.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable,
                  html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "Elia"
DOCUMENT_TYPE = "TSO"

BASE = "https://www.elia.be"
LISTINGS = ["/en/public-consultation", "/en/news/press-releases"]

# Honest identification, as a permitted crawler rather than a fake browser.
CRAWLER_UA = ("MarketDesignBot/1.0 (+https://marketdesign.ai; "
              "market-design research monitor)")

_DATE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})")
ARTICLE = re.compile(r"/en/(?:news/press-releases|public-consultation)/[^/]+")

DATE_REFINED_ON_FETCH = True


def _get(session, url, timeout=45):
    """Plain fetch under our own name. Never a rendered fetch — see module docstring."""
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True,
                        headers={"User-Agent": CRAWLER_UA,
                                 "Accept": "text/html,application/xhtml+xml",
                                 "Accept-Language": "en"})
    except requests.RequestException as exc:
        raise UpstreamUnavailable(f"Elia unreachable: {exc}")
    if r.status_code == 403:
        raise UpstreamUnavailable(
            "Elia returned 403 to a declared crawler, although robots.txt grants "
            "'User-agent: * / Allow: /'. Over-broad WAF, not a stated refusal. "
            "Do not work around it with a rendered fetch: robots.txt disallows "
            "CloudflareBrowserRenderingCrawler by name.")
    if r.status_code >= 400:
        raise CollectorError(f"Elia returned HTTP {r.status_code} for {url}")
    return r


def _date(text: str) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt).date().isoformat()
        except ValueError:
            continue
    return None


def discover(session):
    found: dict[str, Candidate] = {}
    for path in LISTINGS:
        listing = urljoin(BASE, path)
        r = _get(session, listing)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a["href"].split("?")[0]
            if not ARTICLE.search(href):
                continue
            title = " ".join(a.get_text(" ", strip=True).split())
            if len(title) < 15:
                continue
            url = urljoin(BASE, href)
            sid = f"elia-{slugify(url.rstrip('/').split('/')[-1])}"
            found.setdefault(sid, Candidate(sid, title, None, url))
    if not found:
        raise UpstreamUnavailable("Elia listings carried no items")
    return " + ".join(urljoin(BASE, p) for p in LISTINGS), list(found.values())


def is_out_of_scope(candidate: Candidate) -> bool:
    t = candidate.title.lower()
    return any(x in t for x in ("gas", "hydrogen", "waterstof", "vacature", "job"))


def fetch_content(session, candidate: Candidate) -> str:
    r = _get(session, candidate.url, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.get_text(" ", strip=True).split())
        if len(title) > 8:
            candidate.title = title
    main = soup.find("main") or soup
    text = html_to_text(main)
    if not candidate.publication_date:
        candidate.publication_date = _date(text[:1200])
    return text[:MAX_CONTENT_CHARS]
