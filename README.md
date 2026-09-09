# MarketDesign.ai TRACK — NRA/TSO multi-source collector

Discovers market-design publications from European NRAs and TSOs, normalises
them to the TRACK `/ingest/document` contract, deduplicates by source_id +
content hash, and submits new/changed documents for Claude analysis and human
editorial review.

## Sources

| Key | Institution | Discovery |
|---|---|---|
| `cre` | CRE (FR NRA) | cre.fr délibérations + consultations listings (server-rendered; first 25 each) |
| `bnetza` | BNetzA (DE NRA) | BK6/BK8 Beschlusskammer listings + electricity press releases |
| `ofgem` | Ofgem (GB NRA) | Drupal JSON listing API, Generation & Wholesale sector, decision/consultation/call-for-input/code-mod types |
| `rte` | RTE (FR TSO) | services-rte.com news JSON API (cookie-primed) + concerte.fr RSS |
| `neso` | NESO (GB SO) | rss.xml firehose (noise-filtered) + code-modification sitemap |
| `german-tsos` | 50Hertz/Amprion/TenneT/TransnetBW | netztransparenz.de + regelleistung.net LotesNewsXSP JSON APIs (anonymous bootstrap login) |
| `jao` | JAO | resource-center rules library + consultations + news RSS (noise-filtered) |
| `nemo` | NEMO Committee | news/publications/consultations listings (full history, single pages) |
| `aib` | AIB (EECS/GO) | news teasers + sitemap lastmod tracking of rules/residual-mix pages |
| `nbm` | Nordic TSOs (NBM) | WordPress REST API (news, publications, consultations, guides) |
| `dgclima` | EC DG CLIMA (EU ETS) | news listing (carbon-keyword filter) + Better Regulation API initiatives |
| `creg` | CREG (BE NRA) | Drupal faceted publications listing, electricity market themes |
| `acm` | ACM (NL NRA) | Drupal search (Energie + Elektriciteit filters; WAF needs Referer + retry) |
| `elexon` | Elexon (GB BSC) | BSC WordPress REST API: mod-proposals (by modified) + consultations + news |
| `arera` | ARERA (IT NRA) | atti-e-provvedimenti listing (Delibera+Consultazione, settore=4, /R/eel+/R/com) |
| `ceer` | CEER | WordPress REST API: electricity publications (excl. national monitoring) + consultations |
| `recs` | RECS International | WP REST `news` CPT (NOT `posts` — spam-compromised) + /documents inline JSON. **Upstream down since ~11 July 2026**: every path returns HTTP 200 with four spaces, archive shows nothing after that date, no successor domain (recsmarket.eu is the conference site). Reports unavailable and exits 0; nothing to fix here. |
| `energinet` | Energinet (DK TSO) | Umbraco FacetedEnerListApi JSON (news + ancillary-services nodes) |
| `tennet` | TenneT (NL/DE TSO) | /news __NEXT_DATA__ JSON (teaser-only: article pages are WAF-blocked) |
| `nordpool` | Nord Pool | exchange-message-list RSS (full bodies inline; UMM/operational feeds never touched) |
| `omie` | OMIE | notas-de-prensa listing (PDFs; monthly price reports excluded) |
| `gme` | GME | electricity news archive (results-noise filtered) + DTF technical rules |
| `epex` | EPEX SPOT | newsroom listing (noise-filtered; 20s pacing + empty-202 WAF guard) |
| `ferc` | FERC (US) | news releases + headlines via rendered fetch (Cloudflare challenge) + Federal Register rules/NOPRs; US title filter |
| `caiso` | CAISO (US) | news-release cards, market topics only; US title filter |
| `nyiso` | NYISO (US) | /view-press asset publisher (press coverage dropped); date read on fetch; US title filter |
| `miso` | MISO (US) | sitemap.xml news-release entries with lastmod (listing pages 429 quickly); US title filter |
| `pjm` | PJM (US) | Inside Lines RSS with full article bodies inline; US title filter |
| `spp` | SPP (US) | press-release listing (dates in the row; articles under /news-list/); US title filter |
| `pjm-imm` | Monitoring Analytics — PJM IMM (US) | FERC-docket filings + State of the Market recommendations section (PDFs); monitor noise filter |
| `potomac` | Potomac Economics — MISO/NYISO/ISO-NE/ERCOT monitors (US) | document library per market, current and previous year (PDFs); monitor noise filter |
| `texas-register` | PUCT via the Texas Register (US) | official weekly issues, last six, filtered to Public Utility Commission items and 16 TAC ch. 25 rule citations |
| `entsoe-consultations` | ENTSO-E consultation hub (EU) | consultations.entsoe.eu Citizen Space: TSO methodology proposals, one page, no pagination |
| `elia` | Elia (BE TSO) | plain crawl of consultations + press releases under a declared agent, as elia.be/robots.txt permits; the WAF currently answers 403, so runs report `upstream_unavailable` and exit 0 |

Deferred: **ERCOT** (ercot.com) — Imperva/Incapsula returns 403 to plain
requests, to the rendered fetch, and to every subdomain tried (`sa.`, `data.`,
`apiexplorer.`, `api.`). Even `robots.txt` is refused, so ERCOT publishes no
machine-readable statement of what it permits. The Texas PUC interchange and
`puc.texas.gov` are behind Cloudflare and also refuse. `developer.ercot.com`
is open but documents the market-participant transaction APIs, which need
certificates and carry no publications. Retested 9 Sept 2026; do not retry
without a new technique.

ERCOT's market design is covered by two open routes instead. `texas-register`
reads the Secretary of State's official weekly publication, where PUCT
rulemakings — the decisions that actually change ERCOT's market — must appear
before they take effect; this is the Texan equivalent of the Federal Register
route used for FERC. `potomac` collects ERCOT's independent market monitor and
returns more ERCOT documents than any other market.

