"""Load Olist transactional CSVs into the simulated ERP database (typed tables)."""

from pathlib import Path

from psycopg import sql

from ingestion.config import OLIST_DIR, erp_dsn
from ingestion.db import connect

ERP_DDL = """
DROP SCHEMA IF EXISTS erp CASCADE;
CREATE SCHEMA erp;

CREATE TABLE erp.customers (
    customer_id               text PRIMARY KEY,
    customer_unique_id        text NOT NULL,
    customer_zip_code_prefix  text,
    customer_city             text,
    customer_state            char(2)
);
CREATE TABLE erp.sellers (
    seller_id               text PRIMARY KEY,
    seller_zip_code_prefix  text,
    seller_city             text,
    seller_state            char(2)
);
CREATE TABLE erp.products (
    product_id                  text PRIMARY KEY,
    product_category_name       text,
    product_name_lenght         integer,
    product_description_lenght  integer,
    product_photos_qty          integer,
    product_weight_g            numeric,
    product_length_cm           numeric,
    product_height_cm           numeric,
    product_width_cm            numeric
);
CREATE TABLE erp.orders (
    order_id                       text PRIMARY KEY,
    customer_id                    text NOT NULL REFERENCES erp.customers,
    order_status                   text NOT NULL,
    order_purchase_timestamp       timestamp NOT NULL,
    order_approved_at              timestamp,
    order_delivered_carrier_date   timestamp,
    order_delivered_customer_date  timestamp,
    order_estimated_delivery_date  timestamp
);
CREATE INDEX orders_purchase_idx ON erp.orders (order_purchase_timestamp);
CREATE TABLE erp.order_items (
    order_id             text NOT NULL REFERENCES erp.orders,
    order_item_id        integer NOT NULL,
    product_id           text NOT NULL REFERENCES erp.products,
    seller_id            text NOT NULL REFERENCES erp.sellers,
    shipping_limit_date  timestamp,
    price                numeric(12, 2) NOT NULL,
    freight_value        numeric(12, 2) NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);
CREATE TABLE erp.payments (
    order_id              text NOT NULL REFERENCES erp.orders,
    payment_sequential    integer NOT NULL,
    payment_type          text NOT NULL,
    payment_installments  integer,
    payment_value         numeric(12, 2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);
"""

# Load order respects foreign keys.
TABLE_FILES = (
    ("customers", "olist_customers_dataset.csv"),
    ("sellers", "olist_sellers_dataset.csv"),
    ("products", "olist_products_dataset.csv"),
    ("orders", "olist_orders_dataset.csv"),
    ("order_items", "olist_order_items_dataset.csv"),
    ("payments", "olist_order_payments_dataset.csv"),
)


def is_seeded(dsn: str | None = None) -> bool:
    with connect(dsn or erp_dsn()) as conn:
        exists = conn.execute("SELECT to_regclass('erp.payments') IS NOT NULL").fetchone()[0]
        return bool(exists) and conn.execute("SELECT count(*) FROM erp.payments").fetchone()[0] > 0


def seed(source_dir: Path = OLIST_DIR, dsn: str | None = None) -> dict[str, int]:
    counts = {}
    with connect(dsn or erp_dsn()) as conn:
        conn.execute(ERP_DDL)
        for table, filename in TABLE_FILES:
            stmt = sql.SQL("COPY {} FROM STDIN WITH (FORMAT csv, HEADER true)").format(
                sql.Identifier("erp", table)
            )
            with conn.cursor() as cur, cur.copy(stmt) as copy, open(source_dir / filename, "rb") as fh:
                while chunk := fh.read(1 << 20):
                    copy.write(chunk)
            counts[table] = conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("erp", table))
            ).fetchone()[0]
        conn.commit()
    return counts
