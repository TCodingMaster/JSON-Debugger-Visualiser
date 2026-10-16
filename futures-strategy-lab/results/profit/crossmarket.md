# Cross-market FVG Pro: one rule set on MNQ + gold (and crude)

Code: `lab/prof_crossmarket.py` (`python -m lab.prof_crossmarket grid`, `... final`, `... check`).
Data: Dukascopy CFD 1m -> 15m, 2025-09-01 .. 2026-10-14. IS = entries < 2026-04-01, OOS = after.
Costs: 2 MNQ at $0.62/side and 1 MGC at $0.82/side, with 1 tick slippage (2 ticks also checked). R = net $ / planned $ risk.
Setups come from the unchanged `fvg_pro.generate`, and the truncation check passes.

## Search (864 single-market runs -> 720 cross-market candidates)
* Grid (144 parameter sets): min FVG 0.15/0.3/0.5 ATR, RR 1.5/2/2.5, 1h EMA-slope trend filter on/off, stop at the leg swing or beyond the FVG, entry at the gap edge or at 50 %. Every setting allows max 1 trade/day and flattens at 15:55.
* Market windows, fixed in advance: MNQ London 02-05 and NY AM 08:30-11; MGC London 03-06 and COMEX 08:20-10:30; MCL NYMEX 09-11:30 and London 02-05.
* Cross-market candidate: the same parameters on every market in a scheme (NQ+GC-London+CL, NQ+GC-COMEX+CL, NQ+GC-London, NQ+GC-COMEX, NQ+CL).
  Selection rule: the highest combined IS R, among candidates where every market is IS-positive and the scheme has at least 60 IS trades.
* How robust each market window is across the 72 settings of its grid half:

| Market/window | IS > 0 | OOS > 0 | median IS / OOS exp |
|---|---|---|---|
| MNQ London | 34/72 | 51/72 | -0.02 / +0.15R |
| MNQ NY AM | 41/72 | 23/72 | +0.05 / -0.06R |
| **MGC COMEX 08:20-10:30** | **54/72** | **51/72** | **+0.13 / +0.11R** |
| MGC London 03-06 | 5/72 | 31/72 | -0.28 / -0.03R |
| MCL NYMEX 09-11:30 | 21/72 | 9/72 | -0.18 / -0.17R |
| MCL London | 27/72 | 32/72 | -0.08 / -0.04R |

Crude fails in every scheme: no setting is robustly positive. Schemes that include CL rank below the NQ+GC ones and are weak OOS (+0.07R or less for the IS leaders).

## Selected (IS only): MNQ London 02-05 + MGC COMEX 08:20-10:30
Settings: min FVG 0.3 ATR, RR 2.5, edge entry, stop at the leg swing (default), no trend filter, max 1 trade/day per market.
This is the Leto rule with RR 2.5 instead of 2.0, plus gold at the COMEX open.

| | Trades | WR | Exp R | PF $ | PF R | Net $ | Max DD |
|---|---|---|---|---|---|---|---|
| MNQ full | 102 | 41 % | +0.39 | 1.81 | 1.67 | +13,408 | 2,846 |
| MNQ IS / OOS | 54 / 48 | 41 / 42 % | +0.43 / +0.36 | 1.95 / 1.72 | | +6,486 / +6,922 | |
| MGC full | 78 | 53 % | +0.26 | 1.75 | 1.62 | +4,300 | 652 |
| MGC IS / OOS | 45 / 33 | 51 / 55 % | +0.37 / +0.12 | 1.97 / 1.38 | 1.81 / 1.31 | +3,479 / +821 | |
| **Combined full** | **180** | **46 %** | **+0.34** | **1.80** | **1.65** | **+17,708** | **2,871** |
| Combined IS | 99 | 45 % | +0.40 | 1.96 | 1.76 | +9,965 | 2,871 |
| Combined OOS | 81 | 47 % | +0.26 | 1.66 | 1.51 | +7,743 | 2,419 |

Monthly R, combined (11/14 positive): 25-09 +14.2, 25-10 +6.8, 25-11 +14.8, 25-12 +1.4, 26-01 -1.0, 26-02 -5.8, 26-03 +9.2, 26-04 +3.8, 26-05 +4.8, 26-06 -2.7, 26-07 +1.1, 26-08 +5.4, 26-09 +7.8, 26-10 +0.7.
* MNQ alone is positive in 10/14 months. MGC alone is positive in 10/14 months: +1.8R in Feb-2026, when MNQ had -7.7R, but negative in Jul, Aug and Oct 2026.
* Baseline Leto: 102 trades, PF 1.65, +$10.5k, 10/14 months, worst month -8.1R. The selected rule: 180 trades, PF 1.80, +$17.7k, 11/14 months, worst month -5.8R, about the same max DD.

## Robustness
* Stop-first intrabar resolution gives identical results (limit entries do not resolve stop and target on the same bar here). 2 ticks of slippage: PF 1.79, +$17.6k.
* Neighbours on both markets: min FVG 0.2/0.3/0.4 x RR 2.0/2.25/2.5/2.75. All 12 have IS PF $ >= 1.25 and OOS PF $ >= 1.38, and 9-12 of 14 months positive.
  The RR 2.0 version (pure Leto parameters): 180 trades, PF 1.66, IS 1.78 / OOS 1.56, 9/14 months. RR 2.5 is a mild peak, not a cliff.
* Gold window shifted (08:00-10:30, 08:20-10:00, 08:20-11:00, 08:40-10:30): combined PF 1.70-1.89, 10-11/14 months.
* 5-minute bars fail (combined -0.09R, OOS PF 0.79). The edge is specific to 15m, as found earlier.
* Real futures, 2026-08-06 .. 10-15: MNQ 17 trades, +0.78R, PF 3.0, +$4,970, in line with the proxy. MGC 14 trades, +0.03R, PF 0.95, -$64 (proxy over the same period: +0.05R). Gold is about flat over this short window, which is consistent with the proxy.

## Honest reading
* The goal is met on paper: PF >= 1.3 on IS and OOS (1.96 / 1.66), 11/14 months positive, 180 trades, DD $2.9k against $17.7k net.
* Most of the profit is still MNQ London. Gold COMEX adds roughly +$4k a year with a small DD and a different loss calendar (it helped in Feb-2026). Its OOS edge is thin, though: +0.12R, PF 1.38, and about flat on 14 real-futures trades.
* One rule did NOT hold on all three markets. Crude (NYMEX open) and gold in the London window are break-even or negative across the grid.
  The "cross-market" support comes from 2 markets, each in its own session. The choice of the gold COMEX window was part of the IS selection, although COMEX is also the most robust window OOS (51/72).
