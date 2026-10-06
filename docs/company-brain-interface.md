# Company-Brain-Schnittstelle (Entwurf)

Stand: 2026-10-06 · Status: **Entwurf**, wird mit Abschluss von Woche 3 als `insight.v1` eingefroren.

Dieses Dokument beschreibt den Vertrag zwischen dem Business-Intelligence-System (BIS) und
späteren Konsumenten (Hive Mind, Central-Intelligence-Agent). Das BIS ist das quantitative
Organ: Es liefert berechnete Kennzahlen und daraus abgeleitete Ereignisse, keine Rohdaten.

## Kanäle

| Kanal | Richtung | Inhalt | Status |
|---|---|---|---|
| `GET /api/v1/kpis` | Pull | KPI-Registry (Semantic Layer) | Woche 2 |
| `GET /api/v1/kpis/{key}/series` | Pull | Zeitreihe einer Kennzahl | Woche 2 |
| `GET /api/v1/insights` | Pull | Insights seit Zeitpunkt | Woche 3 |
| Webhook (Outbox-Dispatcher) | Push | Insight-Events, HMAC-signiert | Woche 3 |

## Entitäts-IDs

Gemeinsamer Namensraum mit Hive Mind: `<typ>:<quellschlüssel>`.

| Typ | Beispiel | Quelle im Warehouse |
|---|---|---|
| `customer` | `customer:861eff4711a542e4b93843c6dd7febb0` | `marts.dim_customer.entity_id` (Olist `customer_unique_id`) |
| `product` | `product:1e9e8ef04dbcff4541ed26657ea517e5` | `marts.dim_product.entity_id` |
| `seller` | `seller:3442f8959a84dea7ee197c632cb2df15` | `marts.dim_seller.entity_id` |
| `region` | `region:SP` | `marts.dim_region.entity_id` (Bundesstaat) |
| `category` | `category:health_beauty` | `marts.dim_product.category_entity_id` |
| `kpi` | `kpi:delivery_time_avg_days` | Registry-Schlüssel mit Präfix |

Die IDs werden bereits in Woche 1 von dbt erzeugt (`entity_id`-Spalten in Dimensionen sowie
in `kpi_daily` / `kpi_monthly`).

## Event `insight.v1`

```json
{
  "schema_version": "insight.v1",
  "insight_id": "uuid",
  "source": "business-intelligence-system",
  "type": "anomaly | briefing | forecast_deviation | data_quality",
  "kpi": "delivery_time_avg_days",
  "period": {"start": "2018-03-12", "end": "2018-03-12", "grain": "day"},
  "severity": "info | warning | critical",
  "direction": "up | down",
  "observed": 14.2,
  "expected": 9.8,
  "deviation_pct": 44.9,
  "entity_refs": [{"type": "region", "id": "region:SP"}],
  "evidence": {"method": "stl_mad", "score": 4.7, "query_ref": "/api/v1/kpis/delivery_time_avg_days/series"},
  "summary": "Kurzbeschreibung in Klartext",
  "data_class": "public | internal | confidential",
  "created_at": "ISO-8601"
}
```

Regeln:

- `kpi` enthält den Registry-Schlüssel **ohne** Präfix; als Entität heißt derselbe KPI `kpi:<key>`.
- `insight_id` ist der Idempotenzschlüssel. Konsumenten müssen doppelte Zustellung tolerieren.
- `data_class` stammt aus der Registry und steuert, an welche Konsumenten bzw. LLM-Provider
  ein Insight gehen darf.
- Zeitangaben beziehen sich auf die **Simulationszeit** (`ops.sim_clock`), `created_at` auf die
  echte Erzeugungszeit.

## Offene Fragen

1. Signatur-Header und Schlüsselrotation für den Webhook
2. Rückkanal: Darf ein Konsument Insights quittieren oder kommentieren?
3. Versionierung: Ab wann gilt eine Feldänderung als `insight.v2`?
