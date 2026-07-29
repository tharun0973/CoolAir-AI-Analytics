"""
CoolAir Comfort Services — Data Audit
======================================
Read-only inspection pass over the raw CSVs. Produces a structured report of
data-quality issues (missing values, placeholder sentinels, inconsistent
date formats, likely duplicate customers, and referential-integrity gaps)
before anything gets loaded into the database.

Design intent: detection logic is generic and config-driven, not hardcoded
to this dataset's specific values. Feeding it a different CSV with a
different placeholder vocabulary ("UNKNOWN", "NULL", etc.) requires only a
config change, not new code paths.

Usage: python 01_data_audit.py
"""

import re
import chardet
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Config — the only place dataset-specific vocabulary lives
# ---------------------------------------------------------------------------

# Tokens treated as "this looks like a missing value someone typed in",
# matched case-insensitively against stripped string values. Extend this
# list for other datasets rather than adding new detection code.
PLACEHOLDER_TOKENS = {"n/a", "na", "null", "none", "unknown", "-1", "", "tbd", "pending"}

# Column name patterns (substring match, case-insensitive) whose values are
# expected to represent dates, so the date-format checker knows where to look.
DATE_COLUMN_HINTS = ("date", "_since")

# Known date formats we can parse; anything matching none of these gets
# flagged as "unrecognized" rather than silently coerced.
DATE_PATTERNS = [
    (r"^\d{4}-\d{2}-\d{2}$", "YYYY-MM-DD"),
    (r"^\d{2}/\d{2}/\d{4}$", "MM/DD/YYYY"),
    (r"^\d{1,2}-[A-Za-z]{3}-\d{4}$", "DD-MMM-YYYY"),
]

REPORT_LINES = []


def log(line=""):
    REPORT_LINES.append(line)
    print(line)


def section(title):
    log(f"\n## {title}")


def subsection(title):
    log(f"\n### {title}")


# ---------------------------------------------------------------------------
# Loading — handles the encoding trap in technicians.csv generically
# ---------------------------------------------------------------------------

def load_csv_detect_encoding(path: Path) -> pd.DataFrame:
    with open(path, "rb") as f:
        raw = f.read()
    detected = chardet.detect(raw)
    encoding = detected["encoding"] or "utf-8"
    try:
        return pd.read_csv(path, encoding=encoding), encoding
    except UnicodeDecodeError:
        # fall back to latin1, which accepts any byte sequence
        return pd.read_csv(path, encoding="latin1"), "latin1 (fallback)"


# ---------------------------------------------------------------------------
# Generic checks
# ---------------------------------------------------------------------------

def check_missing(df: pd.DataFrame) -> pd.Series:
    return df.isnull().sum()


def check_placeholders(df: pd.DataFrame) -> dict:
    """
    Returns {column: [(row_identifier, raw_value), ...]} for any cell whose
    stripped, lowercased value matches PLACEHOLDER_TOKENS. Works on any
    object-dtype column without column-specific code.
    """
    findings = {}
    id_col = df.columns[0]  # assume first column is the row's identifier
    for col in df.columns:
        # pandas 2.x may report string columns as dtype "str" rather than
        # "object" depending on the string-storage backend in use, so check
        # for either rather than assuming legacy object dtype.
        if not (pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col])):
            continue
        hits = []
        for idx, val in df[col].items():
            if pd.isna(val):
                continue
            norm = str(val).strip().lower()
            if norm in PLACEHOLDER_TOKENS:
                hits.append((df.loc[idx, id_col], val))
        if hits:
            findings[col] = hits
    return findings


def check_duplicate_rows(df: pd.DataFrame) -> int:
    return int(df.duplicated().sum())


def classify_date_format(value: str):
    if pd.isna(value):
        return None
    val = str(value).strip()
    for pattern, label in DATE_PATTERNS:
        if re.match(pattern, val):
            return label
    return "UNRECOGNIZED"


