# Prop direction "daily": more trades per day from day-management rules inside the Leto sessions. Result: FAIL on the frequency goal

**Bottom line.** Day-management rules hardly add trades. FVG Pro gives only about one BOS+FVG setup per session window. The 8-bar time stop (2 h) also uses up most of a 3 h window.

- The best rule, picked on IS only, is MNQ London widened to 01:00–07:00 with "a 2nd trade only after a loss or a time-stop exit", combined with the Leto COMEX leg. The widened MNQ leg passes the bar-shift protocol.
- This raises the portfolio from **2.39 to 3.15 trades/week**, or 0.48 to 0.64 trades/day. The target was 7/week (1.4/day).
- Winning days (≥ $150 at 2 MNQ + 2 MGC) rise from **1.02 to 1.15 per week**.
- OOS PF is 2.19 (Leto 2.52). Every bar offset stays at or above an OOS PF of 1.93.
- Payout weeks: not one of the 59 weeks has 5 winning days, in either version.
- What makes it look better is fragile. The extra 01:00–02:00 and 05:00–07:00 entries have **IS PF 0.98**. The IS gain comes from 5 second-of-day trades that all won.
- On real CME data (50 days) the new version is weaker than Leto: PF 1.32 vs 1.91.

Code: `lab/prop_daily.py`. Data: Dukascopy 1m proxies → 15m, 2025-09-01..2026-10-14, 291 Globex days (151 IS / 140 OOS), 59 weeks.
IS = entry < 2026-04-01.
Costs: data.py commissions, 1 tick on stop/BE/time/EOD exits. Each leg trades 2 contracts so the half-out at 1R splits 1+1.
A win means the position's net $ > 0. A winning day means the day's net is ≥ $150.

## Rules tested (entries = unchanged Leto: fvg_pro.generate, min FVG 0.3, edge limit, chase 1.0 on MNQ / off on MGC; exit ½ at 1R → BE → 3R, time stop 8 bars, flat 15:55)

| Rule | Meaning |
|---|---|
| max1 | 1 trade/day (Leto) |
| anyN | up to N trades, any outcome |
| lossN | next trade only if the previous one lost: "stop for the day after the first winner" |
| timeN | next trade if the previous one lost OR ended by the time stop (direction item d) |
| greenN | next trade only while the day's net is ≤ 0 |
| +lsL | daily loss stop: no new trade once the day's R sum is ≤ −L (1.5 or 2) |

Windows tested:
- MNQ: 02–05 (Leto), 01–05, 02–06, 02–07, 01–06, 01–07.
- MGC: 08:20–10:30 (Leto), 08:20–11:30, 08:00–11:00, 08:20–12:30, 07:30–11:30.

That is 154 leg configs, each run at bar offsets 0..4 min (770 simulations). A setup can only be armed while flat, so every earlier trade of the day is already closed when the gate is checked. The rules are causal.

Cross-market rule: skip MGC for the day once MNQ's closed trades already make ≥ X $, with X ∈ {off, 75, 150}. It was chosen on IS winning days/week, and X = 75 was picked.

**Truncation check** (`trunc`) passes:
- setups on df[:k] equal setups on the full df;
- gated trades closed before the cut are identical at k = 6000/15000/22000, offsets 0 and 2;
- the gate max1 reproduces DP.simulate trade for trade: Leto MNQ gives 70 trades, 67.1 %, PF 2.50, and COMEX gives 78 trades, 60.3 %, PF 1.70.

## Selection rule (fixed in the code docstring before OOS was looked at; the grid prints IS only)

**Eligibility, per market.** A config qualifies if it has:
- IS PF ≥ 1.30, IS WR ≥ 55 %, IS expectancy > 0;
- at least 5 of 7 IS months positive;
- IS PF ≥ 1.15 at every offset.

**Pick.** The eligible config with the most IS green days per week, with IS PF as the tie-break.

**Acceptance (protocol).** IS PF and OOS PF must both be ≥ 1.15 at every offset 0..4. A pick that fails is not re-picked; the market falls back to Leto.

**Size.** k = the largest number of units (one unit = 2 MNQ + 2 MGC) whose IS max trailing end-of-day DD is ≤ $1,500. The result was k = 1.

