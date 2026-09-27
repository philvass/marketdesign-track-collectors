#!/usr/bin/env python3
"""One-time backfill for regulator deliberations the 1-day freshness gate missed.

Runs a source's collector against a FRESH state (so every candidate is treated
as first-time) with the freshness window widened to the worker's 30-day cap, so
recently-published-but->1-day documents are submitted instead of baselined.

Usage (dry-run, shows what WOULD submit):
    python3 backfill_deliberations.py cre

Usage (real submit — needs the ingest token):
    TRACK_INGEST_TOKEN=<token> python3 backfill_deliberations.py cre --submit

Only documents within the worker's 30-day acceptance window can land; older ones
are baselined. Editorial approval still gates whether anything reaches the site.
"""
import sys
import tempfile

WINDOW = 30  # the worker's MAX_SOURCE_WINDOW cap; nothing older than this lands

src_key = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "cre"
do_submit = "--submit" in sys.argv

# Widen the payload window to the cap for this one source before core loads it,
# so build_payload sends max_age_days=30 and the worker accepts recent items.
import importlib
mod = importlib.import_module(f"sources.{src_key}")
mod.MAX_AGE_DAYS = WINDOW

import core

state = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False).name
argv = ["--source", src_key, "--limit", "25", "--max-age-days", str(WINDOW),
        "--state", state, "--json"]
argv += ["--submit"] if do_submit else ["--dry-run"]
core.main(argv)
