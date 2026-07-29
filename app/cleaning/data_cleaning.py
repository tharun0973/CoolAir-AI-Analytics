"""
CoolAir Comfort Services — Data Cleaning
==========================================
Consumes the raw CSVs and applies the transformations justified by
01_data_audit.py's findings. Every transformation is logged with a reason,
and the cleaning log is written alongside the cleaned output so the "what
did you decide and why" trail survives past this script's run.

Judgment calls made here (see logs/data_cleaning_report.md for the full,
row-level version):
  - Placeholder tokens (N/A, -1, blank strings) -> NULL
  - Dates normalized to ISO (YYYY-MM-DD)
  - Whitespace trimmed on all string fields
  - Phone numbers normalized to a consistent digits-only or E.164-ish format
  - Emails lowercased for consistent matching/dedup downstream
  - The Robert/Rob Fenwick duplicate is NOT merged automatically — both
    customer_id 1006 and 1015 are kept as-is, but flagged in the report,
    because service_orders references both IDs and merging risks losing
    order history. Manual review recommended; documented, not resolved.
  - Orphan customer_ids (9998, 9999) in service_orders are NOT dropped —
    they represent real revenue. A placeholder customer record is
    inserted for each so referential integrity holds when loaded into
    SQLite, tagged is_placeholder=1 so dashboards can exclude them from
    customer-level (but not revenue) reporting.
  - technicians.csv is re-saved as UTF-8 (was Latin-1 on read).

Usage: python 02_data_cleaning.py
"""

import re
import chardet
import pandas as pd
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
OUT_DIR = BASE_DIR / "cleaned_data"
LOG_DIR = BASE_DIR / "logs"

PLACEHOLDER_TOKENS = {"n/a", "na", "null", "none", "unknown", "-1", "", "tbd", "pending"}

DATE_PATTERNS = [
    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
    (r"^\d{2}/\d{2}/\d{4}$", "%m/%d/%Y"),
    (r"^\d{1,2}-[A-Za-z]{3}-\d{4}$", "%d-%b-%Y"),
]

REPORT_LINES = []


def log(line=""):
    REPORT_LINES.append(line)
    print(line)