| Pick | IS | OOS | IS PF @ offset 0/1/2/3/4 | OOS PF @ offset 0/1/2/3/4 | Accepted |
|---|---|---|---|---|---|
| MNQ 01–07, time2 | 59 tr, 55.9 %, +0.186R, PF 1.52 | 62 tr, 64.5 %, +0.191R, PF 2.14 | 1.52 1.82 1.32 1.50 1.72 | 2.14 2.55 3.49 3.60 2.87 | **yes** |
| MGC 07:30–11:30, any2 | 77 tr, 58.4 %, PF 1.50 | 59 tr, 59.3 %, PF 1.17 | 1.50 1.26 1.16 1.17 1.19 | 1.17 1.05 1.50 1.14 **0.92** | **no** → Leto COMEX kept |

Leto COMEX itself also misses the per-leg shift bar: its OOS PF by offset is 1.77 / 1.34 / 2.08 / 1.51 / **1.01**. It is kept only as the existing baseline leg.

## Per leg (base: 1 tick, path intrabar; 2 contracts)

| Leg | Trades (/wk) | WR | Exp R | PF | Net $ | Max DD | +months | IS PF / OOS PF | Win days ≥$150 /wk | Worst day | Trailing EOD DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Leto MNQ 02–05 max1 | 70 (1.19) | 67.1 % | +0.256 | 2.50 | 5,626 | 583 | 12/14 | 2.05 / 3.06 | 0.44 | −502 | 583 |
| **MNQ 01–07 time2** | 121 (2.05) | 60.3 % | +0.189 | 1.82 | 7,590 | 1,257 | 12/14 | 1.52 / 2.14 | 0.66 | −636 | 1,054 |
| Leto MGC COMEX max1 | 78 (1.32) | 60.3 % | +0.183 | 1.70 | 5,999 | 1,030 | 8/14 | 1.66 / 1.77 | 0.61 | −611 | 1,030 |

Robustness of MNQ 01–07 time2 (IS / OOS PF): 2-tick slippage 1.51 / 2.12; conservative intrabar 1.50 / 2.12; conservative + 2 ticks 1.48 / 2.10; 1-minute replay 1.52 / 2.14; 1-minute replay + 2 ticks 1.51 / 2.12.

## Portfolio (MNQ + MGC, 2 + 2 contracts, k = 1)

| | Trades | Trades/wk | WR | Exp R | PF | Net $ | Max DD | +months | Win days/wk (≥$150) | Green days/wk | Worst day | Trailing EOD DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Leto (1/day each), full year | 141 | 2.39 | 64.5 % | +0.236 | 2.02 | 11,655 | 1,382 | 12/14 | 1.02 | 1.37 | −870 | 1,382 |
| Leto, IS / OOS | 78 / 63 | 2.52 / 2.17 | 61.5 / 68.3 % | +0.228 / +0.247 | 1.76 / 2.52 | | | | 1.06 / 0.93 | | −870 / −410 | 1,382 / 813 |
| **Daily-rule portfolio**, full year | 186 | 3.15 | 60.8 % | +0.201 | 1.80 | 13,271 | 1,789 | 11/14 | 1.15 | 1.75 | −870 | 1,478 |
| Daily-rule, IS / OOS | 101 / 85 | 3.26 / 2.93 | 56.4 / 65.9 % | +0.189 / +0.215 | 1.57 / 2.19 | | | | 1.19 / 1.03 | 1.61 / 1.79 | −870 / −636 | 1,478 / 966 |

The daily-rule portfolio under each robustness check (IS / OOS PF; OOS winning days/wk):

| Check | IS PF | OOS PF | OOS winning days/wk |
|---|---|---|---|
| 2 ticks | 1.55 | 2.17 | 1.03 |
| conservative intrabar | 1.57 | 2.06 | 1.03 |
| conservative + 2 ticks | 1.56 | 2.04 | 1.03 |
| 1-minute replay | 1.57 | 2.19 | 1.03 |
| 1-minute replay + 2 ticks | 1.55 | 2.17 | 1.03 |
| offset 1 min | 1.69 | 2.09 | 1.10 |
| offset 2 min | 1.61 | 2.70 | 1.14 |
| offset 3 min | 1.96 | 2.32 | 1.14 |
| offset 4 min | 2.02 | 1.93 | 1.10 |

