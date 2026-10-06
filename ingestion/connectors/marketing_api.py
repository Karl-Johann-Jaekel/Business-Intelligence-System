"""Marketing REST API (synthetic): sessions and ad spend per day and channel."""

from datetime import date, timedelta

import httpx
import pandas as pd

from ingestion.base import Connector, Entity, ExtractResult
from ingestion.config import MARKETING_API_URL


class MarketingApiConnector(Connector):
    source = "marketing"
    entities = (Entity("daily", ("date", "channel", "sessions", "ad_spend"), "incremental"),)

    def __init__(self, base_url: str = MARKETING_API_URL, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=30)

    def extract(self, entity: Entity, since: str | None, until: date) -> ExtractResult:
        params = {"to": until.isoformat()}
        if since is not None:
            params["from"] = (date.fromisoformat(since) + timedelta(days=1)).isoformat()
        response = self.client.get(f"{self.base_url}/v1/marketing/daily", params=params)
        response.raise_for_status()
        df = pd.DataFrame(response.json()["items"], columns=list(entity.columns)).astype(str)
        return ExtractResult(df, df["date"].max() if not df.empty else None)
