"""
CoolAir Comfort Services — SQL Agent
========================================
Converts a natural-language question into SQL via an LLM, then executes it
through two independent safety layers before returning results:

  1. sqlglot parses the generated SQL into an AST and rejects anything that
     isn't a pure SELECT (catches stacked statements, DDL/DML hidden in a
     CTE, etc. — a regex on keywords alone would miss these).
  2. The SQLite connection itself is opened in read-only mode at the OS
     level (file:...?mode=ro), so even a query that somehow slipped past
     the parser is physically unable to write to disk.

Requires a GROQ_API_KEY in your environment / .env file for the
natural-language-to-SQL step (see app/utils/config.py — LLM_PROVIDER
must be set to "groq"). The safety layer and execution path work and are
tested independently of that key — see `if __name__ == "__main__"` at
the bottom for a self-contained safety-layer test that runs with no API
key at all.

Usage: python 06_sql_agent.py
"""

import sys
import sqlite3
import sqlglot
from sqlglot import exp
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2] # project root (coolair-ai-poc/)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))  # so `python 06_sql_agent.py` finds the app package

from groq import Groq
from app.utils.config import GROQ_API_KEY, LLM_MODEL, require_llm_key

DB_PATH = BASE_DIR / "database" / "coolair.db"

SCHEMA_DESCRIPTION = """
Tables:
customers(customer_id, first_name, last_name, address, city, state, zip, phone, email, customer_since, is_placeholder)
technicians(technician_id, name, specialty, hire_date)
service_orders(order_id, customer_id, order_date, service_type, technician_id, total_amount, status)
invoices(invoice_id, order_id, amount_due, amount_paid, invoice_date, payment_method)

Notes:
- service_orders.status can be 'Completed' or 'Cancelled'. Exclude 'Cancelled' from revenue queries unless asked otherwise.
- service_orders with total_amount = 0.00 are complimentary maintenance-plan visits (per Customer_Service_SOP.md)
  and should be excluded from revenue-generating job counts unless the question is specifically about maintenance visits.
- customers.is_placeholder = 1 marks synthetic rows backfilled for orders that referenced a missing customer_id.
  Exclude these from customer-level reporting (e.g. "top customers") unless asked about all orders including unknown customers.
- invoices.amount_due is billed revenue; invoices.amount_paid is collected revenue. These differ for partial/financing
  payments — state which one you used if the question just says "revenue".
"""


class UnsafeQueryError(Exception):
    pass


def is_safe_select(sql: str) -> bool:
    """
    Returns True only if every statement in the given SQL text parses as a
    pure SELECT with no destructive operation anywhere in its tree — including
    nested inside a CTE (e.g. "WITH x AS (DELETE ... RETURNING *) SELECT * FROM x"
    parses with an outer Select node, so a top-level-only type check would miss
    the nested DELETE; this walks the entire AST instead).
    """
    try:
        parsed = sqlglot.parse(sql, read="sqlite")
    except Exception:
        return False  # unparseable input is rejected, not given the benefit of the doubt

    if not parsed:
        return False

    destructive_types = (
        exp.Delete, exp.Update, exp.Insert, exp.Drop, exp.Create,
        exp.Alter, exp.TruncateTable, exp.Attach, exp.Detach,
    )

    for statement in parsed:
        if statement is None:
            continue
        if not isinstance(statement, exp.Select):
            return False
        if statement.find(*destructive_types) is not None:
            return False
    return True


def safe_execute(sql: str, params: tuple = ()) -> list:
    """
    Validates via sqlglot, then executes against a read-only SQLite
    connection opened with mode=ro at the OS level — a second, independent
    layer that holds even if a query somehow bypasses the parser check.
    """
    if not is_safe_select(sql):
        raise UnsafeQueryError(f"Rejected non-SELECT or unparseable query: {sql!r}")

    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.execute(sql, params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def natural_language_to_sql(question: str) -> str:
    """
    Sends the question + schema description to an LLM and returns the
    generated SQL text.
    """
    require_llm_key()

    client = Groq(api_key=GROQ_API_KEY)

    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        max_tokens=300,
        messages=[
            {
                "role": "system",
                "content": f"""
You are an expert SQLite SQL generator.

Generate ONLY a valid SQLite SELECT query.

Rules:
- Return ONLY SQL.
- Never use DELETE, UPDATE, INSERT, DROP, ALTER, CREATE or TRUNCATE.
- Use only the schema below.

Important business rules:
- service_orders.status = 'Cancelled' should be excluded from revenue calculations unless the user explicitly asks for cancelled orders.
- total_amount represents billed revenue from service orders.
- invoices.amount_paid represents collected revenue.
- If the user asks for "revenue" without clarification, calculate billed revenue using service_orders.total_amount and mention the assumption.
- customers with is_placeholder = 1 are synthetic records created for missing customer IDs.
- Exclude placeholder customers from customer-level reporting unless the user asks for all database records.
- For customer count questions, exclude placeholder customers by default and mention that placeholder customers were excluded.

Schema:
{SCHEMA_DESCRIPTION}
"""
            },
            {
                "role": "user",
                "content": question
            }
        ]
    )

    sql = response.choices[0].message.content.strip()

    sql = sql.replace("```sql", "").replace("```", "").strip()

    return sql


def answer_question(question: str) -> dict:
    sql = natural_language_to_sql(question)
    try:
        results = safe_execute(sql)
        return {"question": question, "sql": sql, "results": results, "blocked": False}
    except UnsafeQueryError as e:
        return {"question": question, "sql": sql, "results": None, "blocked": True, "reason": str(e)}
    
class SQLAgent:
    """
    Wrapper class for the SQL agent.
    """

    def answer_question(self, question: str) -> dict:
        return answer_question(question)

# ---------------------------------------------------------------------------
# Self-contained safety-layer test — runs with no API key, no LLM call.
# This is what to run/demo to prove the safety mechanism works on its own.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_cases = [
        ("SELECT * FROM customers LIMIT 5", True),
        ("SELECT SUM(total_amount) FROM service_orders WHERE status != 'Cancelled'", True),
        ("DROP TABLE customers", False),
        ("SELECT * FROM customers; DROP TABLE customers;", False),
        ("DELETE FROM invoices WHERE invoice_id = 9001", False),
        ("UPDATE customers SET email = 'x' WHERE customer_id = 1001", False),
        ("WITH x AS (DELETE FROM customers RETURNING *) SELECT * FROM x", False),
        ("not even valid sql at all $$$", False),
    ]

    print("=== SQL Safety Layer Test (no API key required) ===\n")
    all_passed = True
    for sql, expected_safe in test_cases:
        actual_safe = is_safe_select(sql)
        status = "PASS" if actual_safe == expected_safe else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"[{status}] safe={actual_safe} (expected {expected_safe})  ::  {sql}")

    print("\n=== Read-only connection test ===")
    try:
        safe_execute("DROP TABLE customers")
        print("[FAIL] DROP was not blocked by is_safe_select")
    except UnsafeQueryError:
        print("[PASS] DROP correctly rejected by the parser layer before touching the DB")

    print("\n=== Legitimate query execution test ===")
    results = safe_execute("SELECT COUNT(*) as n FROM customers")
    print(f"[PASS] SELECT executed successfully: {results}")

    print(f"\nAll safety tests passed: {all_passed}")