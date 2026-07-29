# COOLAIR DATA CLEANING REPORT

## customers.csv
- phone: converted 2 placeholder value(s) to NULL
- phone: normalized to XXX-XXX-XXXX where a 10-digit number was recoverable
- email: lowercased for consistent matching
- customer_since: normalized 11 date value(s) to ISO YYYY-MM-DD
- no exact duplicate rows found
- POTENTIAL DUPLICATE CUSTOMER NOT MERGED: customer_ids [1006, 1015] share phone 512-555-0233 and address '15 Comal Ct'. Kept both records as-is since service_orders references both IDs; flagging for manual review rather than silently merging order history.

## technicians.csv
- re-saved as UTF-8 (source file was Latin-1 encoded)
- hire_date: normalized to ISO YYYY-MM-DD

## service_orders.csv
- order_date: normalized 14 date value(s) to ISO YYYY-MM-DD
- inserted 2 placeholder customer record(s) for orphan customer_id(s) [9998, 9999] so referential integrity holds on load; tagged is_placeholder=1 so dashboards can exclude these from customer-level (but not revenue) reporting
- 1 order(s) with status='Cancelled' kept in the table but should be excluded from revenue queries (not deleted — represents real history)
- 3 order(s) with total_amount=0.00, consistent with Customer_Service_SOP.md Section 4 (complimentary maintenance-plan visits); per the SOP these should not be counted as revenue-generating jobs in reporting

## invoices.csv
- invoice_date: normalized 10 date value(s) to ISO YYYY-MM-DD
- 1 invoice(s) have payment_method='Unpaid', which is functioning as a status flag rather than a real payment method. Kept as-is (not reclassified) since amount_paid=0.00 already captures this correctly; flagged as a schema design note for the write-up rather than a data error to fix here
- 3 invoice(s) show amount_paid < amount_due (partial/financing payments or unpaid). Both columns are preserved as-is; the dashboard and SQL agent should be explicit about whether 'revenue' means billed (amount_due) or collected (amount_paid) — this script does not collapse that ambiguity

## Output
- cleaned_data/customers.csv        (32 rows)
- cleaned_data/technicians.csv       (4 rows)
- cleaned_data/service_orders.csv    (35 rows)
- cleaned_data/invoices.csv          (29 rows)