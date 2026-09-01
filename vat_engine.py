"""
vat_engine.py
----------------------------------------------------------------------
Pure calculation engine for the Zimbabwe VAT Return Automation System.

Deliberately kept independent of Streamlit so it can be unit tested
and re-used (e.g. from a CLI or a notebook) without pulling in any UI
code. app.py is a thin presentation layer over this module.

Design summary
---------------
1. Input: a pandas DataFrame of transactions (one row per transaction)
   with the columns described in `REQUIRED_COLUMNS` below.
2. Each transaction is individually assessed against the VAT rules in
   vat_config.py, producing an "audit trail" row that records:
      - the amount(s) involved,
      - the VAT rate applied (looked up by date of supply),
      - the VAT7 field/category it maps to,
      - whether the amount was allowed/denied/reversed and WHY
        (the legal basis / rule applied).
3. The audit trail rows are aggregated into a VAT7-style return
   summary (Output Tax, Input Tax, Adjustments, Net VAT).
----------------------------------------------------------------------
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

import vat_config as cfg


REQUIRED_COLUMNS = [
    "transaction_id",
    "date",
    "transaction_type",   # "sale" or "purchase"
    "category",           # key into OUTPUT_CATEGORIES / INPUT_CATEGORIES
    "description",
    "net_amount",          # value of supply, EXCLUDING VAT
    "has_fiscal_invoice",  # bool-like: True/False/1/0/Yes/No
    "taxable_use_pct",     # 0-100, for mixed-use purchases (apportionment); 100 if wholly taxable
    "vat_withheld",        # amount of VAT withheld at source by a WHT agent (sales only), 0 if none
    "notes",
]

OPTIONAL_DEFAULTS = {
    "has_fiscal_invoice": True,
    "taxable_use_pct": 100,
    "vat_withheld": 0,
    "notes": "",
}


@dataclass
class AuditRow:
    transaction_id: str
    date: date
    direction: str          # "Output" or "Input"
    category: str
    vat7_field: str
    description: str
    net_amount: float
    vat_rate: float
    vat_before_rules: float
    apportionment_pct: float
    vat_denied: float
    vat_allowed: float       # final VAT amount counted into the return (signed)
    treatment: str           # "Allowed", "Denied", "Partially allowed", "Zero-rated", "Exempt", "Reversal"
    basis: str               # plain-English legal / rule basis
    warning: Optional[str] = None


@dataclass
class ReturnSummary:
    period_label: str
    output_lines: dict
    input_lines: dict
    total_output_tax: float
    total_input_tax: float
    total_vat_withheld: float
    net_vat_before_withholding: float
    net_vat_payable: float          # positive = pay ZIMRA, negative = refund due
    is_refund: bool
    exempt_supplies_value: float
    zero_rated_supplies_value: float
    standard_supplies_value: float
    total_denied_input_tax: float
    warnings: List[str]


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return True
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _parse_date(value) -> date:
    if isinstance(value, (datetime, date)):
        return value if isinstance(value, date) and not isinstance(value, datetime) else value.date()
    return pd.to_datetime(value).date()


def normalise_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and fill in defaults for an uploaded/entered transaction table."""
    df = df.copy()
    missing = [c for c in ["transaction_id", "date", "transaction_type", "category",
                            "description", "net_amount"] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")

    for col, default in OPTIONAL_DEFAULTS.items():
        if col not in df.columns:
            df[col] = default
        df[col] = df[col].fillna(default)

    df["date"] = df["date"].apply(_parse_date)
    df["net_amount"] = pd.to_numeric(df["net_amount"], errors="coerce").fillna(0.0)
    df["vat_withheld"] = pd.to_numeric(df["vat_withheld"], errors="coerce").fillna(0.0)
    df["taxable_use_pct"] = pd.to_numeric(df["taxable_use_pct"], errors="coerce").fillna(100.0)
    df["has_fiscal_invoice"] = df["has_fiscal_invoice"].apply(_to_bool)
    df["transaction_type"] = df["transaction_type"].str.strip().str.lower()
    df["category"] = df["category"].str.strip()

    bad_types = set(df["transaction_type"]) - {"sale", "purchase"}
    if bad_types:
        raise ValueError(f"Unknown transaction_type value(s): {bad_types}. Must be 'sale' or 'purchase'.")

    all_cats = set(cfg.OUTPUT_CATEGORIES) | set(cfg.INPUT_CATEGORIES)
    bad_cats = set(df["category"]) - all_cats
    if bad_cats:
        raise ValueError(
            f"Unknown category value(s): {bad_cats}. "
            f"Valid categories are: {sorted(all_cats)}"
        )
    return df


def _process_sale(row) -> AuditRow:
    cat_key = row["category"]
    cat = cfg.OUTPUT_CATEGORIES[cat_key]
    supply_date = row["date"]
    rate = cfg.standard_rate_on(supply_date) if cat["rate_type"] == "standard" else 0.0
    net = float(row["net_amount"])
    gross_vat = round(net * rate, 2)

    treatment = "Allowed"
    basis = "Standard-rated supply — output tax accounted for at the rate in force on the date of supply."
    warning = None

    if cat["rate_type"] == "zero":
        treatment = "Zero-rated"
        basis = "Zero-rated supply (e.g. export) — VAT charged at 0% per s.10 VAT Act; still a taxable supply."
    elif cat["rate_type"] == "exempt":
        treatment = "Exempt"
        basis = "Exempt supply (Sch. 2 VAT Act) — falls outside the VAT system; no output tax and disclosed for information only."
        gross_vat = 0.0
    elif cat_key == "deemed_supply":
        basis = "Deemed supply — output tax accounted for on open market value (fringe benefit / change in use / retained asset)."
    elif cat_key == "bad_debt_recovered":
        basis = "Bad debt previously relieved is now recovered — output tax re-instated to the extent recovered."

    withheld = float(row.get("vat_withheld", 0) or 0)
    if withheld > gross_vat + 0.01:
        warning = "VAT withheld exceeds calculated output tax on this line — please check the input."

    return AuditRow(
        transaction_id=row["transaction_id"],
        date=supply_date,
        direction="Output",
        category=cat_key,
        vat7_field=cat["vat7_field"],
        description=row["description"],
        net_amount=net,
        vat_rate=rate,
        vat_before_rules=gross_vat,
        apportionment_pct=100.0,
        vat_denied=0.0,
        vat_allowed=gross_vat,
        treatment=treatment,
        basis=basis,
        warning=warning,
    )


def _process_purchase(row) -> AuditRow:
    cat_key = row["category"]
    cat = cfg.INPUT_CATEGORIES[cat_key]
    supply_date = row["date"]
    rate = cfg.standard_rate_on(supply_date) if cat["rate_type"] == "standard" else 0.0
    net = float(row["net_amount"])
    gross_vat = round(net * rate, 2)
    has_invoice = bool(row["has_fiscal_invoice"])
    use_pct = max(0.0, min(100.0, float(row["taxable_use_pct"])))

    warning = None
    apportionment_pct = 100.0

    # --- Rule 1: statutorily denied categories (s.16(2) VAT Act) -----
    if cat_key in cfg.DENIED_INPUT_KEYS:
        treatment = "Denied"
        vat_allowed = 0.0
        vat_denied = gross_vat
        basis = cat["label"]

    # --- Rule 2: reversal categories (credit notes reduce input tax) -
    elif cat_key == "credit_note_received":
        treatment = "Reversal"
        vat_allowed = -gross_vat  # reduces total input tax
        vat_denied = 0.0
        basis = "Credit note received from supplier — previously claimed input tax reversed."

    # --- Rule 3: bad debt relief (always fully allowed if flagged) ---
    elif cat_key == "bad_debt_relief":
        treatment = "Allowed"
        vat_allowed = gross_vat
        vat_denied = 0.0
        basis = "Debt outstanding >12 months and written off; output tax was previously " \
                "declared on the related sale — relief claimed as an input tax deduction (s.22)."

    # --- Rule 4: no valid fiscal tax invoice held --------------------
    elif not has_invoice and cat["rate_type"] == "standard":
        treatment = "Denied"
        vat_allowed = 0.0
        vat_denied = gross_vat
        basis = "No valid Fiscal Tax Invoice / Bill of Entry held to support the claim " \
                "(Finance Act No.7 of 2021, effective 1 Jan 2022) — claim denied."
        warning = "Obtain a valid Fiscal Tax Invoice to support this claim, or exclude it from the return."

    # --- Rule 5: zero-rated / exempt purchases -----------------------
    elif cat["rate_type"] == "zero":
        treatment = "Zero-rated"
        vat_allowed = 0.0
        vat_denied = 0.0
        basis = "Zero-rated purchase — no VAT was charged, so there is nothing to claim."
    elif cat["rate_type"] == "exempt":
        treatment = "Exempt"
        vat_allowed = 0.0
        vat_denied = 0.0
        basis = "Exempt purchase — no VAT charged, no input tax arises."

    # --- Rule 6: mixed taxable/exempt use -> apportionment -----------
    elif use_pct >= cfg.DE_MINIMIS_TAXABLE_USE_THRESHOLD * 100:
        treatment = "Allowed"
        vat_allowed = gross_vat
        vat_denied = 0.0
        basis = f"Taxable use is {use_pct:.0f}% (>= 90% de minimis threshold) — full input tax claimed."
    elif use_pct <= cfg.DE_MINIMIS_EXEMPT_USE_THRESHOLD * 100:
        treatment = "Denied"
        vat_allowed = 0.0
        vat_denied = gross_vat
        basis = f"Taxable use is only {use_pct:.0f}% (<= 10%, i.e. predominantly for exempt supplies) " \
                f"— input tax claim fully denied under the de minimis rule."
    else:
        apportionment_pct = use_pct
        treatment = "Partially allowed"
        vat_allowed = round(gross_vat * use_pct / 100, 2)
        vat_denied = round(gross_vat - vat_allowed, 2)
        basis = f"Mixed taxable/exempt use — apportioned {use_pct:.0f}% taxable based on the turnover " \
                f"method (taxable supplies / total supplies), per VAT Act apportionment rules."

    return AuditRow(
        transaction_id=row["transaction_id"],
        date=supply_date,
        direction="Input",
        category=cat_key,
        vat7_field=cat["vat7_field"],
        description=row["description"],
        net_amount=net,
        vat_rate=rate,
        vat_before_rules=gross_vat,
        apportionment_pct=apportionment_pct,
        vat_denied=vat_denied,
        vat_allowed=vat_allowed,
        treatment=treatment,
        basis=basis,
        warning=warning,
    )


def build_audit_trail(df: pd.DataFrame) -> List[AuditRow]:
    df = normalise_transactions(df)
    trail = []
    for _, row in df.iterrows():
        if row["transaction_type"] == "sale":
            trail.append(_process_sale(row))
        else:
            trail.append(_process_purchase(row))
    return trail


def audit_trail_to_dataframe(trail: List[AuditRow]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Transaction ID": r.transaction_id,
        "Date": r.date,
        "Direction": r.direction,
        "Category": r.category,
        "VAT7 Field": r.vat7_field,
        "Description": r.description,
        "Net Amount": r.net_amount,
        "VAT Rate": f"{r.vat_rate * 100:.1f}%" if r.vat_rate else "0.0%",
        "VAT Before Rules": r.vat_before_rules,
        "Apportionment %": r.apportionment_pct,
        "VAT Denied": r.vat_denied,
        "VAT Allowed / Counted": r.vat_allowed,
        "Treatment": r.treatment,
        "Basis / Rule Applied": r.basis,
        "Warning": r.warning or "",
    } for r in trail])


