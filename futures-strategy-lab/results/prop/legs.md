# Prop direction "legs": add bar-shift-robust FVG Pro legs to Leto. Result: FAIL

Code: `lab/prop_legs.py`. Outputs: `results/prop/legs_grid.json` (792 configs × every bar offset), `legs.json`
(selection, gate, portfolios), `legs_real.json` (real CME check).
Data: Dukascopy 1m proxies, 2025-09-01 .. 2026-10-14, 291 Globex days (IS 151 / OOS 140). IS = entry < 2026-04-01.
Costs: `data.py` commissions, 2 contracts per leg (MNQ / MGC / MCL), 1 tick slippage on stop / BE / time / EOD exits.
Win = position net $ > 0. Winning day = Globex-day net >= +$150.

## Rules
* **Every leg** uses the unchanged Leto family: `fvg_pro.generate` (BOS + FVG, limit at the gap edge), with an optional chase filter (skip if side*(close-entry)/ATR > 1.0). The exit is half at 1R, then BE, then the runner at 3R. Time stop 8 bars, flat 15:55 NY, max 1 trade per leg per Globex day.
* **Free choices per leg:**
  * market: MNQ, MGC or MCL
  * timeframe: 5, 10, 15 or 30 min
  * window: one of 11 (18-20, 20-24, 00-02, 02-05, 05-08, 08:20-10:30, 08:30-11, 09:30-11:30, 11:30-13:30, 13-15, 14-15:45)
  * min FVG: 0.15, 0.3 or 0.45
  * chase filter: off or 1.0
  * That gives **792 configs**, each one run at shift 0 and at bar offsets 1-4 min (1-2 min for 5m), so 3,564 runs.
* **Portfolio:** max 1 trade per leg per day. Each market takes at most the first 2 fills per Globex day, and only an earlier fill blocks a later one.
* **Truncation check** (`trunc`: generate + chase on df[:k] versus the full df, on shift 0 and shift 1): passes.

## Selection rule (pre-registered in the module docstring before any OOS number was read; IS only)
1. **IS eligibility.** All of these must hold:
   * at least 20 IS trades at shift 0
   * IS WR >= 55 % at shift 0, and a mean IS WR >= 55 % over all shifts
   * IS PF >= 1.15 at every shift, and a median IS PF >= 1.30
2. **Score and pick.** The score is the minimum IS PF over the shifts. Configs are picked greedily in score order.
   * The two Leto legs are put in first.
   * A config is skipped if its market already has a leg in an overlapping window.
3. **Mandatory gate.** IS PF >= 1.15 **and** OOS PF >= 1.15 at every offset. This is applied to all legs, including Leto.

Only 19 of 792 configs were IS-eligible. The rule picked 5 new legs:
* MCL 10m 13-15 mf0.45
* MNQ 5m 14-15:45 mf0.3
* MNQ 30m 05-08 mf0.3
* MNQ 10m 11:30-13:30 mf0.15
* MGC 30m Asia mf0.3

