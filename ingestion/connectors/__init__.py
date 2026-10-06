from ingestion.base import Connector
from ingestion.connectors.controlling_excel import ControllingExcelConnector
from ingestion.connectors.erp_postgres import ErpPostgresConnector
from ingestion.connectors.legacy_csv import LegacyCsvConnector
from ingestion.connectors.marketing_api import MarketingApiConnector


def all_connectors() -> list[Connector]:
    return [
        ErpPostgresConnector(),
        LegacyCsvConnector(),
        MarketingApiConnector(),
        ControllingExcelConnector(),
    ]
