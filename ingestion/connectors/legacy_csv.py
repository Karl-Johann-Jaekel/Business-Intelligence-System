"""Legacy CSV export: reviews (incremental by creation date), geodata and category translation."""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ingestion.base import Connector, Entity, ExtractResult
from ingestion.config import OLIST_DIR

_FILES = {
    "reviews": "olist_order_reviews_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


class LegacyCsvConnector(Connector):
    source = "legacy"
    entities = (
        Entity(
            "reviews",
            (
                "review_id",
                "order_id",
                "review_score",
                "review_comment_title",
                "review_comment_message",
                "review_creation_date",
                "review_answer_timestamp",
            ),
            "incremental",
        ),
        Entity(
            "geolocation",
            (
                "geolocation_zip_code_prefix",
                "geolocation_lat",
                "geolocation_lng",
                "geolocation_city",
                "geolocation_state",
            ),
        ),
        Entity("category_translation", ("product_category_name", "product_category_name_english")),
    )

    def __init__(self, directory: Path = OLIST_DIR):
        self.directory = directory

    def extract(self, entity: Entity, since: str | None, until: date) -> ExtractResult:
        df = pd.read_csv(self.directory / _FILES[entity.name], dtype=str, encoding="utf-8-sig")
        if entity.name != "reviews":
            return ExtractResult(df)

        # Timestamps are ISO formatted, so string comparison is chronological.
        ts = df["review_creation_date"]
        mask = ts < (until + timedelta(days=1)).isoformat()
        if since is not None:
            mask &= ts > since
        df = df[mask]
        return ExtractResult(df, ts[mask].max() if not df.empty else None)
