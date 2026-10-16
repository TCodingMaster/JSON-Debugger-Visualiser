# Regime filters for FVG Pro Leto (MNQ 15m, London 02:00-05:00 NY)

Code: `lab/prof_regime.py` (`python -m lab.prof_regime` = stage 1 + NY AM, `... stage2`, `... final`).
Data: Dukascopy NQ CFD 1m -> 15m, 2025-09-01 .. 2026-10-14. IS = entries < 2026-04-01, OOS = after.
Costs: 2 MNQ, $0.62/side, 1 tick slippage (2 and 3 ticks also checked). PF below is the $ PF (same as the baseline report's 1.65).
All regime values are computed at the signal bar from data up to that bar; truncation check passes.
Filtered setups are removed before the engine runs. Equity filters use a shadow equity curve, so a skip only depends on earlier trades.

Configurations tried: 172. Stage 1: 80 regime-quantile filters, 5 weekdays, 9 equity/loss-limit filters. NY AM grid: 18. Stage 2: 60 fixed-grid variants and combos. Robustness re-runs are not counted.

## Result (chosen by IS score only, with at least 40 IS trades)

**Asia range >= 0.10 x 20-day daily ATR, and skip the next setup after 3 consecutive losses (shadow equity; trading resumes after a shadow winner)**

| | Trades | WR | Exp | PF $ | Net | Max DD |
|---|---|---|---|---|---|---|
| Baseline Leto, full year | 102 | 43 % | +0.26R | 1.65 | +$10,460 | $3,009 |
| **Selected, full year** | 81 | 47 % | +0.39R | 1.87 | +$10,521 | $1,619 |
| Selected, IS | 41 | 51 % | +0.52R | 2.27 | +$5,428 | $1,619 |
| Selected, OOS | 40 | 43 % | +0.25R | 1.65 | +$5,093 | $1,398 |
| Selected, stop-first intrabar | 81 | 47 % | +0.39R | 1.87 | +$10,521 | $1,619 |
| Selected, 2 ticks slippage | 81 | 47 % | +0.38R | 1.86 | +$10,477 | $1,626 |
| Streak-3 only (1 parameter) | 85 | 46 % | +0.36R | 1.86 | +$10,737 | $1,619 |

Monthly R (selected): 25-09 +9.8, 25-10 -1.1, 25-11 +8.9, 25-12 +2.9, 26-01 -1.1, 26-02 -3.0, 26-03 +5.0,
26-04 -0.1, 26-05 +1.0, 26-06 -2.0, 26-07 +2.0, 26-08 +5.4, 26-09 +1.9, 26-10 +2.0. That is 9/14 positive months; the worst month is -3.0R, against -8.1R for the baseline.
Streak-3 alone: 10/14 positive months, same worst month (-3.0R), April +0.9R.
On real MNQ futures (2026-08-06 .. 10-15) no setup was filtered: 17 trades, 53 % WR, +0.54R, PF 2.49, +$3,621, the same as the baseline.

Goal check: PF >= 1.3 on IS (2.27) and on OOS (1.65), 9/14 months positive, 81 trades, max DD $1.6k against a $10.5k net. The goal is met, but only just on trade count and months.

## What the year says (honest reading)

* **Almost all of the gain comes from the equity filter "skip after 3 consecutive losses".** It cuts the Feb-2026 loss cluster from -8.1R to -3.0R and the max DD from $3.0k to $1.6k. Net profit stays about the same, and OOS expectancy is unchanged (+0.26R).
  Neighbouring settings: streak 2 (72 trades, 7/14 months), streak 4 (90 trades, DD $2.2k, 9/14). Streak 3 is the best of these, but streak 2 and streak 4 also improve DD.
* **The regime filters do not generalise reliably.** Across all single filters, the IS score vs OOS expectancy correlation is -0.27, in both stage 1 and stage 2. Only half of the filters beat the baseline's OOS expectancy.
  The IS favourites (London ATR / daily ATR above a threshold, high prior-day range) look like IS fits. For example, vol_rel >= 0.06 has IS PF 2.43 but OOS PF 1.51.
* The most interesting filter is "skip when the 20-day daily ATR is in the top ~15 % of its 120-day range" (datr_pct <= 0.85). It is good IS and OOS (IS PF 1.72, OOS PF 2.68, 83 trades, 11/14 months, +$12.2k).
  With streak-3 it gives 72 trades and 11/14 months. It did not win the IS selection, and the OOS gain is larger than the IS gain, so treat it as a candidate to watch, not a proven edge.
* Weekday filters, rolling-R filters and weekly loss limits: no robust improvement. Weekly -2R was the best of these (98 trades, PF 1.56 R, 10/14, but worst month -5.1R).
* **NY AM 08:30-11:00 as a second rule set:** 10 of the 18 configs are positive in IS. The IS-best (min FVG 0.15 ATR, 2.5R) has IS PF 1.27 but OOS +0.04R (PF 1.06), with 105 trades and a DD of $5.8k.
  Adding it to Leto lowers the portfolio PF to 1.30 and raises DD to $4.4k, so it was rejected.
* Stop-first intrabar resolution and 2 or 3 ticks of slippage change almost nothing: the limit entries rarely fill and exit on the same bar.
