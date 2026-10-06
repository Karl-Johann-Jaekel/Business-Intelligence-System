"""Download the public Olist dataset (CC BY-NC-SA 4.0) into data/olist. Never committed."""

import shutil
from pathlib import Path

from ingestion.config import OLIST_DIR

KAGGLE_DATASET = "olistbr/brazilian-ecommerce"
EXPECTED_FILES = (
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
)


def is_downloaded(target: Path = OLIST_DIR) -> bool:
    return all((target / f).exists() for f in EXPECTED_FILES)


def download(target: Path = OLIST_DIR) -> Path:
    if is_downloaded(target):
        return target
    import kagglehub

    cache = Path(kagglehub.dataset_download(KAGGLE_DATASET))
    target.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED_FILES:
        shutil.copy2(cache / name, target / name)
    return target
