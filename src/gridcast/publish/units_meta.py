# ruff: noqa: E501 (data-dictionary lines; keep prose intact on one line per entry)
"""Single source of truth for market-unit presentation metadata.

The frontend renders every displayable market fact (names, countries,
operators, caveats, timezones, cadences, publication lags, source links)
from these fields - PROJECT_REBUILD_PLAN §3.1.1: nothing about markets
lives in JavaScript constants. Changing a caveat here re-renders the site
with no frontend edit.
"""

from __future__ import annotations

from gridcast.config import CADENCE_MINUTES
from gridcast.eval.backtest import PRIMARY_METRIC, PUB_LAG_DAYS
from gridcast.features.calendar import UNIT_TZ

_UNIT_BASE = {
    "GB": dict(
        display_name="Great Britain",
        operator="NESO",
        country_code="gb",
        source_link="https://data.neso.energy",
        caveat="Operator actuals publish ~21 days late by design - the tail of the fact series always ends three weeks before today.",
    ),
    "ALL": dict(
        display_name="Ireland (All-Island power system)",
        operator="EirGrid",
        country_code="ie",
        source_link="https://www.smartgriddashboard.com",
        caveat="Northern Ireland co-modeled with the Republic of Ireland as one market. Small upstream null holes in the feed are documented.",
    ),
    "NEM_TOTAL": dict(
        display_name="Australia - NEM total",
        operator="AEMO",
        country_code="au",
        source_link="https://aemo.com.au/aemo/data/nem/priceanddemand/",
        caveat="Sum of five regional loads at 5-minute dispatch cadence.",
    ),
    "NSW1": dict(
        display_name="Australia - New South Wales",
        operator="AEMO",
        country_code="au",
        source_link="https://aemo.com.au/aemo/data/nem/priceanddemand/",
        caveat="5-minute dispatch region series.",
    ),
    "QLD1": dict(
        display_name="Australia - Queensland",
        operator="AEMO",
        country_code="au",
        source_link="https://aemo.com.au/aemo/data/nem/priceanddemand/",
        caveat="5-minute dispatch region series.",
    ),
    "SA1": dict(
        display_name="Australia - South Australia",
        operator="AEMO",
        country_code="au",
        source_link="https://aemo.com.au/aemo/data/nem/priceanddemand/",
        caveat="Operational demand dips below 0 MW at solar noon - sMAPE is the only honest ratio metric here.",
    ),
    "TAS1": dict(
        display_name="Australia - Tasmania",
        operator="AEMO",
        country_code="au",
        source_link="https://aemo.com.au/aemo/data/nem/priceanddemand/",
        caveat="Small-region volatility amplifies percentage metrics.",
    ),
    "VIC1": dict(
        display_name="Australia - Victoria",
        operator="AEMO",
        country_code="au",
        source_link="https://aemo.com.au/aemo/data/nem/priceanddemand/",
        caveat="5-minute dispatch region series.",
    ),
    "FR": dict(
        display_name="France",
        operator="RTE",
        country_code="fr",
        source_link="https://odre.opendatasoft.com",
        caveat="Definitive archive carried 30-minute demand until Jun 2026; rolling feed is 15-minute. Mixed cadence is the operator's design.",
    ),
    "DE": dict(
        display_name="Germany",
        operator="SMARD / Bundesnetzagentur",
        country_code="de",
        source_link="https://www.smard.de",
        caveat="SMARD revises historic values retroactively; we re-read the freshest two weeks every run.",
    ),
    "BE": dict(
        display_name="Belgium",
        operator="Elia",
        country_code="be",
        source_link="https://opendata.elia.be",
        caveat="Transmission offtake view - midday solar depressions are real physics, well below the MAPE floor.",
    ),
    "DK": dict(
        display_name="Denmark",
        operator="Energinet",
        country_code="dk",
        source_link="https://api.energidataservice.dk",
        caveat="Industry-settlement consumption publishes ~18 days late - this lag is the operator's design.",
    ),
    "KZ": dict(
        display_name="Kazakhstan - North-South zone",
        operator="KOREM",
        country_code="kz",
        source_link="https://portal.korem.kz",
        caveat="Clearing-trade demand of centralized trades (~25-45% of physical consumption) - market-side volume, not physical grid load.",
    ),
    "KZ_W": dict(
        display_name="Kazakhstan - West zone",
        operator="KOREM",
        country_code="kz",
        source_link="https://portal.korem.kz",
        caveat="Clearing-trade demand, West zone - trade-side volume, not physical grid load.",
    ),
}

FLAGS = {
    "gb": "\U0001f1ec\U0001f1e7", "ie": "\U0001f1ee\U0001f1ea",
    "au": "\U0001f1e6\U0001f1fa", "fr": "\U0001f1eb\U0001f1f7",
    "de": "\U0001f1e9\U0001f1ea", "be": "\U0001f1e7\U0001f1ea",
    "dk": "\U0001f1e9\U0001f1f0", "kz": "\U0001f1f0\U0001f1ff",
}

# same market key as MARKET_UNITS in forecast.py
UNIT_MARKET = {
    "GB": "GB", "ALL": "IE",
    "NEM_TOTAL": "AU", "NSW1": "AU", "QLD1": "AU", "SA1": "AU",
    "TAS1": "AU", "VIC1": "AU",
    "FR": "FR", "DE": "DE", "BE": "BE", "DK": "DK",
    "KZ": "KZ", "KZ_W": "KZ",
}


def build_units_meta() -> dict[str, dict]:
    """Assemble the v2 units_meta payload with derived fields attached."""
    out = {}
    for unit, base in _UNIT_BASE.items():
        market = UNIT_MARKET[unit]
        cc = base["country_code"]
        out[unit] = {
            "unit": unit,
            "market": market,
            "display_name": base["display_name"],
            "operator": base["operator"],
            "country_code": cc,
            "flag": FLAGS.get(cc, ""),
            "tz": UNIT_TZ[unit],
            "cadence_min": CADENCE_MINUTES[market],
            "pub_lag_days": PUB_LAG_DAYS[market],
            "primary_metric": PRIMARY_METRIC[market],
            "source_link": base["source_link"],
            "caveat": base["caveat"],
        }
    return out


UNITS_META = build_units_meta()
