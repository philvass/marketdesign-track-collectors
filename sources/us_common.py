"""Shared vocabulary for the US adapters.

The US monitor is deliberately sparse: it should carry the handful of
decisions a European market designer would want to know about, not the
news flow of four organisations. Two filters enforce that. This module is
the first, applied to titles before anything is fetched: a candidate must
name a market-design subject and must not be one of the recurring
operational, corporate or study announcements. The second is TRACK's own
US significance gate, which reads the document.
"""
from __future__ import annotations

import re

REGION = "US"

# A title must match this to be considered at all.
MARKET_DESIGN = re.compile(
    r"\b(capacity market|capacity auction|capacity accreditation|accreditation|"
    r"resource adequacy|energy market|ancillary service|ancillary services|"
    r"wholesale market|market rule|market rules|market reform|market reforms|"
    r"market design|price formation|scarcity pric|shortage pric|"
    r"day-ahead|real-time market|co-optimi[sz]|reserve product|reserve market|"
    r"operating reserve|demand response|demand curve|buyer-side|"
    r"storage participation|energy storage|distributed energy resource|"
    r"virtual power plant|extended day-ahead|edam|imbalance market|"
    r"notice of proposed rulemaking|order no\.|"
    r"tariff|market power|mitigation|interregional transfer|seams|"
    r"fast-start|uplift|congestion revenue|financial transmission right|"
    r"capacity performance|reliability must-run|rmr|"
    r"colocat|co-locat|large load|data cent|"
    # RTO governance is market design when it decides who writes the rules;
    # PJM's 2026 reform is the case that made this necessary.
    r"governance reform|stakeholder reform|governance and stakeholder|"
    # Decision verbs: an approval or rejection is what the monitor exists for.
    r"board approves|governing body approves|board of governors approves|"
    r"ferc approves|ferc accepts|ferc rejects|ferc directs|ferc proposes|"
    r"ferc orders|ferc issues (?:final|order)|files .* with ferc|files with ferc)", re.I)

# Recurring announcements that are never a design decision, whatever else
# the title says.
NOISE = re.compile(
    r"\b(joins|join the|commits to|commit to|becomes .* to commit|"
    r"appoint|reappoint|elects|elected|names |named |welcomes|retire|"
    r"record|records|all-time high|heat ?wave|heat dome|cold snap|winter storm|"
    r"summer readiness|winter readiness|summer conditions|"
    r"energy watch|energy warning|energy emergency|conservation|"
    r"power trends|annual report|quarterly|benefits report|survey|"
    r"press conference|webinar|registration|video|podcast|"
    r"environmental impact statement|environmental assessment|"
    r"pipeline|natural gas|lng|hydropower|hydroelectric|dam safety|"
    r"oil pipeline|sunshine notice|ferc insight|highlights|"
    r"selected developers|competitive transmission|transmission project|"
    r"transmission planning|connection study|transmission readiness|"
    r"expedited resource addition|eras cycle|interconnection queue|"
    r"celebrat|anniversary|scholarship|award)", re.I)


# The monitors are a different case. Their quarterly and annual reports are
# the product, not the housekeeping, so the general noise list would throw
# away exactly what makes them worth reading. Only genuinely non-substantive
# items are dropped here.
MONITOR_NOISE = re.compile(
    r"\b(appoint|reappoint|elects|elected|names |named |welcomes|retire|"
    r"careers|vacanc|webinar|registration|celebrat|anniversary|award|"
    r"brand guidelines|fact sheet)\b", re.I)


def title_in_scope(title: str) -> bool:
    return bool(MARKET_DESIGN.search(title)) and not NOISE.search(title)
