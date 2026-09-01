# 🇿🇼 Zimbabwe VAT Return Automation System

An automated system that calculates a Zimbabwe VAT return from accounting
transaction data — output tax, allowable input tax, adjustments and special
transactions, net VAT payable/refundable — with a full, line-by-line
**auditable calculation trail**, delivered as a simple Streamlit web app.

> ⚠️ **Disclaimer**: This is a decision-support / educational tool, not a
> substitute for professional tax advice or ZIMRA's own TaRMS system.
> Always verify results against the current VAT Act [Chapter 23:12] and
> ZIMRA Public Notices before submitting a return.

---

## 1. What it does

You give it a list of transactions (sales and purchases) for a tax period.
It:

1. **Calculates Output Tax** on standard-rated, zero-rated, exempt and
   deemed supplies, applying the VAT rate that was actually in force on
   each transaction's date of supply.
2. **Calculates allowable Input Tax**, applying ZIMRA's input tax rules:
   - denies input tax on entertainment, passenger motor vehicles, and
     club/association subscriptions (VAT Act s.16(2)),
   - denies claims with no valid **Fiscal Tax Invoice** / Bill of Entry,
   - apportions input tax for mixed taxable/exempt use, including the
     90% / 10% **de minimis** rule,
   - allows **bad debt relief** (debts >12 months old, written off) and
     reverses input tax for **credit notes received**.
3. **Processes adjustments and special transactions**: deemed supplies
   (fringe benefits / change in use), bad debts recovered, credit notes,
   bad debt relief, and VAT withheld at source by appointed VAT
   Withholding Agents (1/3 withholding).
4. **Determines net VAT payable or refundable** for the period.
5. **Produces a return summary** (mapped to the ZIMRA VAT7 return fields)
   and a **full calculation trail** — one row per transaction, showing the
   rule applied and the legal basis, downloadable as CSV for your working
   papers or an audit file.

## 2. Zimbabwe VAT rules built into the system

