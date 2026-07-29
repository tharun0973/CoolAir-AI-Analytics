-- CoolAir Comfort Services — Starter Database Schema
-- This is the schema used by our legacy reporting scripts. It has been
-- handed down from the previous vendor with minimal documentation.
-- You are free to use it as-is, extend it, or redesign it entirely —
-- just document what you changed and why.

CREATE TABLE customers (
    customer_id     INTEGER PRIMARY KEY,
    first_name      VARCHAR(50),
    last_name       VARCHAR(50),
    address         VARCHAR(150),
    city            VARCHAR(50),
    state           VARCHAR(2),
    zip             VARCHAR(10),
    phone           VARCHAR(20),
    email           VARCHAR(100),
    customer_since  DATE
);

CREATE TABLE technicians (
    technician_id   INTEGER PRIMARY KEY,
    name            VARCHAR(100),
    specialty       VARCHAR(50),
    hire_date       DATE
);

CREATE TABLE service_orders (
    order_id        INTEGER PRIMARY KEY,
    customer_id     INTEGER,
    order_date      DATE,
    service_type    VARCHAR(50),
    technician_id   INTEGER,
    total_amount    INT,              -- matches finance export format
    status          VARCHAR(20)
);

CREATE TABLE invoices (
    invoice_id      INTEGER PRIMARY KEY,
    order_id        INTEGER,
    amount_due      INT,
    amount_paid     INT,
    invoice_date    DATE,
    payment_method  VARCHAR(30)
);

-- Load order (matches the CSVs in /data):
--   customers.csv -> customers
--   technicians.csv -> technicians
--   service_orders.csv -> service_orders
--   invoices.csv -> invoices
