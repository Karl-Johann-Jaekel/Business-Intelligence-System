from datetime import date

import httpx
import pandas as pd

from ingestion.connectors.legacy_csv import LegacyCsvConnector
from ingestion.connectors.marketing_api import MarketingApiConnector


def _write_reviews(directory):
    pd.DataFrame(
        {
            "review_id": ["r1", "r2", "r3"],
            "order_id": ["o1", "o2", "o3"],
            "review_score": ["5", "3", "1"],
            "review_comment_title": [None, None, None],
            "review_comment_message": [None, None, None],
            "review_creation_date": ["2018-01-01 00:00:00", "2018-01-02 00:00:00", "2018-01-03 00:00:00"],
            "review_answer_timestamp": [None, None, None],
        }
    ).to_csv(directory / "olist_order_reviews_dataset.csv", index=False)


def test_reviews_are_cut_at_sim_date(tmp_path):
    _write_reviews(tmp_path)
    connector = LegacyCsvConnector(tmp_path)
    entity = connector.entities[0]

    result = connector.extract(entity, since=None, until=date(2018, 1, 2))

    assert list(result.rows["review_id"]) == ["r1", "r2"]
    assert result.watermark == "2018-01-02 00:00:00"


def test_reviews_continue_after_watermark(tmp_path):
    _write_reviews(tmp_path)
    connector = LegacyCsvConnector(tmp_path)

    result = connector.extract(connector.entities[0], since="2018-01-02 00:00:00", until=date(2018, 1, 5))

    assert list(result.rows["review_id"]) == ["r3"]


def test_marketing_requests_window_after_watermark():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(
            200,
            json={
                "items": [
                    {"date": "2018-01-03", "channel": "organic", "sessions": 100, "ad_spend": 0.0},
                ]
            },
        )

    connector = MarketingApiConnector("http://mock", httpx.Client(transport=httpx.MockTransport(handler)))
    result = connector.extract(connector.entities[0], since="2018-01-02", until=date(2018, 1, 3))

    assert seen == {"from": "2018-01-03", "to": "2018-01-03"}
    assert result.watermark == "2018-01-03"
    assert result.rows.iloc[0]["sessions"] == "100"


def test_marketing_empty_response_keeps_columns():
    connector = MarketingApiConnector(
        "http://mock",
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []}))),
    )
    result = connector.extract(connector.entities[0], since=None, until=date(2018, 1, 3))

    assert result.rows.empty
    assert result.watermark is None
