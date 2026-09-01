"""
app.py — Zimbabwe VAT Return Automation System
----------------------------------------------------------------------
A simple Streamlit front-end over vat_engine.py.

Run locally with:  streamlit run app.py
----------------------------------------------------------------------
"""

import io
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import vat_config as cfg
import vat_engine as engine

st.set_page_config(
    page_title="Zimbabwe VAT Return Calculator",
    page_icon="🇿🇼",
    layout="wide",
)

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_PATH = BASE_DIR / "sample_data" / "sample_transactions.csv"

BLANK_ROW = {
    "transaction_id": "",
    "date": date.today(),
    "transaction_type": "sale",
    "category": "standard_sale",
    "description": "",
    "net_amount": 0.0,
    "has_fiscal_invoice": True,
    "taxable_use_pct": 100,
    "vat_withheld": 0.0,
    "notes": "",
}

ALL_CATEGORY_KEYS = list(cfg.OUTPUT_CATEGORIES.keys()) + list(cfg.INPUT_CATEGORIES.keys())


def money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def load_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_PATH)


def category_help_table() -> pd.DataFrame:
    rows = []
    for key, meta in cfg.OUTPUT_CATEGORIES.items():
        rows.append({"transaction_type": "sale", "category": key, "meaning": meta["label"]})
    for key, meta in cfg.INPUT_CATEGORIES.items():
        rows.append({"transaction_type": "purchase", "category": key, "meaning": meta["label"]})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# Sidebar — period & inputs
# ----------------------------------------------------------------------

st.sidebar.title("🇿🇼 VAT Return Setup")
st.sidebar.caption("Zimbabwe VAT Return Automation System")

period_label = st.sidebar.text_input("Tax period (e.g. January 2026)", value="January 2026")

st.sidebar.markdown("---")
st.sidebar.subheader("VAT Withholding Tax (WHT)")
st.sidebar.caption(
    "If any of your customers are appointed VAT Withholding Agents, they withhold "
    "1/3 of the VAT on your invoice and remit it to ZIMRA on your behalf. "
    "Enter the total shown on withholding certificates received for this period — "
    "it is credited against your VAT payable."
)
vat_withheld_total = st.sidebar.number_input(
    "Total VAT withheld at source this period ($)", min_value=0.0, value=0.0, step=1.0
)

st.sidebar.markdown("---")
st.sidebar.subheader("Current standard rate")
today_rate = cfg.standard_rate_on(date.today())
st.sidebar.metric("In force today", f"{today_rate * 100:.1f}%")
st.sidebar.caption(
    "Rate is looked up automatically per transaction based on its date of supply, "
    "per the ZIMRA rate history configured in vat_config.py "
    "(15% → 15.5% w.e.f. 1 January 2026, per ZIMRA Public Notices 07 & 11 of 2026)."
)