def summarise(trail: List[AuditRow], period_label: str = "") -> ReturnSummary:
    outputs = [r for r in trail if r.direction == "Output"]
    inputs = [r for r in trail if r.direction == "Input"]

    def sum_by_field(rows, field_name="vat_allowed"):
        totals = {}
        for r in rows:
            totals.setdefault(r.vat7_field, 0.0)
            totals[r.vat7_field] += getattr(r, field_name)
        return totals

    output_lines = sum_by_field(outputs)
    input_lines = sum_by_field(inputs)

    total_output_tax = round(sum(r.vat_allowed for r in outputs), 2)
    total_input_tax = round(sum(r.vat_allowed for r in inputs), 2)
    total_vat_withheld = 0.0
    total_denied_input_tax = round(sum(r.vat_denied for r in inputs), 2)

    exempt_supplies_value = round(sum(r.net_amount for r in outputs if r.treatment == "Exempt"), 2)
    zero_rated_supplies_value = round(sum(r.net_amount for r in outputs if r.treatment == "Zero-rated"), 2)
    standard_supplies_value = round(
        sum(r.net_amount for r in outputs if r.treatment == "Allowed" and r.category != "bad_debt_recovered"), 2
    )

    warnings = [r.warning for r in trail if r.warning]

    net_vat_before_withholding = round(total_output_tax - total_input_tax, 2)
    net_vat_payable = round(net_vat_before_withholding - total_vat_withheld, 2)

    return ReturnSummary(
        period_label=period_label,
        output_lines={k: round(v, 2) for k, v in output_lines.items()},
        input_lines={k: round(v, 2) for k, v in input_lines.items()},
        total_output_tax=total_output_tax,
        total_input_tax=total_input_tax,
        total_vat_withheld=total_vat_withheld,
        net_vat_before_withholding=net_vat_before_withholding,
        net_vat_payable=net_vat_payable,
        is_refund=net_vat_payable < 0,
        exempt_supplies_value=exempt_supplies_value,
        zero_rated_supplies_value=zero_rated_supplies_value,
        standard_supplies_value=standard_supplies_value,
        total_denied_input_tax=total_denied_input_tax,
        warnings=warnings,
    )


def compute_return(df: pd.DataFrame, period_label: str = "", vat_withheld_total: float = 0.0):
    """Top-level convenience function used by the Streamlit app.

    Returns (summary: ReturnSummary, trail_df: pd.DataFrame)
    `vat_withheld_total` is entered separately by the user (total VAT
    withheld at source by Withholding Tax agents during the period,
    e.g. per withholding tax certificates) since it is a credit against
    the amount payable, not a per-transaction output/input tax item.
    """
    trail = build_audit_trail(df)
    summary = summarise(trail, period_label=period_label)
    # Apply the period's total VAT withheld as a credit against the liability
    summary.total_vat_withheld = round(float(vat_withheld_total or 0), 2)
    summary.net_vat_payable = round(summary.net_vat_before_withholding - summary.total_vat_withheld, 2)
    summary.is_refund = summary.net_vat_payable < 0
    trail_df = audit_trail_to_dataframe(trail)
    return summary, trail_df