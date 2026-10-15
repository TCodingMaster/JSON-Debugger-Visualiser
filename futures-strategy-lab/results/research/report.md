# ICT research engine — scalping 1-15m

Yahoo Finance bars accumulated in data/store: MGC 15m 2026-08-06→2026-10-15, MGC 1m 2026-09-17→2026-10-15, MGC 2m 2026-09-09→2026-10-15, MGC 3m 2026-09-17→2026-10-15, MGC 5m 2026-08-06→2026-10-15, MNQ 15m 2026-08-06→2026-10-15, MNQ 1m 2026-09-17→2026-10-15, MNQ 2m 2026-09-09→2026-10-15, MNQ 3m 2026-09-17→2026-10-15, MNQ 5m 2026-08-06→2026-10-15.

* Variants tested: **3420** (1326 with ≥30 trades)
* Out-of-sample confirmed (IS > 0 and OOS > 0): **325** = 25% of eligible — random control: 16%
* Survivors after false-discovery control (q ≤ 0.10): **0** (random control: 0)
* Variants with ≥60 % win rate and ≥30 trades: **3**

If the real families confirm out-of-sample about as often as random entries do, the 'winners' are luck.

## Families

| Family | Variants | Median exp | % positive | Win rate | OOS-confirmed | Survivors |
|---|---|---|---|---|---|---|
| BOS continuation → FVG | 132 | +0.108R | 67% | 39.1% | 49 | 0 |
| First FVG of the hour (Silver Bullet style) | 173 | +0.049R | 60% | 37.0% | 48 | 0 |
| Fair value gap retrace | 280 | +0.044R | 57% | 36.8% | 96 | 0 |
| Sweep → MSS → OTE 62-79 % | 46 | +0.022R | 52% | 34.9% | 10 | 0 |
| Sweep → MSS → FVG (2022 model) | 39 | -0.045R | 46% | 34.9% | 10 | 0 |
| Change in state of delivery | 9 | -0.048R | 22% | 30.7% | 0 | 0 |
| Order block retest after BOS | 198 | -0.056R | 42% | 35.6% | 38 | 0 |
| Inverse FVG retest | 248 | -0.058R | 39% | 34.1% | 57 | 0 |
| Random entries (control) | 100 | -0.090R | 39% | 34.1% | 16 | 0 |
| Breaker block retest | 201 | -0.210R | 20% | 29.8% | 17 | 0 |

## Top out-of-sample-confirmed variants

| Variant | Trades | WR | Exp | IS exp | OOS n | OOS WR | OOS exp | q |
|---|---|---|---|---|---|---|---|---|
| first_fvg|asia|any|edge|2m|MNQ | 50 | 48% | +0.40R | +0.03R | 22 | 64% | +0.87R | 1.00 |
| first_fvg|all|any|edge|2m|MNQ | 52 | 50% | +0.46R | +0.16R | 22 | 64% | +0.87R | 1.00 |
| fvg|london_kz|any|edge|15m|MNQ | 55 | 51% | +0.51R | +0.30R | 23 | 61% | +0.81R | 1.00 |
| fvg|london_kz|any|ce|15m|MNQ | 50 | 48% | +0.42R | +0.24R | 19 | 58% | +0.72R | 1.00 |
| first_fvg|ny_am_kz|any|edge|3m|MGC | 30 | 47% | +0.37R | +0.13R | 12 | 58% | +0.72R | 1.00 |
| first_fvg|all|any|edge|15m|MNQ | 98 | 48% | +0.42R | +0.23R | 40 | 57% | +0.71R | 0.64 |
| bos_fvg|ny_am_kz|trend|edge|1m|MNQ | 31 | 45% | +0.32R | +0.03R | 14 | 57% | +0.68R | 1.00 |
| ifvg|london_kz|any|edge|5m|MGC | 68 | 44% | +0.29R | +0.12R | 21 | 57% | +0.68R | 1.00 |
| bos_fvg|ny_am_kz|any|ce|1m|MNQ | 36 | 50% | +0.47R | +0.32R | 16 | 56% | +0.66R | 1.00 |
| first_fvg|ny_am_kz|pd|edge|5m|MNQ | 35 | 49% | +0.30R | +0.15R | 11 | 55% | +0.61R | 1.00 |
| ote|all|trend|edge|2m|MNQ | 46 | 50% | +0.46R | +0.34R | 20 | 55% | +0.61R | 1.00 |
| ifvg|london_kz|any|ce|5m|MGC | 64 | 42% | +0.23R | +0.05R | 20 | 55% | +0.61R | 1.00 |
| fvg|silver_bullet|pd|edge|1m|MGC | 36 | 50% | +0.39R | +0.23R | 15 | 60% | +0.61R | 1.00 |
| fvg|asia|trend|ce|2m|MNQ | 52 | 44% | +0.29R | +0.06R | 22 | 55% | +0.60R | 1.00 |
| fvg|all|trend|ce|2m|MNQ | 52 | 44% | +0.29R | +0.06R | 22 | 55% | +0.60R | 1.00 |
| ifvg|london_kz|trend|edge|5m|MNQ | 45 | 47% | +0.38R | +0.28R | 15 | 53% | +0.58R | 1.00 |
| ifvg|london_kz|trend|ce|5m|MNQ | 46 | 46% | +0.34R | +0.23R | 15 | 53% | +0.58R | 1.00 |
| ob|london_kz|trend|edge|5m|MNQ | 38 | 50% | +0.46R | +0.39R | 13 | 54% | +0.58R | 1.00 |
| first_fvg|london_kz|any|edge|15m|MNQ | 47 | 49% | +0.45R | +0.38R | 17 | 53% | +0.57R | 1.00 |
| fvg|silver_bullet|any|ce|2m|MNQ | 42 | 43% | +0.26R | +0.06R | 17 | 53% | +0.57R | 1.00 |
| bos_fvg|asia|any|ce|5m|MNQ | 49 | 41% | +0.20R | +0.01R | 17 | 53% | +0.56R | 1.00 |
| bos_fvg|asia|trend|edge|2m|MNQ | 38 | 58% | +0.72R | +0.85R | 17 | 53% | +0.55R | 0.64 |
| fvg|all|any|edge|15m|MNQ | 99 | 45% | +0.34R | +0.20R | 40 | 52% | +0.54R | 1.00 |
| bos_fvg|london_kz|any|ce|2m|MGC | 42 | 52% | +0.53R | +0.52R | 17 | 53% | +0.54R | 1.00 |
| ob|ny_am_kz|trend|edge|2m|MNQ | 40 | 48% | +0.38R | +0.25R | 19 | 53% | +0.54R | 1.00 |

## Forward-test watchlist

Empty — no variant has survived the false-discovery control yet.
