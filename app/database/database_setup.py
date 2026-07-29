"""
CoolAir Comfort Services — Database Setup
============================================
Creates the SQLite schema, deliberately deviating from the legacy
schema.sql where the audit found reasons to. Every deviation is commented
inline with why.

Deviations from the legacy schema.sql:
  - total_amount, amount_due, amount_paid: INT -> NUMERIC(10,2).
    The legacy schema declared these as INT, but the actual data has
    cents (e.g. 189.50). Loading as INT would silently truncate money.
  - customers: added is_placeholder INTEGER DEFAULT 0, to support the
    placeholder rows inserted in 02_data_cleaning.py for orphan
    customer_ids referenced by real orders.
  - Added explicit FOREIGN KEY constraints (the legacy schema had none),
    plus indexes on the FK columns since those are the join paths the
    SQL agent and Power BI will use most.
  - service_orders.status and invoices.payment_method: left as free-text
    VARCHAR rather than an ENUM/CHECK constraint, since the audit found
    an unexpected value ('Unpaid' as a payment_method) that a strict
    CHECK would have rejected on load. Validated at the application layer
    instead (see 01_data_audit.py's VALUE VALIDATION section).

Usage: python database_setup.py
"""

import sqlite3
from pathlib import Path

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "database" / "coolair.db"

# ------------------------------------------------------------
# Schema
# ------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id     INTEGER PRIMARY KEY,
    first_name      VARCHAR(50),
    last_name       VARCHAR(50),
    address         VARCHAR(150),
    city            VARCHAR(50),
    state           VARCHAR(2),
    zip             VARCHAR(10),
    phone           VARCHAR(20),
    email           VARCHAR(100),
    customer_since  DATE,
    is_placeholder  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS technicians (
    technician_id   INTEGER PRIMARY KEY,
    name            VARCHAR(100),
    specialty       VARCHAR(50),
    hire_date       DATE
);

CREATE TABLE IF NOT EXISTS service_orders (
    order_id        INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL,
    order_date      DATE,
    service_type    VARCHAR(50),
    technician_id   INTEGER,
    total_amount    NUMERIC(10,2),
    status          VARCHAR(20),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (technician_id) REFERENCES technicians(technician_id)
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id      INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL,
    amount_due      NUMERIC(10,2),
    amount_paid     NUMERIC(10,2),
    invoice_date    DATE,
    payment_method  VARCHAR(30),
    FOREIGN KEY (order_id) REFERENCES service_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_customer
ON service_orders(customer_id);

CREATE INDEX IF NOT EXISTS idx_orders_technician
ON service_orders(technician_id);

CREATE INDEX IF NOT EXISTS idx_orders_date
ON service_orders(order_date);

CREATE INDEX IF NOT EXISTS idx_invoices_order
ON invoices(order_id);
"""

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    DB_PATH.parent.mkdir(exist_ok=True)

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    conn.commit()

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()

    print(f"Database created at {DB_PATH}")
    print("Tables:", [t[0] for t in tables])

    conn.close()


if __name__ == "__main__":
    main()