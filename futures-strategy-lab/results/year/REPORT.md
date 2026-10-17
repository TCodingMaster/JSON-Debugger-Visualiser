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

## "Respected FVG" confirmation entry (user's definition), 1 year MNQ 15m, 2R

Rule (`lab/fvg_respect.py`): after BOS + FVG, the first candle that trades into the gap must close back
outside it as a hammer (rejection wick ≥ 50 % of range) or doji (body ≤ 25 %); enter next bar.

| London, min FVG 0.3 | Trades | WR | Exp. | PF |
|---|---|---|---|---|
| Current: limit on FVG edge | 102 | 43 % | +0.26R | 1.65 |
| Hammer/doji respect, market entry, stop beyond FVG | 31 | 19 % | −0.44R | 0.41 |
| same, swing stop | 18 | 28 % | −0.25R | 0.55 |
| close-back only (no candle shape) | 70 | 36 % | +0.04R | 0.98 |
| touch within 0.25 ATR | 35 | 29 % | −0.19R | 0.59 |
| respect, then limit back at the edge | 25 | 36 % | +0.04R | 0.87 |

Grid of 432 variants (sessions, wick size, first-touch only, stop type, RR): average −0.03R, IS→OOS
correlation 0.03. Waiting for a rejection candle lowers win rate: the best FVG trades touch the gap
and leave without a hammer, and a hammer at the gap is often followed by a deeper move.

## Gold and crude oil over one year (Dukascopy XAUUSD / WTI CFD, 1 MGC / 1 CL)

Proxy check vs Yahoo futures: gold 15m return corr 0.99; WTI 0.93 (WTI is missing most of June–July 2026,
the Dukascopy feed rate-limited the download).

| Market | Strategy | Trades | WR | Exp. | IS / OOS exp. |
|---|---|---|---|---|---|
| MGC 15m | Quality A+L 1.5R | 159 | 42 % | +0.02R | +0.04 / +0.00 |
| MGC 5m | Quality A+L 2R | 260 | 40 % | +0.16R | +0.13 / +0.19 |
| MGC 15m | Leto London 2R | 49 | 29 % | −0.21R | −0.44 / +0.09 |
| CL 5m | Quality A+L 1.5R | 221 | 43 % | +0.00R | −0.06 / +0.10 |
| CL 5m | Quality A+L 2R | 221 | 35 % | −0.02R | −0.12 / +0.14 |
| CL 15m | Quality A+L 2R EMA50 | 124 | 33 % | −0.07R | +0.06 / −0.32 |

Over a full year the FVG strategies are about break-even on gold and crude; the strong CL 5m run seen
in TradingView (Aug 24 – Oct 16) was the good part of the year. Only MNQ 15m shows a steady edge.
