# WR60 — direction "exits" (trade management on FVG Pro)

Code: `lab/wr60_exits.py` (own simulator; with `tp=2.0` it reproduces `engine.run` path mode trade for trade:
102 trades, 43 %, +0.26R, $10,460). Data: Dukascopy NQ 1m → 15m (also 10m, 30m), 2025-09-01 → 2026-10-14.
Costs: 2 MNQ, $0.62/side/contract, 1 tick slippage on stops/BE/market/time exits, flat 15:55.
IS = entry < 2026-04-01, OOS = entry ≥ 2026-04-01. Win = trade net $ > 0.
Entries unchanged (`fvg_pro.generate`); truncation check passes (`truncation_check()`).

## Chosen config (picked on IS: IS WR ≥ 58 %, IS PF ≥ 1.2, then most IS-positive months, then IS PF)

FVG Pro London 02:00–05:00 NY, min FVG 0.3 ATR, edge limit, 1 trade/day, 15m.
Exit: **half (1 contract) at +0.75R, stop to break-even from the next bar, runner target 3R,
time stop: everything still open exits at the open of the 9th bar after the fill bar (~2 h).**

| | Trades | WR | Exp. | PF | Net | Max DD |
|---|---|---|---|---|---|---|
| IS (Sep–Mar) | 54 | 63.0 % | +0.20R | 1.49 | +$1,679 | $874 |
| OOS (Apr–Oct) | 48 | 60.4 % | +0.10R | 1.60 | +$2,038 | $1,057 |
| Full year | 102 | 61.8 % | +0.15R | 1.54 | +$3,717 | $1,057 |
| Real MNQ, last ~70 days | 17 | 52.9 % | +0.11R | 1.50 | +$640 | $607 |

Monthly R: 25-09 +5.8, 10 +0.1, 11 +4.7, 12 +0.2, 26-01 −2.7, 02 +1.0, 03 +1.7, 04 −0.5, 05 +1.0,
06 −0.4, 07 +2.2, 08 +0.7, 09 +1.2, 10 +0.9 → **11/14 positive**.
Average win +0.68R, average loss −0.69R. Exits: 43 time, 18 full stop, 14 BE after TP1, 6 runner at 3R.

**The trade-off:** win rate 43 % → 62 %, drawdown $3,009 → $1,057, but expectancy +0.26R → +0.15R and
net $10,460 → $3,717 vs the 2R baseline. Higher WR is bought with smaller profit. On real MNQ (17 trades) the
2R version made $3,621, this one $640.

## What the grid showed (15m unless noted; 252 + 108 configs + 23 sensitivity runs = 383)

- Fixed 0.75R / 1.0R: IS 59–67 % WR but OOS 54–60 % and PF ~1.0–1.2 — costs eat small targets.
- Partial 0.5R + BE: 70–76 % WR on both halves, but wins are tiny; IS PF only 1.1–1.25 (OOS 1.8–2.1).
- Partial 1R + BE (1/2): 59 % IS / 54 % OOS, best expectancy (+0.17–0.20R).
- Break-even at +0.5/+0.75R (no partial) lowers WR (BE exits pay slippage + costs = small losses).
- The 2 h time stop is what keeps OOS PF ≥ 1.5: London trades not done by ~07:00 tend to give back at the NY open.
- Asia+London and NY AM: tight exits negative in IS (Asia+London PF 0.6–0.9 IS, positive OOS) — not stable.
- 10m: ~0R; 30m: negative. Only 15m works.
- Sensitivity of the chosen config (not used for selection): time stop 6–16 bars → OOS 60–62 % WR, PF 1.45–2.08;
  TP1 0.6/0.9R → OOS 56–62 %; min FVG 0.25–0.4 → OOS 56–60 %, PF 1.3–1.5. Runner target (1.5/2/3R) barely matters.

## Honesty notes

- The final ranking rule (most IS-positive months) was written after the first grid had printed OOS columns;
  a pure "max IS expectancy" rule picks partial 1.0/3.0 BE (IS 59 %, OOS 54 %, +0.15R, PF 1.36, 9/14 months).
- 102 trades/year on one market, one session; 60 % ± 7 % is the 95 % noise band on 48 OOS trades.
- TradingView: implement as `strategy.exit(qty_percent=50, limit=tp1)` + second exit for the rest, BE stop applied
  on the bar after TP1 fills, and `strategy.close` after 8 bars in the trade.
