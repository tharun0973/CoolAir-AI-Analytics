"""
CoolAir Comfort Services — Load Cleaned Data into SQLite
============================================================
Loads data/*.csv into the schema created by database_setup.py,
using SQLAlchemy so the same code works against Postgres/MySQL later by
just changing the connection string.

After loading, runs verification queries and refuses to exit silently if
row counts don't match the source CSVs or if a foreign key is dangling.
"""

import sys
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, text

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "cleaned_data"
DB_PATH = BASE_DIR / "database" / "coolair.db"

engine = create_engine(f"sqlite:///{DB_PATH}")


# ------------------------------------------------------------
# Load CSV
# ------------------------------------------------------------

def load_table(csv_name: str, table_name: str, dtype_overrides=None):
    csv_path = DATA_DIR / csv_name

    # Try UTF-8 first, then fall back to Latin-1
    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
    except UnicodeDecodeError:
        print(f"{csv_name} is not UTF-8. Reading with latin-1 encoding...")
        df = pd.read_csv(csv_path, encoding="latin-1")

    df.to_sql(
        table_name,
        engine,
        if_exists="append",
        index=False,
        dtype=dtype_overrides,
    )

    print(f"Loaded {len(df)} rows into {table_name} from {csv_name}")
    return df


# ------------------------------------------------------------
# Verification
# ------------------------------------------------------------

def verify_row_counts(expected: dict):
    print("\n--- Row count verification ---")
    ok = True

    with engine.connect() as conn:
        for table, expected_count in expected.items():
            actual = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

            status = "OK" if actual == expected_count else "MISMATCH"

            if actual != expected_count:
                ok = False

            print(
                f"{table}: expected {expected_count}, got {actual} [{status}]"
            )

    return ok


def verify_referential_integrity():
    print("\n--- Referential integrity verification ---")

    ok = True

    checks = [
        (
            "service_orders.customer_id -> customers.customer_id",
            """
            SELECT COUNT(*)
            FROM service_orders so
            LEFT JOIN customers c
            ON so.customer_id = c.customer_id
            WHERE c.customer_id IS NULL
            """,
        ),
        (
            "service_orders.technician_id -> technicians.technician_id",
            """
            SELECT COUNT(*)
            FROM service_orders so
            LEFT JOIN technicians t
            ON so.technician_id = t.technician_id
            WHERE so.technician_id IS NOT NULL
            AND t.technician_id IS NULL
            """,
        ),
        (
            "invoices.order_id -> service_orders.order_id",
            """
            SELECT COUNT(*)
            FROM invoices i
            LEFT JOIN service_orders so
            ON i.order_id = so.order_id
            WHERE so.order_id IS NULL
            """,
        ),
    ]

    with engine.connect() as conn:
        for label, query in checks:
            dangling = conn.execute(text(query)).scalar()

            status = "OK" if dangling == 0 else "DANGLING REFS FOUND"

            if dangling != 0:
                ok = False

            print(f"{label}: {dangling} dangling [{status}]")

    return ok


# ------------------------------------------------------------
# Sample Queries
# ------------------------------------------------------------

def sample_queries():
    print("\n--- Sample query sanity check ---")

    with engine.connect() as conn:

        revenue = conn.execute(
            text(
                """
                SELECT SUM(total_amount)
                FROM service_orders
                WHERE status != 'Cancelled'
                """
            )
        ).scalar()

        print(
            f"Total billed revenue (status != 'Cancelled'): ${revenue:,.2f}"
        )

        by_tech = conn.execute(
            text(
                """
                SELECT
                    t.name,
                    COUNT(*) AS jobs,
                    SUM(so.total_amount) AS revenue
                FROM service_orders so
                JOIN technicians t
                    ON so.technician_id = t.technician_id
                WHERE so.status != 'Cancelled'
                GROUP BY t.name
                ORDER BY revenue DESC
                """
            )
        ).fetchall()

        print("Technician performance:")

        for row in by_tech:
            print(f"  {row[0]}: {row[1]} jobs, ${row[2]:,.2f}")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    if not DB_PATH.exists():
        print("Database not found. Run database_setup.py first.")
        sys.exit(1)

    customers_df = load_table("customers.csv", "customers")
    technicians_df = load_table("technicians.csv", "technicians")
    service_orders_df = load_table("service_orders.csv", "service_orders")
    invoices_df = load_table("invoices.csv", "invoices")

    counts_ok = verify_row_counts(
        {
            "customers": len(customers_df),
            "technicians": len(technicians_df),
            "service_orders": len(service_orders_df),
            "invoices": len(invoices_df),
        }
    )

    integrity_ok = verify_referential_integrity()

    sample_queries()

    if not (counts_ok and integrity_ok):
        print(
            "\nWARNING: verification failed — inspect the mismatches above."
        )
        sys.exit(1)

    print("\nAll verification checks passed.")


if __name__ == "__main__":
    main()