Current as of 2026 (see [References](#7-references) for sources):

| Rule | How it's handled |
|---|---|
| Standard VAT rate | **15.5%** with effect from **1 January 2026** (up from 15%, per ZIMRA Public Notices 07 & 11 of 2026). The rate is looked up **per transaction, by date of supply**, from a rate history table (`vat_config.py`) — a future rate change only needs one new line added there. |
| Zero-rated supplies | e.g. exports — output tax at 0%, still a taxable supply, input tax on related purchases remains claimable. |
| Exempt supplies | e.g. residential rentals, financial services — outside the VAT system entirely; no output tax, no related input tax. |
| Fiscal Tax Invoice requirement | Since 1 Jan 2022 (Finance Act No. 7 of 2021), input tax may only be claimed with a valid **Fiscal Tax Invoice** (or Bill of Entry for imports). A purchase flagged `has_fiscal_invoice = False` has its input tax claim **denied**, with the reason recorded in the audit trail. |
| Denied input tax categories (s.16(2) VAT Act) | Entertainment, passenger motor vehicles (unless the registered operator's stock-in-trade or hire fleet), and club/association subscriptions are automatically denied. |
| Apportionment / de minimis | For goods/services used partly for taxable and partly for exempt supplies: ≥90% taxable use → full claim; ≤10% taxable use → nil claim; in between → apportioned by the `taxable_use_pct` you supply (turnover-based method). |
| Deemed supplies | Fringe benefits, change in use, and similar deemed supplies are charged output tax on the value entered (open market value). |
| Bad debts | **Bad debt relief**: a debt outstanding >12 months and written off, where output tax was already declared, is claimed back as an input tax deduction. **Bad debt recovered**: if a written-off debt is later recovered, output tax is reinstated on the amount recovered. |
| Credit notes | A credit note received from a supplier reverses (reduces) input tax previously claimable on that purchase. |
| VAT Withholding Tax | Appointed VAT Withholding Agents withhold **1/3** of the VAT on your invoice and remit it directly to ZIMRA. The total shown on withholding certificates received for the period is entered separately and **credited against your net VAT payable**. |
| VAT7 return mapping | Every transaction is tagged with the return field it feeds into (e.g. *"Output Tax – Standard Rated Supplies"*, *"Input Tax – Denied (Entertainment)"*) so the summary reads like the actual return. |

## 3. Repository structure

```
zw-vat-return/
├── app.py                       # Streamlit UI (thin presentation layer)
├── vat_engine.py                # Core calculation engine (pure Python/pandas, unit-testable)
├── vat_config.py                # VAT rules, rates, categories — single source of truth
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
├── .streamlit/
│   └── config.toml              # Simple, clean UI theme
├── sample_data/
│   └── sample_transactions.csv  # Example dataset covering every rule above
└── tests/
    └── test_vat_engine.py       # Unit tests for the calculation engine
```

**Design**: `vat_engine.py` has no dependency on Streamlit — it takes a
pandas DataFrame in and returns a `ReturnSummary` + audit trail DataFrame
out. This keeps the tax logic testable and reusable (e.g. from a script or
notebook) independently of the web UI, and makes it easy to audit the
rules in one place.

## 4. Running it locally

Requires Python 3.10+.

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/zw-vat-return.git
cd zw-vat-return

# 2. Create and activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`. Click **"Load sample dataset"**
on the Upload tab for an instant working example, or enter your own
transactions manually / upload a CSV or Excel file.

### Running the tests

```bash
pytest tests/
```

## 5. Using the app

1. **Set the tax period** and, if applicable, the **total VAT withheld at
   source** (from withholding tax certificates received) in the sidebar.
2. **Provide transactions** either by:
   - uploading a CSV/XLSX file (see column spec below), or
   - typing/pasting rows into the editable table on the "Enter manually" tab.
3. Review the **VAT Return Summary** (Output Tax, Input Tax, Net VAT
   Payable/Refundable, memorandum values of supply).
4. Review the **Auditable Calculation Trail** — filterable by direction
   and treatment — and download it (and the summary) as CSV.

### Transaction file format

| Column | Required | Description |
|---|---|---|
| `transaction_id` | Yes | Any unique reference |
| `date` | Yes | `YYYY-MM-DD` — determines which VAT rate applies |
| `transaction_type` | Yes | `sale` or `purchase` |
| `category` | Yes | One of the category codes below |
| `description` | Yes | Free text |
| `net_amount` | Yes | Value of supply, **excluding** VAT |
| `has_fiscal_invoice` | No (default `True`) | Required to claim input tax |
| `taxable_use_pct` | No (default `100`) | 0–100, for mixed-use purchase apportionment |
| `vat_withheld` | No (default `0`) | VAT withheld on a sale by a WHT agent (informational; enter the period total in the sidebar) |
| `notes` | No | Free text |

**Sale categories**: `standard_sale`, `zero_rated_sale`, `exempt_sale`,
`deemed_supply`, `bad_debt_recovered`.

**Purchase categories**: `standard_purchase`, `import`,
`zero_rated_purchase`, `exempt_purchase`, `denied_entertainment`,
`denied_passenger_vehicle`, `denied_club_subscription`,
`denied_no_fiscal_invoice`, `bad_debt_relief`, `credit_note_received`.

See `sample_data/sample_transactions.csv` for a worked example covering
every category.

## 6. Deploying to Streamlit Community Cloud

1. Push this repository to GitHub (public or private — Streamlit
   Community Cloud can access both once authorised).
2. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in
   with GitHub.
3. Click **"New app"**, select this repository and the `main` branch, and
   set the main file path to `app.py`.
4. Click **"Deploy"**. Streamlit Cloud installs `requirements.txt`
   automatically and serves the app at a public
   `https://<app-name>.streamlit.app` URL.
5. Any future push to the connected branch redeploys the app
   automatically.

No secrets or API keys are required for this app, so no `secrets.toml`
setup is needed.

## 7. References

- Zimbabwe VAT Act [Chapter 23:12]
- ZIMRA, *Mechanics of VAT* — https://www.zimra.co.zw/domestic-taxes/vat/mechanics-of-vat
- ZIMRA, *Refund of VAT — features of a valid fiscal tax invoice* — https://www.zimra.co.zw/domestic-taxes/vat/refund-of-vat
- ZIMRA Public Notice 07 of 2026 — *Implications of change of VAT rate on return* (15% → 15.5%, effective 1 Jan 2026)
- ZIMRA Public Notice 11 of 2026 — *Submission of VAT returns and payment — Categories A & C*
- Finance Act No. 7 of 2021 — Fiscal Tax Invoice requirement, effective 1 January 2022
- ZIMRA, *Explanatory Notes for the Completion of VAT Return Form (VAT7)*

Rules and rates change periodically via the annual Finance Act and ZIMRA
Public Notices — always check https://www.zimra.co.zw for the latest
guidance and update `vat_config.py` accordingly if a rate or rule changes.

## 8. Limitations / not covered in this version

- Currency: amounts are treated as a single currency (e.g. USD); it does
  not perform ZiG/USD conversion.
- Category A/B rate-transition-month blended-rate calculations (as
  required in the December 2025/January 2026 transition return) are not
  automated — see ZIMRA Public Notice 07/2026 if you need that specific
  transitional calculation.
- Does not integrate directly with TaRMS/e-filing — it produces the
  figures and audit trail to support manual entry or review against your
  TaRMS submission.

## 9. License

MIT — see [LICENSE](LICENSE).
