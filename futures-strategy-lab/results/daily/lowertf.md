# Daily direction "lowertf": 5m/10m execution with 15m/1h context. Result: FAIL

Code: `lab/daily_lowertf.py`. Data: Dukascopy 1m proxies (NQ, XAU), 2025-09-01 to 2026-10-14, 291 Globex days (151 IS, 140 OOS).
IS means entry before 2026-04-01; OOS means entry on or after 2026-04-01. Selection used IS only.
A win is a position whose net $ is above 0. Costs are $0.62/side/contract. Stop, BE, time and EOD exits pay 1 tick of slippage, 2 ticks in the robustness runs.
The simulator is `lab.daily_exits.simulate`, with TradingView path, "worst" intrabar and 1-minute replay modes.

## Rules tested
* **Entry.** The unchanged FVG Pro setup (`fvg_pro.generate`: BOS + FVG, limit at the gap edge) on the 5m or 10m chart.
  The "don't chase" filter is applied at 1.0 ATR. Max 1 trade per component per day.
* **Context.** It uses completed higher-TF bars only: an HTF bar [T, T+H) is usable by an exec bar [s, s+e) only when T+H <= s+e.
  * `bos15` / `bos60`: the trade must go in the direction of the last 15m or 1h close beyond a confirmed pivot-3 swing.
  * `ema60`: the trade must follow the slope of a 20-period EMA on completed 1h bars.
  * `bos15+ema60`: both of the above.
  * `fvg15`: a 15m FVG Pro setup in the same direction within the last 2h.
* **Exit.** Base (`p10`): half at 1R, then BE, runner at 3R. Variants: `p05` (half at 0.5R, BE, runner 2R) and `p05x3` (2 of 3 contracts at 0.5R).
  Time stop is 8, 12 or 24 exec bars. Flat at 15:55.
* **Portfolio.** The first filled trade per market per day (max 1 MNQ + 1 MGC).
* **Windows (NY).** MNQ London 02-05 and NY AM 08:30-11. MGC London and COMEX 08:20-10:30. Stage 2 also tried the two windows combined.

## Search: 384 component configs + about 50 portfolio, robustness and neighbour runs
* **Stage 1 (160).** 2 markets × 2 windows × TF {5,10} × 5 contexts × min FVG {0.15, 0.3} × 2 time stops, with the base exit.
  Only 2 configs met the IS gate (≥30 IS trades, WR ≥60 %, PF ≥1.3, ≥5/7 IS months positive).
  The 5m/10m FVG Pro win rate is mostly 40-55 %.
* **Stage 2 (192).** Quicker exits (`p05`, `p05x3`) × single and combined windows × 4 contexts × TF × min FVG. 8 configs met the IS gate.
* **Stage 3 (32).** `fvg15` context (15m BOS+FVG, then 5m/10m FVG entry). It gives only 1-12 trades per half. That is useless for frequency.
* **IS→OOS across the 306 configs with enough trades.** The Spearman rank correlation of PF is −0.00. 192 configs had IS PF > 1, but only 86 had OOS PF > 1.
  Mean expectancy on 5m: IS +0.04R, OOS −0.08R. On 10m: −0.06R and −0.06R.
  **No single component has WR ≥58 % and PF ≥1.3 in both IS and OOS.**

## IS pick (rule: per market+window, the best IS WR × min(PF,3) × sqrt(trades/day))
| Component | IS n / WR / PF | OOS n / WR / PF |
|---|---|---|
| MGC 5m London+COMEX, bos15+ema60, mf 0.3, ts24, p05 | 50 / 74 % / 2.30 | 41 / 59 % / 0.62 |
| MNQ 5m London, bos15, mf 0.3, ts24, p05 | 39 / 69 % / 1.42 | 44 / 61 % / 0.80 |
| MNQ 5m NY AM, ema60, mf 0.15, ts8, p10 | 32 / 62 % / 2.15 | 29 / 38 % / 0.24 |

| Portfolio (1/market/day) | trades/day | WR | Exp R | PF | Net $ | Max DD |
|---|---|---|---|---|---|---|
| IS | 0.74 | 70.3 % | +0.162 | 2.05 | +6,139 | 1,381 |
| OOS | 0.73 | 56.9 % | −0.135 | **0.59** | −4,105 | 4,105 |
| Full year | 0.73 | 63.8 % | +0.020 | 1.13 | +2,034 | 4,105 |

Positive months: 8/14.

| Check | IS PF | OOS WR / PF |
|---|---|---|
| worst intrabar + 2 ticks | 2.03 | 56.9 % / 0.58 |
| conservative + 2 ticks | 2.04 | 59.8 % / 0.64 |
| 1-minute replay + 2 ticks | 1.98 | 56.9 % / 0.60 |

**Bar alignment (1m data resampled with bar starts shifted by 1-4 minutes).**

| Shift | IS PF | OOS PF |
|---|---|---|
| 0 min (base) | 2.05 | 0.59 |
| 1 min | 2.30 | 1.25 |
| 2 min | 1.34 | 1.22 |
| 3 min | 1.39 | 1.43 |
| 4 min | 1.30 | 0.78 |

The result depends strongly on where the bars start, which is a sign of noise. None of the shifts passes (0.65-0.75 trades/day, 7-8/14 months).

**Neighbours.** 41 portfolios, each changing one thing (min FVG, time stop, context, exit, TF, chase). Every one has OOS PF between 0.51 and 0.75.
Without the context filter, frequency reaches 0.84-1.01 trades/day, but OOS PF is 0.61-0.75.

## Conclusion
Moving FVG Pro execution to 5m/10m does raise the number of setups. Even so, the IS-only pick reaches just 0.73 trades/day.
The higher-TF filters (15m/1h BOS, 1h EMA, 15m FVG) do not create an edge that carries over to OOS.
Picks that look good in IS (62-76 % WR) fall to 38-61 % WR and PF < 1 in OOS, and the results are unstable under 1-4 minute bar shifts.
This matches earlier research, where MNQ 5m IS ranking had negative OOS predictive value.
**No lower-TF configuration passes.** The closest is the portfolio above (0.73 trades/day, 64 % WR for the year), and it is not robust.
The daily-frequency target is better served on 15m. `results/daily/exits.md` (15m entries, 2/3 out at 0.5R) passes there.

Reproduce: `cd futures-strategy-lab && PYTHONPATH=. python -m lab.daily_lowertf grid` (stage 1), then `grid2`, `grid3`, `final` and `trunc`. Each takes under 3 min.
Outputs: `results/daily/lowertf_grid.json`, `lowertf_grid2.json`, `lowertf_grid3.json`, `lowertf_final.json`.
The truncation check (setups and context rebuilt from truncated 1m data) passes.
