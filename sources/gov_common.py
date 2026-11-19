"""A stricter title test for the small-country energy ministries.

A ministry's news feed is mostly not market design: visits, council meetings,
cooperation agreements, funding rounds, speeches. The per-country keyword
filters keep anything about electricity, which for a small administration with
one press channel still lets most of that through, and every item that passes
costs a model call and, if it slips past the relevance gate, a draft on the
editor's desk.

This test asks for more. A title passes only if it names an INSTRUMENT (a law
or ordinance, a consultation, a market, a tariff or network charge, an
auction, a capacity, balancing, flexibility or storage arrangement, a price
intervention), is about the power sector, and is not a diplomatic or
ceremonial item. It works on word stems across the languages concerned, so it
is deliberately approximate: it will drop a relevant item now and then, which
for these sources is the right side to err on, because the national regulator
and system operator are collected separately and carry the implementation.
"""
from __future__ import annotations

import re

from core import UpstreamUnavailable

_POWER = re.compile(
    r"strom|elektri|elektro|electri|eletri|électri|elnät|elnet|elmarkn|elmarked|elområd|elpris|elräkn|"
    r"\bel\b|elforsyn|elförsörj|villamos|áram|електро|ток\b|sähkö|"
    r"erneuerbar|obnovljiv|megújuló|възобновяем|taastuv|atjaunoj|renováve|vedvarende|förnybar|"
    r"photovolt|\bpv\b|solar|wind|vjetro|vetrn|szél|вятър|tuule|vēja|eólic|vind|"
    r"netz|omrež|mrež|hálózat|мреж|võrgu|tīkl|rede\b|redes|"
    r"speicher|hranilnik|skladišt|tároló|съхранен|salvest|uzkrā|armazenamento|lagring|"
    r"kraftwerk|elektrarn|elektran|erőmű|централ|elektrijaam|elektrostacij|cogera|kraftværk|kraftverk|"
    r"energi|енерг|injeç|injec", re.I)

_INSTRUMENT = re.compile(
    # law, ordinance, consultation
    r"gesetz|verordnung|novelle|begutachtung|zakon|uredb|pravilnik|törvény|rendelet|закон|наредб|постановлени|"
    r"seadus|määrus|eelnõu|likum|noteikum|regulējum|decreto|portaria|despacho|\blei\b|lovforslag|bekendtgørelse|"
    r"lagförslag|proposition|förordning|remiss|"
    r"konsultat|javni obravnav|javno savjetovanj|savjetovanj|обществено обсъждане|avalik|sabiedrisk|"
    r"consulta pública|høring|samråd|"
    # market, tariffs, procurement
    r"markt|mercado|\btrg|tržišt|tirgu|turu\b|turg|piac|пазар|marknad|marked|"
    r"tarif|omrežnin|mrežarin|võrgutas|hálózati díj|netzentgelt|nettarif|nätavgift|"
    r"aukc|aukt|leilão|leilões|procedimentos? concorrencia|licit|търг|udbud|anbud|oksjon|izsol|dražb|vähempakkumi|"
    # capacity, balancing, flexibility, storage, congestion
    r"kapazität|kapacit|zmogljivost|capacidade|võimsus|jaud|kapazitätsmechanismus|"
    r"balanc|bilanc|izravnav|regelenergie|flexib|prožnost|fleksib|rugalmas|paindlik|elastīg|"
    r"flaskhals|engpass|zagušenj|congest|"
    # price interventions and support design
    r"kompenz|компенсац|kompensat|högkostnadsskydd|preisbremse|price cap|ценов таван|árplafon|hinnalagi|"
    r"differenzvertr|contratos? por diferença|\bcfd\b|prispevk|toetusmeet|"
    r"reform|akutplan|udspil", re.I)

_CEREMONIAL = re.compile(
    r"besuch|visit|obisk|posjet|látogat|посещени|külastus|vizīt|visita|besøg|besök|"
    r"srečanj|sastan|találkoz|среща|kohtumi|tikšan|reunião|møde\b|möte\b|treffen|"
    r"konferen|webin|vebin|seminar|fórum|forum|kongres|"
    r"energierat|energetskega sveta|vijeću eu|vijeća eu|energianõukogu|energeetikanõukogu|"
    r"ministru sanāksm|energiråd|conselho de energia|съвет на ес|"
    r"memorand|sporazum o sodelovanj|suradnj|sodelovanj|sadarbīb|együttműködés|сътрудничеств|"
    r"donation|donācij|annetus|adomány|дарени|"
    r"nagrad|auszeichnung|díjat|награда|auhin|balv|prémio|pris\b|"
    r"uuring|študij|studie zeigt|tanulmány|pētījum", re.I)


def is_market_design(title: str) -> bool:
    t = title or ""
    return bool(_POWER.search(t) and _INSTRUMENT.search(t) and not _CEREMONIAL.search(t))


def market_design_only(discover, institution: str):
    """Wrap a ministry adapter's discover() with the stricter title test."""
    def wrapped(session):
        url, candidates = discover(session)
        kept = [c for c in candidates if is_market_design(c.title)]
        if not kept:
            raise UpstreamUnavailable(
                f"No market-design item among {len(candidates)} {institution} energy items this run")
        return url, kept
    return wrapped
