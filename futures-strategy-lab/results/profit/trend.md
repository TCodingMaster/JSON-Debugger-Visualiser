# profit / trend: higher-timeframe trend-following intraday (MNQ, MGC, MCL)

**Short answer:** MNQ "daily-trend pullback-bar breakout" holds up all year. The variant with a VWAP filter is profitable through the summer (Jun +4.4R, Jul +0.6R, Aug +2.4R), but it was **not** the in-sample pick. Under the strict protocol the goal is **not met**.

Code: `lab/prof_trend.py` (`PYTHONPATH=. python -m lab.prof_trend grid | stage2 | final | check`).
Simulation runs on **1-minute bars**. Signals come from completed 15m bars. Stop and limit orders work from the next minute. Inside a minute the stop is checked first, also on the fill minute. Trails update only at 15m closes. Costs: 1 tick slippage on stop entries, stop exits and EOD exits; 2 MNQ / 1 MGC / 1 MCL; commission $0.62 / $0.82 / $0.75 per side. All positions are flat at 15:55 NY.
Protocol: IS = entry < 2026-04-01 (selection), OOS = after. PF is the $ profit factor.
Truncation check (signals on data cut at 35/60/85 %): **OK** for all 9 trend × trigger combinations.

## Configurations tried: 526 grid + 27 neighbour re-runs
* Stage 1 (270): {MNQ, MGC, MCL} × trend {d20 = prior daily close vs 20-day EMA, h50 = 1h EMA50 side + slope, both} × trigger {ema = EMA20 touch then stop entry at the bar high, pbb = pullback bar (lower high in an uptrend) then stop entry at its high, fvg = 3-bar FVG then limit at the gap edge} × window {am, day} × exit {rr2, rr3, chandelier 2/3 ATR, prior-bar trail after +1R}.
* Stage 2 (256): MNQ + MGC, d20 trend, triggers pbb/ema × filter {none, close beyond session VWAP, daily EMA20 5-day slope, both} × window × exit {rr2, rr3, ch2, ch3} × max 1 or 2 trades a day.

## Findings
* **MGC and MCL: no trend rule holds OOS.** The best IS configs have IS PF 1.5-1.9 and OOS PF 0.4-1.0. The IS-OOS t correlation is 0.08 to 0.35. Gold and crude are rejected.
* **MNQ, d20 + pbb is the one family that is positive in every variant.** The IS-OOS t correlation is 0.74. The EMA-touch and FVG triggers do not work.
* **IS selection (highest IS t over 128 stage-2 MNQ configs): d20 / pbb / 09:45-12:00 / no filter / 2R / max 2 a day.**
  IS: 65 trades, 60 % WR, +0.43R, PF 1.85, +$6,648, DD $1,263. **OOS: 66 trades, 44 % WR, +0.05R, PF 1.06, +$809, DD $4,450.** Fails.
  The same rule with a ch3 trail does better OOS (PF 1.24, +0.24R) and is 11/14 months positive, but it is still below 1.3.
  All of the OOS damage comes from **shorts**: 16 OOS shorts, PF 0.44. Longs make OOS PF 1.47-1.94.
  July 2026 is negative in all of these variants.

## Closest result (post-hoc, NOT IS-selected): add a "close beyond the session VWAP" filter
Rule (MNQ 15m, decision time 09:45-14:00 NY):
* Trend: the prior RTH close is above (below) its 20-day EMA, so trade long (short) only.
* Setup bar: it closes above (below) the 15m EMA20 and above (below) the session VWAP, and it is a pullback bar (high below the prior bar's high for longs, low above the prior bar's low for shorts).
* Entry: buy stop 1 tick above the setup bar's high (sell stop 1 tick below its low for shorts), valid for 1 bar.
* Stop: below the lower low of the setup bar and the bar before it, minus 0.1 ATR. Setups with risk under 0.2 ATR or over 2.5 ATR are skipped.
* Exit: chandelier trail at 2 × ATR(15m) from the best completed-bar extreme. Flat at 15:55. At most 2 trades a day.

| set | trades | WR | exp R | PF | net $ | max DD $ |
|---|---|---|---|---|---|---|
| IS  | 96 | 46.9 % | +0.397 | 1.51 | +5,649 | 1,933 |
| OOS | 82 | 46.3 % | +0.391 | 1.83 | +9,175 | 2,178 |
| Year | 178 | 46.6 % | +0.394 | 1.67 | +14,824 | 2,178 |

Monthly R: 25-09 +5.2, 10 +8.7, 11 **-3.7**, 12 +11.7, 26-01 +4.8, 02 +4.0, 03 +7.4, 04 +10.3, 05 +8.9, 06 +4.4, 07 +0.6, 08 +2.4, 09 +2.5, 10 (partial) +3.0. That is **13/14 positive months**.
Robustness:
* 2 ticks slippage: IS PF 1.49 / OOS PF 1.81.
* Replay on 5-minute bars (coarser intrabar resolution): identical.
* Longs: IS PF 1.96 / OOS 2.01. Shorts: IS 1.28 / OOS 1.47.
* Every neighbour of the exit (rr2 to rr3, ch1.5 to ch3), the window (am) and the trade cap (1 or 3) has IS PF ≥ 1.42 and OOS PF ≥ 1.53, with 11 to 13/14 months positive.
* Real MNQ futures, 5m (2026-09-03 .. 10-15, after a warm-up): 15 trades, PF 1.14, +$233. Dukascopy on the same window: 15 trades, PF 1.18, +$284. The two match closely, but the sample is tiny.

**Why goal_met = false:** the VWAP filter was one of 4 filters set before stage 2 ran. Its family mean IS t was 1.91, against 2.39 for "no filter", so every IS criterion I tried (t-stat, PF, net/DD) picks the unfiltered rule, and that rule fails OOS. Picking the VWAP variant uses OOS information, so its OOS numbers are not an untouched test.
It is the most robust-looking rule set found here: it beats the FVG Pro Leto baseline on months (13 vs 10), on net ($14.8k vs $10.5k) and on DD ($2.2k vs $3.0k). It needs a fresh forward or real-futures sample before anyone trusts it.
