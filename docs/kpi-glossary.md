# KPI-Glossar

Quelle der Wahrheit ist [registry/kpis/olist.yaml](../registry/kpis/olist.yaml). Dieses Glossar
erklärt Definitionen und Datenherkunft. Quoten werden als Anteil gespeichert (0,05 = 5 %), Faktoren als Vielfaches (8,2 = 8,2×).
Änderungen von Quoten zeigt das Dashboard in Prozentpunkten (pp), alle anderen relativ in %.

| Schlüssel | Bezeichnung | Definition | Datum | Dimensionen | Herkunft |
|---|---|---|---|---|---|
| `gmv` | Umsatz (GMV) | Summe Artikelpreise nicht stornierter Bestellungen | Bestelldatum | Region, Kategorie | echt |
| `orders_count` | Anzahl Bestellungen | Nicht stornierte Bestellungen | Bestelldatum | Region | echt |
| `avg_order_value` | Ø Warenkorbwert | GMV / Bestellungen mit Positionen | Bestelldatum | Region | echt |
| `items_per_order` | Ø Artikel pro Bestellung | Bestellpositionen / nicht stornierte Bestellungen mit Positionen | Bestelldatum | Region | echt |
| `freight_ratio` | Frachtkostenquote | Frachtkosten / GMV | Bestelldatum | Region, Kategorie | echt |
| `cancellation_rate` | Stornoquote | Status `canceled` oder `unavailable` / alle Bestellungen | Bestelldatum | Region | echt |
| `delivery_time_avg_days` | Ø Lieferzeit | Zustellung − Bestellung in Tagen | Zustelldatum | Region | echt |
| `on_time_rate` | Pünktlichkeitsquote | Zustellung ≤ zugesagter Termin / Zustellungen | Zustelldatum | Region | echt |
| `review_score_avg` | Ø Bewertung | Mittelwert Bewertung 1–5 | Bewertungsdatum | Region | echt |
| `new_customers` | Neukunden | Bestellungen von Kunden ohne frühere Bestellung | Bestelldatum | Region | echt |
| `returning_customers` | Wiederkäufer | Bestellungen von Kunden mit früherer Bestellung | Bestelldatum | Region | echt |
| `conversion_rate` | Conversion Rate | Nicht stornierte Bestellungen / Sessions | Bestelldatum | – | **teils synthetisch** (Sessions) |
| `roas` | ROAS | GMV / Werbeausgaben (Faktor, 8,2 = 8,2×) | Bestelldatum | – | **teils synthetisch** (Werbeausgaben) |
| `budget_deviation` | Budgetabweichung | (Ist-GMV − Budget) / Budget, monatlich | Monat | Kategorie | **teils synthetisch** (Budget) |

## Synthetische Daten

Olist enthält weder Besuchs- noch Budgetdaten. Beide werden in `ingestion/setup/synthetic.py`
mit festem Seed (`42`) erzeugt:

- **Marketing (Mock-API):** Sessions = reale Tagesbestellungen / Conversion Rate. Die Rate liegt
  um 2,2 % mit Wochentagseffekt und log-normalem Rauschen. Aufteilung auf vier Kanäle
  (organic, paid_search, paid_social, email) per Dirichlet-Verteilung; Kosten pro Session je Kanal.
- **Budget (Excel):** realer Monats-GMV je Kategorie × log-normaler Planfaktor, auf 100 BRL gerundet.

Conversion Rate, ROAS und Budgetabweichung sind deshalb nur eingeschränkt aussagekräftig und
dienen dem Nachweis der Pipeline, nicht einer echten Geschäftsaussage.

## Bekannte Vereinfachungen

- **Bestellstatus:** Olist liefert nur den Endstatus. Die Simulationsuhr blendet Zeitstempel nach
  dem Simulationsdatum aus und setzt `delivered` dann auf `shipped` bzw. `processing` zurück.
  Stornierungen sind dagegen ab Bestelltag sichtbar, weil Olist kein Stornodatum enthält.
- **Datenränder:** Olist ist vor 2017-01 und nach 2018-08 sehr dünn besetzt.
- **Mehrfachbewertungen:** Eine `review_id` kann mehrere Bestellungen abdecken; der Schlüssel ist
  `(review_id, order_id)`.
