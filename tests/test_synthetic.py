import numpy as np
import pandas as pd

from ingestion.setup.synthetic import (
    BASE_CONVERSION_RATE,
    CHANNELS,
    category_en,
    generate_budgets,
    generate_marketing,
)


def _orders(days: int = 60, per_day: int = 50) -> pd.DataFrame:
    stamps = pd.date_range("2018-01-01", periods=days, freq="D").repeat(per_day)
    return pd.DataFrame(
        {
            "order_id": [f"o{i}" for i in range(len(stamps))],
            "order_status": "delivered",
            "order_purchase_timestamp": stamps.astype(str),
        }
    )


def test_marketing_is_deterministic():
    orders = _orders()
    pd.testing.assert_frame_equal(generate_marketing(orders), generate_marketing(orders))


def test_marketing_has_every_channel_every_day_and_plausible_conversion():
    df = generate_marketing(_orders())
    assert set(df["channel"]) == set(CHANNELS)
    assert len(df) == 60 * len(CHANNELS)

    conversion = 50 / df.groupby("date")["sessions"].sum()
    assert np.isclose(conversion.median(), BASE_CONVERSION_RATE, rtol=0.2)
    assert (df.loc[df["channel"] == "organic", "ad_spend"] == 0).all()


def test_category_falls_back_to_portuguese_then_unknown():
    products = pd.DataFrame({"product_category_name": ["beleza_saude", "pc_gamer", None]})
    translation = pd.DataFrame(
        {
            "product_category_name": ["beleza_saude"],
            "product_category_name_english": ["health_beauty"],
        }
    )
    assert list(category_en(products, translation)) == ["health_beauty", "pc_gamer", "unknown"]


def test_budgets_are_rounded_and_exclude_canceled_orders():
    orders = pd.DataFrame(
        {
            "order_id": ["a", "b"],
            "order_status": ["delivered", "canceled"],
            "order_purchase_timestamp": ["2018-02-03 10:00:00", "2018-02-04 10:00:00"],
        }
    )
    items = pd.DataFrame(
        {"order_id": ["a", "b"], "product_id": ["p1", "p1"], "price": ["1000.00", "9999.00"]}
    )
    products = pd.DataFrame({"product_id": ["p1"], "product_category_name": ["beleza_saude"]})
    translation = pd.DataFrame(
        {
            "product_category_name": ["beleza_saude"],
            "product_category_name_english": ["health_beauty"],
        }
    )

    budgets = generate_budgets(orders, items, products, translation)

    assert len(budgets) == 1
    row = budgets.iloc[0]
    assert row["month"] == "2018-02-01" and row["category"] == "health_beauty"
    assert row["budget_brl"] % 100 == 0
    assert 500 <= row["budget_brl"] <= 2000
