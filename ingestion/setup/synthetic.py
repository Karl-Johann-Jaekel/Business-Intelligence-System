"""Synthetic sources that Olist lacks. Clearly labelled as synthetic in docs and KPI registry.

- Marketing (served by the mock API): sessions and ad spend per day and channel.
  Sessions are derived from real daily order counts divided by a noisy conversion rate
  with weekly seasonality, so Conversion Rate and ROAS behave plausibly.
- Controlling (Excel): monthly budget per category = real monthly GMV x noisy plan factor.

All randomness uses SYNTHETIC_SEED, so output is reproducible.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from ingestion.config import CONTROLLING_DIR, OLIST_DIR, SYNTHETIC_DIR, SYNTHETIC_SEED
from ingestion.connectors.controlling_excel import BUDGET_FILE, BUDGET_SHEET

# channel: (share of sessions, cost per session in BRL; None = fixed daily cost)
CHANNELS = {
    "organic": (0.40, 0.0),
    "paid_search": (0.30, 0.85),
    "paid_social": (0.18, 0.55),
    "email": (0.12, None),
}
EMAIL_DAILY_COST = 60.0
BASE_CONVERSION_RATE = 0.022
EXCLUDED_STATUSES = ("canceled", "unavailable")


def generate_marketing(orders: pd.DataFrame, seed: int = SYNTHETIC_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    purchase_day = pd.to_datetime(orders["order_purchase_timestamp"]).dt.normalize()
    daily = purchase_day.value_counts().sort_index()
    days = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    orders_per_day = daily.reindex(days, fill_value=0).astype(float)

    # Blend actual and smoothed demand so days without orders still have traffic.
    smooth = orders_per_day.rolling(7, center=True, min_periods=1).mean().clip(lower=1.0)
    demand = 0.6 * orders_per_day + 0.4 * smooth
    weekday_effect = 1 + 0.08 * np.sin(2 * np.pi * days.dayofweek.to_numpy() / 7)
    conversion = BASE_CONVERSION_RATE * weekday_effect * rng.lognormal(0, 0.08, len(days))
    sessions_total = demand.to_numpy() / conversion

    shares = np.array([s for s, _ in CHANNELS.values()])
    split = rng.dirichlet(shares * 200, size=len(days))

    rows = []
    for i, day in enumerate(days):
        for j, (channel, (_, cps)) in enumerate(CHANNELS.items()):
            sessions = int(round(sessions_total[i] * split[i, j]))
            if cps is None:
                spend = EMAIL_DAILY_COST * rng.lognormal(0, 0.15)
            else:
                spend = sessions * cps * rng.lognormal(0, 0.10)
            rows.append((day.date().isoformat(), channel, sessions, round(spend, 2)))
    return pd.DataFrame(rows, columns=["date", "channel", "sessions", "ad_spend"])


def category_en(products: pd.DataFrame, translation: pd.DataFrame) -> pd.Series:
    """Same fallback as dbt dim_product: English name, else Portuguese name, else 'unknown'."""
    mapping = dict(
        zip(translation["product_category_name"], translation["product_category_name_english"], strict=True)
    )
    pt = products["product_category_name"]
    return pt.map(mapping).fillna(pt).fillna("unknown")


def generate_budgets(
    orders: pd.DataFrame,
    items: pd.DataFrame,
    products: pd.DataFrame,
    translation: pd.DataFrame,
    seed: int = SYNTHETIC_SEED,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 1)
    valid = orders[~orders["order_status"].isin(EXCLUDED_STATUSES)]
    df = items.merge(valid[["order_id", "order_purchase_timestamp"]], on="order_id")
    prods = products.assign(category=category_en(products, translation))[["product_id", "category"]]
    df = df.merge(prods, on="product_id", how="left")
    df["month"] = pd.to_datetime(df["order_purchase_timestamp"]).dt.to_period("M").dt.to_timestamp()
    df["price"] = df["price"].astype(float)

    actual = df.groupby(["month", "category"], as_index=False)["price"].sum()
    # Plan only for months with meaningful activity (Olist is sparse before 2017 and after 2018-08).
    actual = actual[(actual["month"] >= "2017-01-01") & (actual["month"] <= "2018-08-01")]
    plan_factor = rng.lognormal(0.02, 0.12, len(actual))
    budget = (actual["price"].to_numpy() * plan_factor / 100).round().clip(min=1) * 100
    return pd.DataFrame(
        {
            "month": actual["month"].dt.date.astype(str).to_numpy(),
            "category": actual["category"].to_numpy(),
            "budget_brl": budget,
        }
    )


def _read(name: str, source_dir: Path) -> pd.DataFrame:
    return pd.read_csv(source_dir / name, dtype=str, encoding="utf-8-sig")


def generate_all(source_dir: Path = OLIST_DIR) -> dict[str, Path]:
    orders = _read("olist_orders_dataset.csv", source_dir)
    items = _read("olist_order_items_dataset.csv", source_dir)
    products = _read("olist_products_dataset.csv", source_dir)
    translation = _read("product_category_name_translation.csv", source_dir)

    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    CONTROLLING_DIR.mkdir(parents=True, exist_ok=True)
    marketing_path = SYNTHETIC_DIR / "marketing_daily.csv"
    generate_marketing(orders).to_csv(marketing_path, index=False)

    budget_path = CONTROLLING_DIR / BUDGET_FILE
    generate_budgets(orders, items, products, translation).to_excel(
        budget_path, sheet_name=BUDGET_SHEET, index=False
    )
    return {"marketing": marketing_path, "budgets": budget_path}


def is_generated() -> bool:
    return (SYNTHETIC_DIR / "marketing_daily.csv").exists() and (CONTROLLING_DIR / BUDGET_FILE).exists()