def check_date_formats(df: pd.DataFrame) -> dict:
    """Returns {column: {format_label: count}} for every column matching DATE_COLUMN_HINTS."""
    results = {}
    for col in df.columns:
        if any(hint in col.lower() for hint in DATE_COLUMN_HINTS):
            formats = df[col].apply(classify_date_format)
            results[col] = formats.value_counts(dropna=False).to_dict()
    return results


def check_duplicate_customers(df: pd.DataFrame) -> list:
    """
    Flags groups of customers sharing the same (phone, address) pair, since
    a shared phone+address with a different name/email/join-date is the
    signature of the same person entered twice rather than two housemates.
    """
    findings = []
    if not {"phone", "address"}.issubset(df.columns):
        return findings
    valid = df[df["phone"].notna() & ~df["phone"].astype(str).str.strip().str.lower().isin(PLACEHOLDER_TOKENS)]
    grouped = valid.groupby(["phone", "address"])
    for (phone, address), group in grouped:
        if len(group) > 1:
            findings.append({
                "phone": phone,
                "address": address,
                "customers": group[["customer_id", "first_name", "last_name", "email", "customer_since"]].to_dict("records"),
            })
    return findings


def check_referential_integrity(child_df, child_key, parent_df, parent_key, child_label, parent_label):
    """Returns rows in child_df whose child_key value has no match in parent_df[parent_key]."""
    orphans = child_df[~child_df[child_key].isin(parent_df[parent_key])]
    return orphans


def check_status_values(df: pd.DataFrame, column: str, allowed: set):
    if column not in df.columns:
        return {}
    actual = set(df[column].dropna().unique())
    unexpected = actual - allowed
    return {"seen": actual, "unexpected": unexpected, "counts": df[column].value_counts().to_dict()}


def check_amount_validity(df: pd.DataFrame, column: str, min_value=0):
    if column not in df.columns:
        return pd.DataFrame()
    return df[df[column] < min_value]


def check_amount_consistency(df: pd.DataFrame, lesser_col: str, greater_col: str):
    """Flags rows where lesser_col > greater_col, e.g. amount_paid > amount_due."""
    if not {lesser_col, greater_col}.issubset(df.columns):
        return pd.DataFrame()
    return df[df[lesser_col] > df[greater_col]]


def check_zip_codes(df: pd.DataFrame, column: str = "zip"):
    """Flags ZIP codes that aren't a 5-digit numeric string."""
    if column not in df.columns:
        return pd.DataFrame()
    invalid_mask = ~df[column].astype(str).str.strip().str.match(r"^\d{5}$")
    return df[invalid_mask]


def check_duplicate_values(df: pd.DataFrame, column: str, id_col: str = None):
    """
    Flags exact duplicate values in a column (e.g. same email or phone used
    by more than one row), case-insensitive for strings. Distinct from
    check_duplicate_customers, which looks for a phone+address pair — this
    catches the same phone/email reused even with a different address.
    """
    if column not in df.columns:
        return []
    id_col = id_col or df.columns[0]
    valid = df[df[column].notna() & ~df[column].astype(str).str.strip().str.lower().isin(PLACEHOLDER_TOKENS)]
    normalized = valid[column].astype(str).str.strip().str.lower()
    dupe_values = normalized[normalized.duplicated(keep=False)]
    findings = []
    for val in dupe_values.unique():
        matching_ids = valid.loc[normalized == val, id_col].tolist()
        findings.append({"value": val, "ids": matching_ids})
    return findings


def check_negative_amounts(df: pd.DataFrame, columns: list, id_col: str = None):
    """Flags rows with a negative value in any of the given amount columns."""
    id_col = id_col or df.columns[0]
    findings = []
    for col in columns:
        if col not in df.columns:
            continue
        bad = df[df[col] < 0]
        for _, row in bad.iterrows():
            findings.append({"id": row[id_col], "column": col, "value": row[col]})
    return findings


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_email_format(df: pd.DataFrame, column: str = "email", id_col: str = None):
    """
    Flags non-null, non-placeholder email values that don't match a basic
    name@domain.tld shape. Deliberately loose (not RFC 5322-strict) — the
    goal is catching obvious typos/garbage, not rejecting valid edge cases.
    """
    if column not in df.columns:
        return []
    id_col = id_col or df.columns[0]
    findings = []
    for idx, val in df[column].items():
        if pd.isna(val):
            continue
        norm = str(val).strip()
        if norm.lower() in PLACEHOLDER_TOKENS:
            continue
        if not EMAIL_PATTERN.match(norm):
            findings.append({"id": df.loc[idx, id_col], "value": val})
    return findings