with st.sidebar.expander("📖 Valid category codes"):
    st.dataframe(category_help_table(), use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------

st.title("Zimbabwe VAT Return Calculator")
st.caption(
    "Upload or enter your accounting transactions, and this tool will calculate output tax, "
    "allowable input tax, adjustments, and your net VAT payable/refundable — "
    "with a full, line-by-line auditable calculation trail modelled on the ZIMRA VAT7 return."
)

st.info(
    "⚠️ **Disclaimer**: This tool is a calculation aid based on publicly available ZIMRA rules "
    "and does not constitute tax advice. Always verify results against the current VAT Act "
    "[Chapter 23:12], ZIMRA Public Notices, and TaRMS before submitting your return.",
    icon="⚠️",
)

# ----------------------------------------------------------------------
# Data input
# ----------------------------------------------------------------------

tab_upload, tab_manual = st.tabs(["📁 Upload transactions", "✍️ Enter transactions manually"])

if "manual_df" not in st.session_state:
    st.session_state.manual_df = pd.DataFrame([BLANK_ROW])

uploaded_df = None

with tab_upload:
    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded_file = st.file_uploader(
            "Upload a CSV or Excel file of transactions", type=["csv", "xlsx", "xls"]
        )
    with col2:
        st.write("")
        st.write("")
        use_sample = st.button("▶ Load sample dataset", use_container_width=True)

    if uploaded_file is not None:
        if uploaded_file.name.lower().endswith(".csv"):
            uploaded_df = pd.read_csv(uploaded_file)
        else:
            uploaded_df = pd.read_excel(uploaded_file)
        st.success(f"Loaded {len(uploaded_df)} transactions from {uploaded_file.name}.")
    elif use_sample:
        uploaded_df = load_sample()
        st.success(f"Loaded {len(uploaded_df)} sample transactions.")

    if uploaded_df is not None:
        st.dataframe(uploaded_df, use_container_width=True, hide_index=True)

    with st.expander("ℹ️ Expected file columns"):
        st.markdown(
            """
| Column | Required | Notes |
|---|---|---|
| `transaction_id` | Yes | Any unique reference |
| `date` | Yes | YYYY-MM-DD — drives which VAT rate applies |
| `transaction_type` | Yes | `sale` or `purchase` |
| `category` | Yes | See "Valid category codes" in the sidebar |
| `description` | Yes | Free text |
| `net_amount` | Yes | Value of supply, **excluding** VAT |
| `has_fiscal_invoice` | No (default True) | True/False — required to claim input tax |
| `taxable_use_pct` | No (default 100) | For mixed taxable/exempt purchases, 0–100 |
| `vat_withheld` | No (default 0) | VAT withheld at source on a sale by a WHT agent |
| `notes` | No | Free text |
            """
        )

with tab_manual:
    st.caption("Add rows below to build your transaction list, then scroll down for the return.")
    edited = st.data_editor(
        st.session_state.manual_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "transaction_type": st.column_config.SelectboxColumn(options=["sale", "purchase"]),
            "category": st.column_config.SelectboxColumn(options=ALL_CATEGORY_KEYS),
            "date": st.column_config.DateColumn(),
            "net_amount": st.column_config.NumberColumn(format="%.2f"),
            "taxable_use_pct": st.column_config.NumberColumn(min_value=0, max_value=100),
            "vat_withheld": st.column_config.NumberColumn(format="%.2f"),
            "has_fiscal_invoice": st.column_config.CheckboxColumn(),
        },
        key="manual_editor",
    )
    st.session_state.manual_df = edited

# Decide which dataset drives the calculation: uploaded file takes priority,
# otherwise fall back to the manually entered table (if it has real data).
source_df = None
if uploaded_df is not None:
    source_df = uploaded_df
else:
    manual_non_empty = st.session_state.manual_df.dropna(subset=["transaction_id"])
    manual_non_empty = manual_non_empty[manual_non_empty["transaction_id"].astype(str).str.strip() != ""]
    if len(manual_non_empty) > 0:
        source_df = manual_non_empty

st.markdown("---")

# ----------------------------------------------------------------------
# Calculate & display return
# ----------------------------------------------------------------------

if source_df is None or len(source_df) == 0:
    st.warning("Upload a file, load the sample dataset, or enter at least one transaction above to calculate a return.")
    st.stop()

try:
    summary, trail_df = engine.compute_return(
        source_df, period_label=period_label, vat_withheld_total=vat_withheld_total
    )
except Exception as e:
    st.error(f"Could not process transactions: {e}")
    st.stop()

st.header(f"📋 VAT Return Summary — {period_label}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Output Tax", money(summary.total_output_tax))
c2.metric("Total Allowable Input Tax", money(summary.total_input_tax))
c3.metric("VAT Withheld at Source (credit)", money(summary.total_vat_withheld))
label = "Net VAT REFUNDABLE" if summary.is_refund else "Net VAT PAYABLE"
c4.metric(label, money(abs(summary.net_vat_payable)))

if summary.is_refund:
    st.success(
        f"✅ Net position: **VAT refund due of {money(abs(summary.net_vat_payable))}** for {period_label}."
    )
else:
    st.warning(
        f"💰 Net position: **VAT payable of {money(summary.net_vat_payable)}** for {period_label}, "
        f"due on or before the 25th of the month following the tax period."
    )

if summary.warnings:
    with st.expander(f"⚠️ {len(summary.warnings)} warning(s) raised during processing", expanded=False):
        for w in summary.warnings:
            st.write(f"- {w}")