## Bar-shift gate (IS PF / OOS PF at offset 0,1,2,3,4)
| Leg | s0 | s1 | s2 | s3 | s4 | Gate |
|---|---|---|---|---|---|---|
| MNQ 15m London mf0.3 chase (Leto) | 2.05/3.06 | 2.36/1.76 | 1.76/2.45 | 1.62/3.76 | 1.94/2.31 | **PASS** |
| MGC 15m COMEX mf0.3 (Leto) | 1.66/1.77 | 1.66/1.34 | 1.87/2.08 | 2.04/1.51 | 1.71/**1.01** | fail (s4) |
| MCL 10m NY PM mf0.45 | 2.68/1.01 | 4.05/1.87 | 3.59/1.59 | 4.10/0.88 | 3.08/0.58 | fail |
| MNQ 5m 14:00-15:45 mf0.3 | 1.94/0.89 | 1.77/0.75 | 2.36/1.72 | – | – | fail |
| MNQ 30m 05-08 mf0.3 | 2.08/0.50 | 1.67/0.35 | 3.09/0.49 | 2.03/0.49 | 1.67/0.38 | fail |
| MNQ 10m 11:30-13:30 mf0.15 | 1.64/1.74 | 1.75/1.36 | 1.84/1.55 | 2.25/**0.84** | 1.69/**1.11** | fail |
| MGC 30m Asia mf0.3 | 1.43/0.46 | 1.29/0.39 | 1.47/0.32 | 2.37/0.61 | 1.41/0.52 | fail |

**Diagnostic, with hindsight and not used for selection.** Across all 792 configs, only **one** passes the gate with at least 10 trades in each half at every offset: Leto MNQ London.
* 16 configs pass the literal gate, but 15 of them have only 1-15 trades in a half.
* 66 configs keep IS PF >= 1.15 at every offset (with at least 10 trades). Only Leto London of those 66 also holds OOS.
* The new legs' high IS figures across shifts are bar-robust in IS, but they are still IS luck. They pass the bar-shift test and fail the time-split test.

## Portfolios (base = TradingView path, 1 tick)
| Portfolio | Trades (IS/OOS) | /week | /day | WR full (IS/OOS) | Exp R | PF IS / OOS | Net $ | Max DD | + months | Win days/wk | Worst day | Trail EOD DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Leto (London + COMEX) | 148 (80/68) | 2.54 | 0.51 | 63.5 % (61.3/66.2) | +0.217 | 1.76 / 2.25 | +11,625 | 1,382 | 12/14 | 0.98 | −870 | 1,382 |
| IS-selected, pre-gate (7 legs) | 417 (211/206) | 7.16 | **1.43** | 55.6 % (60.2/**51.0**) | +0.101 | 1.77 / **1.04** | +15,536 | 3,404 | 9/14 | 1.39 | −1,253 | 3,404 |
| Gated (only Leto London) | 70 (35/35) | 1.20 | 0.24 | 67.1 % (65.7/68.6) | +0.256 | 2.05 / 3.06 | +5,626 | 583 | 12/14 | 0.45 | −502 | 583 |

**Robustness of the pre-gate portfolio:**

| Check | Full PF | OOS PF | OOS WR |
|---|---|---|---|
| 2-tick slippage | 1.35 | 1.03 | 51.0 % |
| Conservative intrabar | 1.43 | 1.07 | 52.4 % |
| Conservative + 2 ticks | 1.41 | 1.06 | 52.4 % |
| 1m replay | 1.38 | 1.05 | 51.0 % |
| Bar shift 1 | – | 0.91 | – |
| Bar shift 2 | – | 1.14 | – |
| Bar shift 3 | – | 1.08 | – |
| Bar shift 4 | – | 0.97 | – |

* Pre-gate OOS prop metrics: 1.25 winning days/week, and only 48 % of the traded days are positive.

**Robustness of Leto:**

| Check | Full PF | WR |
|---|---|---|
| Base | 1.94 | 63.5 % |
| 2-tick slippage | 1.92 | – |
| Conservative intrabar | 1.93 | – |
| 1m replay | 1.94 | – |
| Bar shifts 1-4 | 1.58-2.05 | 59-63 % |

* The weakest bar shift for Leto is shift 4: OOS PF 1.42.

Monthly $ of the pre-gate portfolio:

| Month | 25-09 | 25-10 | 25-11 | 25-12 | 26-01 | 26-02 | 26-03 | 26-04 | 26-05 | 26-06 | 26-07 | 26-08 | 26-09 | 26-10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| $ | +2815 | +1329 | −71 | −357 | +2120 | +2511 | +6188 | +2277 | +1267 | −1874 | +1209 | −1744 | +1370 | −1505 |

**Real CME futures, 2026-08-06..10-15** (MNQ/MGC only; there is no real MCL, so the MCL leg is left out):

| Portfolio | Real: trades / WR / PF | Proxy, same window: WR / PF |
|---|---|---|
| Leto | 25 / 60 % / 1.91 | 67 % / 2.48 |
| Pre-gate | 68 / 40 % / **0.65** | 45 % / 0.81 |
| Gated (London only) | 11 / 64 % / 3.07 | – |

## Verdict
**Nothing passes.** The goal was at least 1.4 trades/day, portfolio WR >= 58 % and OOS PF >= 1.3.

The only portfolio that reaches the frequency is the IS-selected pre-gate one:
* 1.43 trades/day, 7.2 trades/week
* full-year WR 55.6 %, OOS WR 51.0 %
* OOS PF 1.04
* 1.39 winning days/week
* It fails the gate on 5 of its 7 legs, and it loses on real futures (PF 0.65).

Under the mandatory bar-shift gate, **only MNQ London survives**. MGC COMEX misses narrowly (OOS PF 1.01 at the +4 min offset).

So within the Leto rule family, the honest frequency is:
* about 0.24 trades/day (London only, which passes every check), or
* about 0.5 trades/day (Leto London + COMEX, OOS PF 2.25, 1 winning day/week), accepting COMEX's single weak offset.

Adding legs from other markets, timeframes, windows or min-FVG settings does not add edge that survives both the bar-shift test and the time split.

Reproduce: `cd futures-strategy-lab && PYTHONPATH=. python -m lab.prop_legs grid` (3.5 min on 4 cores), then `final`, `trunc` and `real`.
