"""
vat_config.py
----------------------------------------------------------------------
Central configuration for Zimbabwe VAT rules used by the calculation
engine (vat_engine.py). Keeping the rules here — instead of hard-coding
them inside the engine or the UI — means a rate change or a rule
change (which ZIMRA issues fairly often via Public Notices / the
annual Finance Act) only needs to be edited in ONE place.

Sources (see README "References" section for links):
  - VAT Act [Chapter 23:12]
  - ZIMRA Public Notice 07 of 2026 & Public Notice 11 of 2026
    (standard rate raised from 15% to 15.5% w.e.f. 1 January 2026)
  - ZIMRA "Mechanics of VAT" / "Refund of VAT" guidance pages
  - ZIMRA Explanatory Notes for completion of the VAT Return (VAT7)
  - Finance Act No. 7 of 2021 (Fiscal Tax Invoice requirement,
    effective 1 January 2022)
----------------------------------------------------------------------
"""

from dataclasses import dataclass
from datetime import date


# ----------------------------------------------------------------------
# 1. VAT RATE HISTORY
# ----------------------------------------------------------------------
# Each entry is the rate that applies from `effective_from` onward,
# until the next entry's date. Add a new row whenever ZIMRA changes
# the standard rate — nothing else in the codebase needs to change.
RATE_HISTORY = [
    {"effective_from": date(2020, 1, 1), "rate": 0.145, "label": "14.5%"},
    {"effective_from": date(2020, 7, 1), "rate": 0.145, "label": "14.5%"},
    {"effective_from": date(2022, 1, 1), "rate": 0.145, "label": "14.5%"},
    {"effective_from": date(2023, 1, 1), "rate": 0.15, "label": "15%"},
    {"effective_from": date(2026, 1, 1), "rate": 0.155, "label": "15.5%"},
]


def standard_rate_on(supply_date: date) -> float:
    """Return the standard VAT rate (as a decimal) in force on a given
    date, per the VAT rate history above. This implements the
    'time of supply' driven rate lookup ZIMRA requires (see Public
    Notice 07/2026 and 11/2026 re: the 15% -> 15.5% transition)."""
    applicable = RATE_HISTORY[0]["rate"]
    for entry in RATE_HISTORY:
        if supply_date >= entry["effective_from"]:
            applicable = entry["rate"]
        else:
            break
    return applicable


CURRENT_STANDARD_RATE = RATE_HISTORY[-1]["rate"]  # 15.5%, effective 1 Jan 2026
WITHHOLDING_FRACTION = 1 / 3  # VAT Withholding Tax agents withhold 1/3 of VAT
VAT_REGISTRATION_TURNOVER_THRESHOLD = 40000  # USD p.a., compulsory registration
DE_MINIMIS_TAXABLE_USE_THRESHOLD = 0.90  # >=90% taxable use -> claim 100% input tax
DE_MINIMIS_EXEMPT_USE_THRESHOLD = 0.10  # <=10% taxable use (i.e. >=90% exempt) -> claim 0%
TAX_INVOICE_MAX_AGE_DAYS = 365  # invoice >12 months old cannot support an input claim


# ----------------------------------------------------------------------
# 2. SUPPLY / TRANSACTION CATEGORIES
# ----------------------------------------------------------------------
# These map directly onto the sections of the VAT7 return.

OUTPUT_CATEGORIES = {
    "standard_sale": {
        "label": "Standard-rated sale (15.5%)",
        "rate_type": "standard",
        "vat7_field": "Output Tax - Standard Rated Supplies",
    },
    "zero_rated_sale": {
        "label": "Zero-rated sale (exports, specified goods, s.10 VAT Act)",
        "rate_type": "zero",
        "vat7_field": "Value of Supplies - Zero Rated",
    },
    "exempt_sale": {
        "label": "Exempt supply (s.11 / Sch. 2 VAT Act — e.g. financial services, "
                 "residential rentals, education, medical services)",
        "rate_type": "exempt",
        "vat7_field": "Exempt Supplies (memorandum only)",
    },
    "deemed_supply": {
        "label": "Deemed supply (fringe benefit, change in use, "
                 "asset retained on deregistration - s.6/s.9)",
        "rate_type": "standard",
        "vat7_field": "Output Tax - Adjustments (Deemed Supplies)",
    },
    "bad_debt_recovered": {
        "label": "Bad debt previously written off, now recovered",
        "rate_type": "standard",
        "vat7_field": "Output Tax - Adjustments (Bad Debts Recovered)",
    },
}

INPUT_CATEGORIES = {
    "standard_purchase": {
        "label": "Standard-rated local purchase/expense (15.5%)",
        "rate_type": "standard",
        "vat7_field": "Input Tax - Local Purchases",
        "claimable_default": True,
    },
    "import": {
        "label": "Import of goods (VAT paid at Customs — Bill of Entry)",
        "rate_type": "standard",
        "vat7_field": "Input Tax - Imports",
        "claimable_default": True,
    },
    "zero_rated_purchase": {
        "label": "Zero-rated purchase",
        "rate_type": "zero",
        "vat7_field": "Input Tax - Zero Rated Purchases",
        "claimable_default": True,
    },
    "exempt_purchase": {
        "label": "Exempt purchase (no VAT charged)",
        "rate_type": "exempt",
        "vat7_field": "n/a",
        "claimable_default": False,
    },
    "denied_entertainment": {
        "label": "Entertainment (s.16(2)(c) VAT Act — input tax denied)",
        "rate_type": "standard",
        "vat7_field": "Input Tax - Denied (Entertainment)",
        "claimable_default": False,
    },
    "denied_passenger_vehicle": {
        "label": "Passenger motor vehicle purchase (s.16(2)(a) — input tax denied "
                 "unless dealer's stock-in-trade/hire vehicle)",
        "vat7_field": "Input Tax - Denied (Passenger Vehicle)",
        "rate_type": "standard",
        "claimable_default": False,
    },
    "denied_club_subscription": {
        "label": "Club, association or society subscription (s.16(2)(d) — denied)",
        "rate_type": "standard",
        "vat7_field": "Input Tax - Denied (Club Subscriptions)",
        "claimable_default": False,
    },
    "denied_no_fiscal_invoice": {
        "label": "No valid Fiscal Tax Invoice held — claim denied",
        "rate_type": "standard",
        "vat7_field": "Input Tax - Denied (No Fiscal Tax Invoice)",
        "claimable_default": False,
    },
    "bad_debt_relief": {
        "label": "Bad debt written off (>12 months unpaid, output tax "
                 "previously accounted for — relief claimed as input tax, s.22)",
        "rate_type": "standard",
        "vat7_field": "Input Tax - Adjustments (Bad Debts Written Off)",
        "claimable_default": True,
    },
    "credit_note_received": {
        "label": "Credit note received from supplier (reduces input tax)",
        "rate_type": "standard",
        "vat7_field": "Input Tax - Adjustments (Credit Notes Received)",
        "claimable_default": True,
        "reverses": True,
    },
}

DENIED_INPUT_KEYS = {
    "denied_entertainment",
    "denied_passenger_vehicle",
    "denied_club_subscription",
    "denied_no_fiscal_invoice",
    "exempt_purchase",
}

TRANSACTION_TYPES = {"sale": OUTPUT_CATEGORIES, "purchase": INPUT_CATEGORIES}