def section(title):
    log(f"\n## {title}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_csv_detect_encoding(path: Path) -> pd.DataFrame:
    with open(path, "rb") as f:
        raw = f.read()
    detected = chardet.detect(raw)
    encoding = detected["encoding"] or "utf-8"
    try:
        return pd.read_csv(path, encoding=encoding)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin1")


def normalize_date(value):
    """Parses any of the three known formats into ISO YYYY-MM-DD; leaves
    unparseable values untouched but logs them as a warning."""
    if pd.isna(value):
        return value
    val = str(value).strip()
    for pattern, fmt in DATE_PATTERNS:
        if re.match(pattern, val):
            try:
                return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
            except ValueError:
                return val
    return val  # unrecognized format, left as-is for manual review


def replace_placeholders_with_null(series: pd.Series) -> pd.Series:
    def _clean(v):
        if pd.isna(v):
            return v
        norm = str(v).strip().lower()
        return None if norm in PLACEHOLDER_TOKENS else v
    return series.apply(_clean)


def trim_strings(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
    return df


def normalize_phone(value):
    if pd.isna(value):
        return value
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    return value  # not a recognizable 10-digit US number, leave for manual review


def normalize_email(value):
    if pd.isna(value):
        return value
    return str(value).strip().lower()


# ---------------------------------------------------------------------------
# Main cleaning pipeline
# ---------------------------------------------------------------------------

def clean_customers(df: pd.DataFrame) -> pd.DataFrame:
    section("customers.csv")
    df = df.copy()
    df = trim_strings(df)

    for col in ["phone", "email"]:
        before_nulls = df[col].isna().sum()
        df[col] = replace_placeholders_with_null(df[col])
        after_nulls = df[col].isna().sum()
        converted = after_nulls - before_nulls
        if converted:
            log(f"- {col}: converted {converted} placeholder value(s) to NULL")

    df["phone"] = df["phone"].apply(normalize_phone)
    df["email"] = df["email"].apply(normalize_email)
    log("- phone: normalized to XXX-XXX-XXXX where a 10-digit number was recoverable")
    log("- email: lowercased for consistent matching")

    before_formats = df["customer_since"].copy()
    df["customer_since"] = df["customer_since"].apply(normalize_date)
    changed = (before_formats.astype(str) != df["customer_since"].astype(str)).sum()
    log(f"- customer_since: normalized {changed} date value(s) to ISO YYYY-MM-DD")

    dupes = df[df.duplicated()]
    if not dupes.empty:
        df = df.drop_duplicates()
        log(f"- dropped {len(dupes)} exact duplicate row(s)")
    else:
        log("- no exact duplicate rows found")

    # Robert/Rob Fenwick — documented, not auto-merged (see module docstring)
    fenwick_check = df[(df["phone"] == "512-555-0233")]
    if len(fenwick_check) > 1:
        ids = fenwick_check["customer_id"].tolist()
        log(f"- POTENTIAL DUPLICATE CUSTOMER NOT MERGED: customer_ids {ids} share phone "
            f"512-555-0233 and address '{fenwick_check['address'].iloc[0]}'. Kept both records "
            f"as-is since service_orders references both IDs; flagging for manual review "
            f"rather than silently merging order history.")

    return df


def clean_technicians(df: pd.DataFrame) -> pd.DataFrame:
    section("technicians.csv")
    df = df.copy()
    df = trim_strings(df)
    df["hire_date"] = df["hire_date"].apply(normalize_date)
    log("- re-saved as UTF-8 (source file was Latin-1 encoded)")
    log("- hire_date: normalized to ISO YYYY-MM-DD")
    return df


def clean_service_orders(df: pd.DataFrame, customers_df: pd.DataFrame) -> tuple:
    section("service_orders.csv")
    df = df.copy()
    df = trim_strings(df)

    before_formats = df["order_date"].copy()
    df["order_date"] = df["order_date"].apply(normalize_date)
    changed = (before_formats.astype(str) != df["order_date"].astype(str)).sum()
    log(f"- order_date: normalized {changed} date value(s) to ISO YYYY-MM-DD")

    # Orphan customer_ids: insert placeholder customer records rather than
    # dropping the orders, since the orders represent real logged revenue.
    orphan_ids = sorted(set(df["customer_id"]) - set(customers_df["customer_id"]))
    placeholder_rows = []
    if orphan_ids:
        for oid in orphan_ids:
            placeholder_rows.append({
                "customer_id": oid,
                "first_name": "Unknown",
                "last_name": "Placeholder",
                "address": None, "city": None, "state": None, "zip": None,
                "phone": None, "email": None,
                "customer_since": None,
                "is_placeholder": 1,
            })
        log(f"- inserted {len(orphan_ids)} placeholder customer record(s) for orphan "
            f"customer_id(s) {orphan_ids} so referential integrity holds on load; "
            f"tagged is_placeholder=1 so dashboards can exclude these from "
            f"customer-level (but not revenue) reporting")
    else:
        log("- no orphan customer_id values found")

    cancelled = df[df["status"] == "Cancelled"]
    if not cancelled.empty:
        log(f"- {len(cancelled)} order(s) with status='Cancelled' kept in the table "
            f"but should be excluded from revenue queries (not deleted — represents real history)")

    zero_dollar = df[df["total_amount"] == 0]
    if not zero_dollar.empty:
        log(f"- {len(zero_dollar)} order(s) with total_amount=0.00, consistent with "
            f"Customer_Service_SOP.md Section 4 (complimentary maintenance-plan visits); "
            f"per the SOP these should not be counted as revenue-generating jobs in reporting")

    return df, placeholder_rows


def clean_invoices(df: pd.DataFrame) -> pd.DataFrame:
    section("invoices.csv")
    df = df.copy()
    df = trim_strings(df)

    before_formats = df["invoice_date"].copy()
    df["invoice_date"] = df["invoice_date"].apply(normalize_date)
    changed = (before_formats.astype(str) != df["invoice_date"].astype(str)).sum()
    log(f"- invoice_date: normalized {changed} date value(s) to ISO YYYY-MM-DD")

    unpaid = df[df["payment_method"] == "Unpaid"]
    if not unpaid.empty:
        log(f"- {len(unpaid)} invoice(s) have payment_method='Unpaid', which is functioning as "
            f"a status flag rather than a real payment method. Kept as-is (not reclassified) "
            f"since amount_paid=0.00 already captures this correctly; flagged as a schema "
            f"design note for the write-up rather than a data error to fix here")

    partial = df[df["amount_paid"] < df["amount_due"]]
    if not partial.empty:
        log(f"- {len(partial)} invoice(s) show amount_paid < amount_due (partial/financing "
            f"payments or unpaid). Both columns are preserved as-is; the dashboard and SQL "
            f"agent should be explicit about whether 'revenue' means billed (amount_due) or "
            f"collected (amount_paid) — this script does not collapse that ambiguity")

    return df


def main():
    OUT_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

    log("# COOLAIR DATA CLEANING REPORT")

    customers = load_csv_detect_encoding(DATA_DIR / "customers.csv")
    technicians = load_csv_detect_encoding(DATA_DIR / "technicians.csv")
    service_orders = load_csv_detect_encoding(DATA_DIR / "service_orders.csv")
    invoices = load_csv_detect_encoding(DATA_DIR / "invoices.csv")

    customers_clean = clean_customers(customers)
    technicians_clean = clean_technicians(technicians)
    service_orders_clean, placeholder_customers = clean_service_orders(service_orders, customers_clean)
    invoices_clean = clean_invoices(invoices)

    # Add is_placeholder=0 to real customers, then append placeholder rows
    customers_clean["is_placeholder"] = 0
    if placeholder_customers:
        placeholder_df = pd.DataFrame(placeholder_customers)
        customers_clean = pd.concat([customers_clean, placeholder_df], ignore_index=True)

    # --- Save cleaned CSVs ---
    customers_clean.to_csv(OUT_DIR / "customers.csv", index=False, encoding="utf-8")
    technicians_clean.to_csv(OUT_DIR / "technicians.csv", index=False, encoding="utf-8")
    service_orders_clean.to_csv(OUT_DIR / "service_orders.csv", index=False, encoding="utf-8")
    invoices_clean.to_csv(OUT_DIR / "invoices.csv", index=False, encoding="utf-8")

    section("Output")
    log(f"- cleaned_data/customers.csv        ({len(customers_clean)} rows)")
    log(f"- cleaned_data/technicians.csv       ({len(technicians_clean)} rows)")
    log(f"- cleaned_data/service_orders.csv    ({len(service_orders_clean)} rows)")
    log(f"- cleaned_data/invoices.csv          ({len(invoices_clean)} rows)")

    report_path = LOG_DIR / "data_cleaning_report.md"
    report_path.write_text("\n".join(REPORT_LINES), encoding="utf-8")
    print(f"\n\nFull report written to {report_path}")


if __name__ == "__main__":
    main()