PHONE_FORMAT_PATTERNS = [
    (r"^\d{3}-\d{3}-\d{4}$", "XXX-XXX-XXXX"),
    (r"^\d{10}$", "XXXXXXXXXX"),
    (r"^\(\d{3}\)\s?\d{3}-?\d{4}$", "(XXX) XXX-XXXX"),
    (r"^\d{3}\.\d{3}\.\d{4}$", "XXX.XXX.XXXX"),
]


def check_phone_format_preview(df: pd.DataFrame, column: str = "phone", id_col: str = None):
    """
    Reports which formatting patterns are present in the phone column —
    detection only, no normalization here. 02_data_cleaning.py is where
    these actually get standardized; this just tells you up front that
    more than one format exists so it isn't a surprise later.
    """
    if column not in df.columns:
        return {}
    id_col = id_col or df.columns[0]
    format_counts = {}
    unrecognized = []
    for idx, val in df[column].items():
        if pd.isna(val):
            continue
        norm = str(val).strip()
        if norm.lower() in PLACEHOLDER_TOKENS:
            continue
        matched = False
        for pattern, label in PHONE_FORMAT_PATTERNS:
            if re.match(pattern, norm):
                format_counts[label] = format_counts.get(label, 0) + 1
                matched = True
                break
        if not matched:
            unrecognized.append((df.loc[idx, id_col], norm))
    return {"format_counts": format_counts, "unrecognized": unrecognized}


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def main():
    summary = {
        "datasets": 0,
        "missing_values": 0,
        "placeholder_values": 0,
        "broken_foreign_keys": 0,
        "potential_duplicates": 0,
        "unmatched_invoices": 0,
        "amount_inconsistencies": 0,
    }

    section("COOLAIR DATA AUDIT REPORT")

    # --- Load all four files, tracking encoding used ---
    customers, cust_enc = load_csv_detect_encoding(DATA_DIR / "customers.csv")
    technicians, tech_enc = load_csv_detect_encoding(DATA_DIR / "technicians.csv")
    service_orders, so_enc = load_csv_detect_encoding(DATA_DIR / "service_orders.csv")
    invoices, inv_enc = load_csv_detect_encoding(DATA_DIR / "invoices.csv")
    summary["datasets"] = 4

    datasets = {
        "customers.csv": (customers, cust_enc),
        "technicians.csv": (technicians, tech_enc),
        "service_orders.csv": (service_orders, so_enc),
        "invoices.csv": (invoices, inv_enc),
    }

    # --- Per-file generic checks ---
    for name, (df, enc) in datasets.items():
        section(name)
        log(f"Rows: {len(df)}   Columns: {len(df.columns)}   Encoding detected: {enc}")

        subsection("Missing Values")
        missing = check_missing(df)
        missing = missing[missing > 0]
        if missing.empty:
            log("(none)")
        else:
            for col, count in missing.items():
                log(f"{col} : {count}")
                summary["missing_values"] += int(count)

        subsection("Placeholder Values")
        placeholders = check_placeholders(df)
        if not placeholders:
            log("(none)")
        else:
            id_col = df.columns[0]
            for col, hits in placeholders.items():
                for row_id, raw_val in hits:
                    shown = "Blank" if str(raw_val).strip() == "" else raw_val
                    log(f"{id_col}={row_id}  {col} -> {shown}")
                    summary["placeholder_values"] += 1

        subsection("Duplicate Rows (exact)")
        dupes = check_duplicate_rows(df)
        log(str(dupes))

        date_formats = check_date_formats(df)
        if date_formats:
            subsection("Date Format Consistency")
            for col, formats in date_formats.items():
                log(f"{col}:")
                for fmt, count in formats.items():
                    log(f"  {fmt} : {count}")
                if len([f for f in formats if f != "UNRECOGNIZED"]) > 1:
                    log("  -> Multiple formats in use. Recommend normalizing to ISO (YYYY-MM-DD) on load.")

    # --- customers.csv: duplicate-customer heuristic ---
    subsection("Potential Duplicate Customers (same phone + address)")
    dup_customers = check_duplicate_customers(customers)
    if not dup_customers:
        log("(none found)")
    else:
        for group in dup_customers:
            log(f"phone={group['phone']}  address={group['address']}")
            for c in group["customers"]:
                log(f"   customer_id={c['customer_id']}  {c['first_name']} {c['last_name']}  "
                    f"email={c['email']}  since={c['customer_since']}")
            summary["potential_duplicates"] += 1

    # --- customers.csv: additional field-level checks ---
    subsection("ZIP Code Validation (customers)")
    bad_zips = check_zip_codes(customers, "zip")
    if bad_zips.empty:
        log("(none — all ZIPs are 5-digit numeric)")
    else:
        for _, row in bad_zips.iterrows():
            log(f"customer_id={row['customer_id']}  zip={row['zip']!r}")

    subsection("Duplicate Emails (customers)")
    dupe_emails = check_duplicate_values(customers, "email", "customer_id")
    if not dupe_emails:
        log("(none)")
    else:
        for d in dupe_emails:
            log(f"email={d['value']}  customer_ids={d['ids']}")

    subsection("Email Format Validation (customers)")
    bad_emails = check_email_format(customers, "email", "customer_id")
    if not bad_emails:
        log("(none — all non-placeholder emails match name@domain.tld shape)")
    else:
        for f in bad_emails:
            log(f"customer_id={f['id']}  email={f['value']!r}  -> does not match expected email format")

    subsection("Phone Format Preview (customers) — detection only, standardized in 02_data_cleaning.py")
    phone_preview = check_phone_format_preview(customers, "phone", "customer_id")
    if phone_preview.get("format_counts"):
        for label, count in phone_preview["format_counts"].items():
            log(f"{label} : {count}")
    if phone_preview.get("unrecognized"):
        log("Unrecognized formats:")
        for cust_id, val in phone_preview["unrecognized"]:
            log(f"  customer_id={cust_id}  phone={val!r}")
    if len(phone_preview.get("format_counts", {})) > 1:
        log("-> Multiple phone formats in use. Will be standardized to XXX-XXX-XXXX in 02_data_cleaning.py.")

    subsection("Duplicate Phones (customers)")
    dupe_phones = check_duplicate_values(customers, "phone", "customer_id")
    if not dupe_phones:
        log("(none)")
    else:
        for d in dupe_phones:
            log(f"phone={d['value']}  customer_ids={d['ids']}")

    subsection("Negative Amounts (invoices: amount_due, amount_paid)")
    neg_invoice = check_negative_amounts(invoices, ["amount_due", "amount_paid"], "invoice_id")
    if not neg_invoice:
        log("(none)")
    else:
        for f in neg_invoice:
            log(f"invoice_id={f['id']}  {f['column']}={f['value']}")
            summary["amount_inconsistencies"] += 1

    # --- Referential integrity ---
    section("REFERENTIAL INTEGRITY")

    subsection("service_orders -> customers (orphaned customer_id, grouped)")
    orphan_cust = check_referential_integrity(service_orders, "customer_id", customers, "customer_id",
                                               "service_orders", "customers")
    if orphan_cust.empty:
        log("(none)")
    else:
        for cust_id, group in orphan_cust.groupby("customer_id"):
            affected = group["order_id"].tolist()
            log(f"Customer ID {cust_id}  ->  Affected Orders: {affected}")
            summary["broken_foreign_keys"] += len(affected)

    subsection("service_orders -> technicians (orphaned technician_id)")
    orphan_tech = check_referential_integrity(service_orders, "technician_id", technicians, "technician_id",
                                               "service_orders", "technicians")
    if orphan_tech.empty:
        log("(none)")
    else:
        for _, row in orphan_tech.iterrows():
            log(f"technician_id {row['technician_id']}  referenced by order_id {row['order_id']}")
            summary["broken_foreign_keys"] += 1

    subsection("invoices -> service_orders (orphaned order_id)")
    orphan_inv = check_referential_integrity(invoices, "order_id", service_orders, "order_id",
                                              "invoices", "service_orders")
    if orphan_inv.empty:
        log("(none)")
    else:
        for _, row in orphan_inv.iterrows():
            log(f"order_id {row['order_id']}  referenced by invoice_id {row['invoice_id']}")
            summary["broken_foreign_keys"] += 1

    subsection("service_orders with no matching invoice")
    missing_inv = service_orders[~service_orders["order_id"].isin(invoices["order_id"])]
    if missing_inv.empty:
        log("(none)")
    else:
        for _, row in missing_inv.iterrows():
            flag = ""
            if row["status"] == "Cancelled":
                flag = " (expected — cancelled order)"
            elif row["total_amount"] == 0:
                flag = " (expected — $0 order, likely maintenance-plan visit per SOP)"
            else:
                flag = " (UNEXPECTED — nonzero, non-cancelled order missing an invoice)"
                summary["unmatched_invoices"] += 1
            log(f"order_id {row['order_id']}  customer_id {row['customer_id']}  "
                f"amount {row['total_amount']}  status {row['status']}{flag}")

    # --- Status / amount validation ---
    section("VALUE VALIDATION")

    subsection("service_orders.status")
    status_check = check_status_values(service_orders, "status", {"Completed", "Cancelled", "Pending"})
    log(f"Values seen: {status_check['counts']}")
    if status_check["unexpected"]:
        log(f"Unexpected values: {status_check['unexpected']}")

    subsection("invoices.payment_method")
    pm_check = check_status_values(invoices, "payment_method",
                                    {"Credit Card", "Debit Card", "Check", "Cash", "Financing"})
    log(f"Values seen: {pm_check['counts']}")
    if pm_check["unexpected"]:
        log(f"Non-standard values (may indicate unpaid/edge case): {pm_check['unexpected']}")

    subsection("Negative amounts (service_orders.total_amount)")
    bad_amounts = check_amount_validity(service_orders, "total_amount", min_value=0)
    log("(none)" if bad_amounts.empty else bad_amounts.to_string())

    subsection("amount_paid > amount_due (invoices)")
    bad_payments = check_amount_consistency(invoices, "amount_due", "amount_paid")
    # note: check flags lesser_col > greater_col, we want amount_paid > amount_due
    bad_payments = invoices[invoices["amount_paid"] > invoices["amount_due"]]
    if bad_payments.empty:
        log("(none)")
    else:
        log(bad_payments.to_string())
        summary["amount_inconsistencies"] += len(bad_payments)

    subsection("Partial payments (amount_paid < amount_due, excluding $0 due)")
    partial = invoices[(invoices["amount_paid"] < invoices["amount_due"])]
    if partial.empty:
        log("(none)")
    else:
        log(partial.to_string())
        log("-> Revenue metric is ambiguous here: 'amount_due' (billed) vs 'amount_paid' (collected) diverge. "
            "State which one the dashboard uses.")

    # --- Executive summary ---
    section("EXECUTIVE SUMMARY")
    for key, val in summary.items():
        log(f"{key.replace('_', ' ').title()} : {val}")

    log("\nRecommendation: clean per findings above before loading into SQLite. "
        "See 02_data_cleaning.py for the transformation applied to each item.")

    # write report to file
    report_path = Path(__file__).resolve().parent.parent / "logs" / "data_audit_report.md"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text("\n".join(REPORT_LINES), encoding="utf-8")
    print(f"\n\nFull report written to {report_path}")


if __name__ == "__main__":
    main()
