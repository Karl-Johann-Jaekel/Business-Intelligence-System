"""ERP source: Olist transactional tables in a separate Postgres database (schema `erp`).

Orders, items and payments load incrementally by order purchase timestamp. Master data
(customers, sellers, products) is small and reloaded in full.
"""

from datetime import date, timedelta

from ingestion.base import Connector, Entity, ExtractResult
from ingestion.config import ERP_DSN
from ingestion.db import connect, query_df

_WINDOW = """
    o.order_purchase_timestamp > COALESCE(%(since)s::timestamp, '-infinity')
    AND o.order_purchase_timestamp < %(until_excl)s
"""

_QUERIES = {
    "orders": f"""
        SELECT o.*, o.order_purchase_timestamp AS _wm FROM erp.orders o WHERE {_WINDOW}""",
    "order_items": f"""
        SELECT i.*, o.order_purchase_timestamp AS _wm
        FROM erp.order_items i JOIN erp.orders o USING (order_id) WHERE {_WINDOW}""",
    "payments": f"""
        SELECT p.*, o.order_purchase_timestamp AS _wm
        FROM erp.payments p JOIN erp.orders o USING (order_id) WHERE {_WINDOW}""",
    "customers": "SELECT * FROM erp.customers",
    "sellers": "SELECT * FROM erp.sellers",
    "products": "SELECT * FROM erp.products",
}


class ErpPostgresConnector(Connector):
    source = "erp"
    entities = (
        Entity(
            "orders",
            (
                "order_id",
                "customer_id",
                "order_status",
                "order_purchase_timestamp",
                "order_approved_at",
                "order_delivered_carrier_date",
                "order_delivered_customer_date",
                "order_estimated_delivery_date",
            ),
            "incremental",
        ),
        Entity(
            "order_items",
            (
                "order_id",
                "order_item_id",
                "product_id",
                "seller_id",
                "shipping_limit_date",
                "price",
                "freight_value",
            ),
            "incremental",
        ),
        Entity(
            "payments",
            (
                "order_id",
                "payment_sequential",
                "payment_type",
                "payment_installments",
                "payment_value",
            ),
            "incremental",
        ),
        Entity(
            "customers",
            (
                "customer_id",
                "customer_unique_id",
                "customer_zip_code_prefix",
                "customer_city",
                "customer_state",
            ),
        ),
        Entity("sellers", ("seller_id", "seller_zip_code_prefix", "seller_city", "seller_state")),
        Entity(
            "products",
            (
                "product_id",
                "product_category_name",
                "product_name_lenght",
                "product_description_lenght",
                "product_photos_qty",
                "product_weight_g",
                "product_length_cm",
                "product_height_cm",
                "product_width_cm",
            ),
        ),
    )

    def __init__(self, dsn: str = ERP_DSN):
        self.dsn = dsn

    def extract(self, entity: Entity, since: str | None, until: date) -> ExtractResult:
        params = {"since": since, "until_excl": until + timedelta(days=1)}
        with connect(self.dsn) as conn:
            df = query_df(conn, _QUERIES[entity.name], params)
        if "_wm" not in df.columns:
            return ExtractResult(df)
        watermark = df["_wm"].max() if not df.empty else None
        return ExtractResult(df.drop(columns="_wm"), watermark)