st.markdown("### Value of Supplies (memorandum)")
m1, m2, m3 = st.columns(3)
m1.metric("Standard-rated supplies", money(summary.standard_supplies_value))
m2.metric("Zero-rated supplies", money(summary.zero_rated_supplies_value))
m3.metric("Exempt supplies", money(summary.exempt_supplies_value))

col_out, col_in = st.columns(2)

with col_out:
    st.subheader("🧾 Output Tax — VAT7 lines")
    if summary.output_lines:
        out_df = pd.DataFrame(
            [{"VAT7 Field": k, "Amount": v} for k, v in summary.output_lines.items()]
        )
        st.dataframe(out_df, use_container_width=True, hide_index=True)
    st.markdown(f"**Total Output Tax: {money(summary.total_output_tax)}**")

with col_in:
    st.subheader("🧾 Input Tax — VAT7 lines")
    if summary.input_lines:
        in_df = pd.DataFrame(
            [{"VAT7 Field": k, "Amount": v} for k, v in summary.input_lines.items()]
        )
        st.dataframe(in_df, use_container_width=True, hide_index=True)
    st.markdown(f"**Total Allowable Input Tax: {money(summary.total_input_tax)}**")
    st.caption(f"Input tax denied/excluded this period: {money(summary.total_denied_input_tax)}")

st.markdown("### Net VAT Calculation")
calc_df = pd.DataFrame(
    [
        {"Line": "Total Output Tax", "Amount": summary.total_output_tax},
        {"Line": "Less: Total Allowable Input Tax", "Amount": -summary.total_input_tax},
        {"Line": "= Net VAT before withholding credit", "Amount": summary.net_vat_before_withholding},
        {"Line": "Less: VAT withheld at source by WHT agents", "Amount": -summary.total_vat_withheld},
        {"Line": "= Net VAT Payable / (Refundable)", "Amount": summary.net_vat_payable},
    ]
)
st.dataframe(
    calc_df.style.format({"Amount": lambda x: money(x)}),
    use_container_width=True,
    hide_index=True,
)

# ----------------------------------------------------------------------
# Auditable calculation trail
# ----------------------------------------------------------------------

st.markdown("---")
st.header("🔍 Auditable Calculation Trail")
st.caption(
    "Every transaction, the rule applied to it, and how it flows into the return above — "
    "for internal review or in case of a ZIMRA audit query."
)

direction_filter = st.multiselect(
    "Filter by direction", options=["Output", "Input"], default=["Output", "Input"]
)
treatment_filter = st.multiselect(
    "Filter by treatment",
    options=sorted(trail_df["Treatment"].unique()),
    default=sorted(trail_df["Treatment"].unique()),
)

filtered = trail_df[
    trail_df["Direction"].isin(direction_filter) & trail_df["Treatment"].isin(treatment_filter)
]
st.dataframe(filtered, use_container_width=True, hide_index=True)

csv_buffer = io.StringIO()
filtered.to_csv(csv_buffer, index=False)
st.download_button(
    "⬇️ Download calculation trail (CSV)",
    data=csv_buffer.getvalue(),
    file_name=f"vat_audit_trail_{period_label.replace(' ', '_')}.csv",
    mime="text/csv",
)

summary_buffer = io.StringIO()
pd.DataFrame(
    [
        {"Metric": "Period", "Value": period_label},
        {"Metric": "Total Output Tax", "Value": summary.total_output_tax},
        {"Metric": "Total Allowable Input Tax", "Value": summary.total_input_tax},
        {"Metric": "Total Denied Input Tax", "Value": summary.total_denied_input_tax},
        {"Metric": "VAT Withheld at Source", "Value": summary.total_vat_withheld},
        {"Metric": "Net VAT Payable/(Refundable)", "Value": summary.net_vat_payable},
    ]
).to_csv(summary_buffer, index=False)
st.download_button(
    "⬇️ Download return summary (CSV)",
    data=summary_buffer.getvalue(),
    file_name=f"vat_return_summary_{period_label.replace(' ', '_')}.csv",
    mime="text/csv",
)

st.markdown("---")
st.caption(
    "Built as an educational/decision-support tool referencing the Zimbabwe VAT Act [Chapter 23:12] "
    "and ZIMRA public guidance current as of 2026 (standard rate 15.5% w.e.f. 1 January 2026). "
    "Always confirm figures in TaRMS before filing."
)