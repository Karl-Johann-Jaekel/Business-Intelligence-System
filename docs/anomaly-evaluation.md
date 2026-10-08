# Anomalieerkennung: Auswertung mit injizierten Anomalien

Erzeugt mit `python -m analytics.evaluate --start 2017-06-01 --end 2017-12-31 --magnitude 6 --seed 42`.

Methode: `stl_mad` (Wochentagseffekt aus STL, Niveau = rollierender Median der Vortage,
robuster Z-Score der Prognoseabweichung). Bewertet wird nur die Gesamtreihe.
Injektion: etwa alle 10 Tage ein Einzeltag-Ausschlag von ±6 × robuster
Standardabweichung des Ein-Schritt-Prognosefehlers der jeweiligen KPI.

Fehlalarme sauber = Alarme auf den echten Daten ohne Injektion. Darin stecken auch echte
Ausreißer (z. B. Black Friday 2017), sie sind also eine obere Schranke für Fehlalarme.

## Registry-Schwellen

| KPI | Schwelle | Tage | Injiziert | Treffer | Trefferquote | Fehlalarme/Monat (sauber) | Fehlalarme/Monat (mit Injektion) |
|---|---|---|---|---|---|---|---|
| `gmv` | 4 | 214 | 22 | 19 | 86% | 1.4 | 1.8 |
| `orders_count` | 3.5 | 214 | 22 | 19 | 86% | 1.4 | 1.5 |
| `avg_order_value` | 3.5 | 214 | 22 | 21 | 95% | 1.8 | 1.7 |
| `items_per_order` | 3.5 | 214 | 22 | 20 | 91% | 1.1 | 1.0 |
| `freight_ratio` | 3.5 | 214 | 22 | 21 | 95% | 1.1 | 1.4 |
| `cancellation_rate` | 3.5 | 214 | 22 | 20 | 91% | 1.3 | 1.3 |
| `delivery_time_avg_days` | 4 | 210 | 21 | 18 | 86% | 2.0 | 2.1 |
| `on_time_rate` | 4.5 | 210 | 21 | 10 | 48% | 2.0 | 2.4 |
| `review_score_avg` | 6 | 211 | 21 | 17 | 81% | 2.6 | 1.7 |
| `conversion_rate` | 3.5 | 214 | 22 | 20 | 91% | 1.5 | 2.0 |
| `roas` | 3.5 | 214 | 22 | 20 | 91% | 1.8 | 1.1 |

**Gesamt:** Trefferquote 86% (205/239), Fehlalarme Ø 1.6 pro KPI und simuliertem Monat auf den sauberen Daten.

## Kalibriert

| KPI | Schwelle | Tage | Injiziert | Treffer | Trefferquote | Fehlalarme/Monat (sauber) | Fehlalarme/Monat (mit Injektion) |
|---|---|---|---|---|---|---|---|
| `gmv` | 4 | 214 | 22 | 19 | 86% | 1.4 | 1.8 |
| `orders_count` | 3.5 | 214 | 22 | 19 | 86% | 1.4 | 1.5 |
| `avg_order_value` | 3.5 | 214 | 22 | 21 | 95% | 1.8 | 1.7 |
| `items_per_order` | 3.5 | 214 | 22 | 20 | 91% | 1.1 | 1.0 |
| `freight_ratio` | 3.5 | 214 | 22 | 21 | 95% | 1.1 | 1.4 |
| `cancellation_rate` | 3.5 | 214 | 22 | 20 | 91% | 1.3 | 1.3 |
| `delivery_time_avg_days` | 4 | 210 | 21 | 18 | 86% | 2.0 | 2.1 |
| `on_time_rate` | 4.5 | 210 | 21 | 10 | 48% | 2.0 | 2.4 |
| `review_score_avg` | 6 | 211 | 21 | 17 | 81% | 2.6 | 1.7 |
| `conversion_rate` | 3.5 | 214 | 22 | 20 | 91% | 1.5 | 2.0 |
| `roas` | 3.5 | 214 | 22 | 20 | 91% | 1.8 | 1.1 |

**Gesamt:** Trefferquote 86% (205/239), Fehlalarme Ø 1.6 pro KPI und simuliertem Monat auf den sauberen Daten.

Kalibrierung: je KPI die kleinste Schwelle aus 3.5, 4, 4.5, 5, 5.5, 6 mit höchstens 2 Fehlalarmen pro Monat auf den sauberen Daten.
Zielwerte aus dem Plan: Trefferquote ≥ 80 %, höchstens 2 Fehlalarme pro simuliertem Monat.