For comparison, Leto at offsets 1..4 has OOS PF 1.63 / 2.19 / 1.99 / 1.57.

**Bigger size (not selected; IS DD over $1,500).** Winning days/week at 4 + 4 contracts:

| Portfolio | IS winning days/wk | OOS winning days/wk | IS / OOS trailing EOD DD | Weeks with ≥ 3 winning days | Weeks with ≥ 5 winning days |
|---|---|---|---|---|---|
| Daily-rule portfolio | 1.55 | 1.45 | $2,955 / $1,931 | 12 of 59 | 0 |
| Leto | 1.35 | 1.14 | $2,764 / $1,625 | 8 | 0 |

At 6 + 6 contracts the daily-rule portfolio has 1.58 / 1.62 winning days/wk and a trailing DD of $4.4k. **The 5-winning-day payout week never happens:** there are at most 0.67 trades per day.

## Why the rules barely help (post hoc, not used for selection)

- **The extra trades are few.** In Leto's 02–05 window, every re-entry rule gives the same trades as max1: 35 IS / 35 OOS. "any" adds one IS trade, and that trade loses. Re-entries in COMEX add 2 IS / 1 OOS trades.
- **The window gives the frequency, the day rule protects it.**
  - MNQ 01–07 with max1 is poor: IS PF 1.08. Early 01:00 trades block the London trade.
  - "loss2" lifts it to 1.31, and "time2" to 1.52.
  - The 2nd trades of the day: 8 in total (5 IS, 3 OOS), all winners, +1.30R on average. That is too small a sample to trust.
  - The MNQ entries outside 02–05 have IS PF 0.98 (22 trades, 40.9 % WR) and OOS PF 1.88 (26 trades).
- **A cleaner but less frequent variant.** MNQ 02–07 time2 has IS PF 1.79 / OOS PF 2.34. Its minimum PF across offsets is 1.65 IS / 1.90 OOS, with 61 % IS WR and 1.58 trades/wk. The rule ranked it just below 01–07 (0.94 vs 0.97 IS green days/wk).
- **Wider COMEX windows fail OOS.**
  - 08:00–11:00: OOS PF 1.11, worst offset 0.86.
  - 07:30–11:30: OOS PF 1.17–1.29, worst offset 0.92.
  - 08:20–12:30: IS PF 0.99.

## Real CME futures check (Yahoo 5m → 15m, 2026-08-06..10-15, about 50 days)

| | Trades | WR | Exp R | PF | Net $ | DD |
|---|---|---|---|---|---|---|
| Leto, real | 25 | 60.0 % | +0.231 | 1.91 | 1,588 | 843 |
| Leto, proxy (same dates) | 24 | 66.7 % | +0.292 | 2.48 | 2,045 | 813 |
| Daily-rule portfolio, real | 33 | 54.5 % | +0.139 | 1.32 | 885 | 938 |
| Daily-rule portfolio, proxy | 33 | 57.6 % | +0.134 | 1.41 | 1,072 | 813 |

On these 50 days the extra 8 trades lost money, on both real and proxy bars.

## Verdict

- **Protocol:** the new MNQ leg passes. Its IS/OOS PF is ≥ 1.15 at every offset, it holds up under the cost and intrabar checks, and OOS PF is ≥ 1.3.
- **Goal:** not met. 3.15 trades/week, against the 7/week (1.4/day) target, and 1.15 winning days/week at 2 + 2 contracts. The WR drops from 64.5 % to 60.8 %.
- **How much to trust it:** the gain over Leto is small. It rests on the 5 IS second-of-day winners and on the easy OOS half, and real CME data does not confirm it.
- **Recommendation:** keep Leto's 1 trade/day. If more frequency is wanted, the most defensible change is **MNQ 02–07 with time2**: about +0.4 trades/wk, and robust at every offset. Weekly 5-winning-day payouts need more independent setups (more markets or sessions), and earlier directions found those do not hold OOS. Day management inside two sessions cannot produce them.

Reproduce: `cd futures-strategy-lab && PYTHONPATH=. python -m lab.prop_daily trunc` · `grid` (35 s; prints IS only; writes `results/prop/daily_grid.json`) · `final` (`daily.json`) · `real` (`daily_real.json`) · `diag` (`daily_diag.json`).
