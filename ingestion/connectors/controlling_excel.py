"""Controlling Excel workbook (synthetic): monthly budget per product category."""

from datetime import date
from pathlib import Path

import pandas as pd

from ingestion.base import Connector, Entity, ExtractResult
from ingestion.config import CONTROLLING_DIR

BUDGET_FILE = "budgets.xlsx"
BUDGET_SHEET = "Budgets"


class ControllingExcelConnector(Connector):
    source = "controlling"
    entities = (Entity("budgets", ("month", "category", "budget_brl")),)

    def __init__(self, directory: Path = CONTROLLING_DIR):
        self.directory = directory

    def extract(self, entity: Entity, since: str | None, until: date) -> ExtractResult:
        # Budgets are planned in advance, so the whole workbook is visible at any sim date.
        df = pd.read_excel(self.directory / BUDGET_FILE, sheet_name=BUDGET_SHEET, dtype=str)
        return ExtractResult(df)