**Elia** (elia.be) — an adapter now exists and runs, because elia.be/robots.txt
is served without challenge and grants `User-agent: * / Allow: /`. It crawls
the way that permission describes: plain HTTP, honestly declared agent, no
browser impersonation. The WAF still answers 403 to everything but robots.txt,
so each run reports `upstream_unavailable` and exits 0 at the cost of one
request. It starts working by itself if Elia's firewall stops refusing the
crawler its own policy allows.

Do not "fix" it with a rendered fetch. The same robots.txt contains
`User-agent: CloudflareBrowserRenderingCrawler / Disallow: /`, so rendering —
the one technique that could clear the challenge — is the technique the site
refuses by name. The permission to crawl and the refusal to render are both
theirs, and both are honoured.

History: Cloudflare's managed challenge. Retested 9 Sept
2026 with three techniques beyond the plain rendered fetch: a longer virtual
time budget, a warmed profile reused across two passes, and `eliagroup.eu`.
The challenge never settles, so `--dump-dom` hangs rather than returning a
page. `opendata.elia.be` is open but carries only grid time series.

Worth knowing before anyone escalates: Elia's own `robots.txt` is served
without challenge and says `User-agent: * / Allow: /`, with content signals
`search=yes, ai-train=no, use=reference`. Their published policy therefore
permits general crawling; the block is an over-broad WAF, not a stated refusal.
That makes asking Elia to allow our user agent a request to honour their own
robots.txt rather than an exception. Note the same file disallows named AI
crawlers (GPTBot, ClaudeBot, CCBot, Google-Extended) and forbids training use
— TRACK analyses and links rather than trains, which `use=reference` permits,
but the signal is there and should be respected.

Belgian decisions remain covered through `creg`, which approves Elia's
proposals, and the Central European methodology proposals Elia is party to are
consulted in the open at `entsoe-consultations`.
## Local usage

```
pip install -r requirements.txt
python core.py --source cre --dry-run --limit 3
python core.py --source ofgem --submit --limit 5
```

Modes: `--dry-run` (default), `--bootstrap-state` (record baseline, submit
nothing), `--submit`. State: `./state/<source>.sqlite3`.

### Freshness gate

TRACK carries today's news. A document first seen more than `--max-age-days`
after publication is baselined rather than submitted, and that window is **1
day** in production (`MAX_AGE_DAYS` in the workflow, `MAX_DOC_AGE_DAYS` on the
worker): published today or yesterday, nothing older. No source overrides it —
the rule is the same for every site.

Two consequences worth knowing. Sources that publish with an indexing lag will
now rarely submit: EUR-Lex, where CELLAR indexes the Official Journal weeks
after publication, and the market monitors, whose reports the library dates by
year alone. They stay collected because their state keeps advancing, but they
will mostly report nothing new. Widening the window is a one-line change in
both places if that trade turns out to be wrong.

An **undated** document is now held rather than passed. Under a month-long
window a missing date was not evidence of age; under a one-day window almost
everything is too old, so "unknown" is far more likely to be stale than fresh.
Undated documents appear on the editorial desk's rejected page as
`STOP_UNDATED`, with the usual promote button. When discovery already knows the publication date, that decision is
made *before* the fetch: the document is recorded as `STALE_SKIPPED_NOT_FETCHED`
with an empty content hash and never requested. The skip is sticky, so it costs
one decision rather than one request per run, which matters on sources that
rate-limit (EPEX serves an empty HTTP 202 once an IP exceeds its budget).

Documents already fetched at least once keep being re-fetched, so change
detection on anything in TRACK is unaffected. An adapter whose `fetch_content`
may overwrite a publication date supplied by discovery must set
`DATE_REFINED_ON_FETCH = True` to opt out of the pre-fetch skip (currently only
`acm`).

### Content guards

Before submission, `core.py` drops any extraction shorter than 200 characters
or one that `looks_like_binary_text` flags — a PDF, ZIP or Office file served
from a URL that looks like a page and therefore parsed as HTML. Such documents
appear in the run report as `fetch_error: Binary payload extracted as text`.
Adapters should route on `looks_like_pdf(response)` rather than the URL suffix,
since several sources serve PDFs from plain content paths.

## Production behavior (GitHub Actions)

- Matrix job over all six sources every 6 hours (minute 37), max 2 in parallel.
- Scheduled runs only execute when repo variable `TRACK_AUTOMATION_ENABLED=true`.
- SQLite dedupe state persists via the Actions cache (`state-<source>-*`).
- Run reports are retained as artifacts for 14 days.
- `workflow_dispatch` accepts mode (dry-run/submit/bootstrap), a single source
  or `all`, and a per-source limit.

## Safe first activation

1. Dispatch mode=**submit**, limit=**2** — seeds TRACK with the 2 newest
   documents per source for immediate editorial review.
2. Dispatch mode=**bootstrap**, limit=**100** — records everything else
   currently discoverable as baseline; nothing submitted.
3. Dispatch mode=**submit**, limit=**25** — expected: all duplicates, 0 submitted.
4. Set `TRACK_AUTOMATION_ENABLED=true`. The 6-hour schedule is live.

Do not bootstrap after monitoring is live: bootstrap marks currently
discovered documents as already handled.

## Config

- Variable `TRACK_INGEST_URL` — TRACK ingest endpoint (default in core.py).
- Variable `TRACK_AUTOMATION_ENABLED` — must be exactly `true` for scheduled runs.
- Secret `TRACK_INGEST_TOKEN` — optional bearer token if ingestion is protected.
