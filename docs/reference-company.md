# Referenzunternehmen

Fiktive Firma, auf die sich das System bezieht (Plan §1). Ihre Zahlen sind die echten
Olist-Daten, ihr Organisationswissen ist synthetisch. **Alle Personen sind erfunden.**

## Personen

Entitäts-ID nach dem Namensraum in [contracts/entity-namespace.v1.schema.json](../contracts/entity-namespace.v1.schema.json).
Die KPI-Registry verweist über `owner` auf diese IDs; der Korpus-Generator (Phase K1) erzeugt
Meetings, Entscheidungen und Kommunikation mit genau diesen Personen.

| Entitäts-ID | Rolle | Verantwortet (Registry) |
|---|---|---|
| `person:leitung-vertrieb` | Leitung Vertrieb | GMV, Bestellungen, Ø Warenkorbwert, Ø Artikel pro Bestellung |
| `person:leitung-logistik` | Leitung Logistik | Frachtkostenquote, Stornoquote, Ø Lieferzeit, Pünktlichkeitsquote |
| `person:leitung-kundenservice` | Leitung Kundenservice | Ø Bewertung |
| `person:leitung-marketing` | Leitung Marketing | Neukunden, Wiederkäufer, Conversion Rate, ROAS |
| `person:leitung-finanzen` | Leitung Finanzen | Budgetabweichung |

Weitere Personen (Teammitglieder, Geschäftsführung) ergänzt Phase K1 hier, zusammen mit dem
Seed des Generators.
