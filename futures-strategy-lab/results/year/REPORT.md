# One-year backtest (MNQ 15m) — walk-forward

Data: Dukascopy Nasdaq 100 CFD 1-minute bars → 15m, 2025-09-01 → 2026-10-14 (`lab/dukascopy.py`;
data not committed). Proxy check vs real MNQ futures (Yahoo, overlap ~70 days): 15m return
correlation 0.987, bar ranges equal (ratio 0.97). Costs: 2 MNQ, $0.62/side, 1 tick slippage,
TradingView-like intrabar path, flat 15:55 NY.

## Existing strategies over the full year

| Strategy | Trades | WR | Exp. | PF | Net | Max DD | + months |
|---|---|---|---|---|---|---|---|
| Quality 2R EMA50 (Asia+London) | 152 | 44 % | +0.26R | 1.48 | +$11,036 | $2,950 | 11/14 |
| Liquidity Swings Retest 2R | 241 | 36 % | +0.01R | 1.02 | +$754 | $5,460 | 8/14 |
| sweepX 15m preset 2R | 460 | 41 % | +0.14R | 1.21 | +$12,976 | $5,000 | 10/14 |

Quality: first 7 months ≈ 0R (IS 83 tr, 37 %, +0.08R), last 6.5 months +0.48R — uneven.
Liquidity Swings Retest's 58 % on the last 60 days did not hold over the year.
On 5m all three are ≈ 0R over the year.

## Walk-forward: Quality family, chosen on 2025-09 → 2026-03, tested on 2026-04 → 2026-10

720 configs per timeframe (sessions × min FVG × entry × max trades × 1h trend × RR × EMA).
MNQ 15m: 96 % of configs positive out-of-sample (mean +0.30R) — the 15m edge is broad.
MNQ 5m: IS ranking predicted OOS negatively (corr −0.53) — no reliable 5m version.

Chosen ("FVG Pro Leto", `pine/fvg_pro_year_strategy.pine`): London 02:00–05:00 NY only,
min FVG 0.3 ATR, edge entry, 2R, 1 trade/day, no EMA.

| | Trades | WR | Exp. | PF | Net |
|---|---|---|---|---|---|
| In-sample (Sep–Mar) | 54 | 43 % | +0.26R | 1.68 | +$4,660 |
| Out-of-sample (Apr–Oct) | 48 | 44 % | +0.27R | 1.62 | +$5,800 |
| Full year | 102 | 43 % | +0.26R | 1.65 | +$10,460 (DD $3,009, 10/14 months +) |
| Real MNQ (Yahoo, last ~70 days) | 17 | 53 % | +0.54R | 2.49 | +$3,621 |

Monthly R: 25-09 +8.7, 25-10 −1.1, 25-11 +8.9, 25-12 +1.9, 26-01 −3.1, 26-02 −8.1, 26-03 +7.0,
26-04 +2.9, 26-05 +1.9, 26-06 −3.1, 26-07 +1.8, 26-08 +5.4, 26-09 +1.9, 26-10 +2.0.
Same rules at 1.5R: 46 % WR, +0.14R; at 2.5R: 41 % WR, +0.39R.
