# daily / portfolio: about 1 trade per day from several FVG Pro rule sets. Result: FAIL

Code: `lab/daily_portfolio.py`.
* `PYTHONPATH=. python -m lab.daily_portfolio scan 15min [trend]` runs the component grid (for 5/10/15/30min).
* `... final` runs selection, portfolio, robustness and neighbours.
* `... real` runs the real-futures check.
* `... trunc` runs the truncation check, which passes.

Data: Dukascopy 1m (NQ, XAU, WTI proxies), 2025-09-01 .. 2026-10-14, 291 Globex days (IS 151, OOS 140).
IS means entries before 2026-04-01.
Costs: MNQ, MGC and MCL each trade 2 contracts so the partial exit can split 1+1. Commission is as in `data.py`, with 1 tick slippage.

## Rules (fixed for every component)
* **Entry:** the unchanged `fvg_pro.generate` setup (BOS + FVG, limit order at the gap edge). It is decided at the bar close and the order works from the next bar.
* **Chase filter (optional):** skip the setup if side*(close-entry)/ATR > 1.0 at the signal bar.
* **Exit:** half the position at 1R, then the stop moves to BE, and the runner targets 3R. Time stop 8 bars, flat at 15:55 or at the new Globex day.
* **Daily limits:** max 1 trade per component per day.
* **Portfolio rule:** per Globex day either the FIRST filled trade across the portfolio ("first"), or the first trade per market ("1/market").
* **Simulator:** a copy of `wr60_exits.simulate`, plus switches for slippage ticks, conservative intrabar (adverse extreme first) and a 1-minute replay. It reproduces Leto exactly: 70 trades, 67.1 %, PF 2.50. It also reproduces MGC COMEX exactly: 78 trades, 60.3 %, PF 1.70.

## Search (408 component configs + about 60 portfolio/robustness/neighbour evaluations)
* **Component grid:** 3 markets × 5-6 windows (asia 20-24, pre-London 00-02, London 02-05, late London 05-08, NY AM 08:30-11 / COMEX 08:20-10:30 / NYMEX 09-11:30, NY PM 13-15) × min FVG {0.15, 0.3} × chase {off, 1.0} × TF {5, 10, 15, 30 min}. That is 272 configs. The 1h trend filter was added on 10 and 15 min, which is 136 more.
* **Eligibility (IS only):** at least 20 IS trades, IS WR ≥ 60 %, IS PF ≥ 1.3. For each market+window, the best IS PF is kept.
* **Result of the grid:** only 5 market+windows qualified. Without the trend filter, only 4.
  * The FVG Pro family is mostly at 45-58 % WR with this exit.
  * MNQ Asia, NY AM, NY PM at 15m, MGC London and MCL NYMEX all stay under 60 % or under PF 1.3 in IS.

| Selected component (IS) | IS n / WR / PF | OOS n / WR / PF |
|---|---|---|
| MGC 15m Asia, mf 0.15, chase, trend | 28 / 64 % / 3.66 | 19 / 37 % / 0.47 |
| MNQ 10m NY PM 13-15, mf 0.3, chase | 21 / 67 % / 3.63 | 18 / 50 % / 1.25 |
| MNQ 15m London, mf 0.3, chase, trend | 22 / 68 % / 3.03 | 24 / 67 % / 2.98 |
| MNQ 30m 05-08, mf 0.15, chase | 22 / 68 % / 2.28 | 14 / 43 % / 0.52 |
| MCL 15m NY PM, mf 0.15, chase | 25 / 68 % / 1.74 | 5 / 80 % / 12.4 |

Only the London component survives OOS. The others are IS luck: with about 20-30 trades the standard error of WR is about 9-10 points, and they were picked from 408 configs.

## Portfolios (base = TradingView path, 1 tick)
| Portfolio | trades/day | IS WR / PF | OOS WR / PF | year WR / PF / net / DD | + months |
|---|---|---|---|---|---|
| A strict, first/day | 0.52 | 70.9 % / 3.76 | 52.3 % / 0.88 | 62.9 % / 1.86 / +$11.0k / $3.3k | 9/14 |
| A strict, 1/market/day | 0.61 | 68.9 % / 3.23 | 54.9 % / 0.96 | 63.3 % / 1.82 / +$11.9k / $3.1k | 11/14 |
| B = A + MGC COMEX, first/day | 0.65 | 65.7 % / 2.35 | 55.6 % / 1.11 | 61.4 % / 1.69 / +$12.2k / $1.7k | 10/14 |
| **B, 1/market/day (closest)** | **0.83** | **66.0 % / 2.54** | **58.0 % / 1.17** | 62.7 % / 1.80 / +$17.0k / $2.0k | 10/14 |

* **Variant B:** MGC COMEX 08:20-10:30 (mf 0.3, no chase) is the previously verified gold rule. Its IS WR is 57.8 %, so it does not meet the 60 % gate. It is added from prior knowledge, so its selection is not clean.
* **B 1/market/day under each check:**

  | Check | OOS WR / PF | Year exp | Year trades/day |
  |---|---|---|---|
  | conservative intrabar | 60.0 % / 1.23 | +0.20R | 0.83 |
  | 2 ticks of slippage | 58.0 % / 1.16 | — | — |
  | conservative + 2 ticks | 60.0 % / 1.22 | — | — |
  | 1m replay | 57.0 % / 1.12 | — | — |

* **B monthly $:**

  | Month | 25-09 | 25-10 | 25-11 | 25-12 | 26-01 | 26-02 | 26-03 | 26-04 | 26-05 | 26-06 | 26-07 | 26-08 | 26-09 | 26-10 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
  | $ | +1353 | +2052 | +3185 | −265 | +4572 | +2651 | +1452 | +1380 | +516 | −1485 | +1254 | −460 | +962 | −210 |

* **Neighbours of A** (each component moved one step in mf, chase or TF; 30 runs): OOS PF 0.67-1.16 and OOS WR 44-58 %. None of them gets OOS PF to 1.3.
* **Real CME futures** (2026-08-06..10-15, MNQ and MGC only, first/day):
  * A: 20 trades, 45 %, PF 0.81 (the proxy on the same window gave PF 0.82).
  * B: 30 trades, 53 %, PF 1.08 (the proxy gave PF 0.88).

## Verdict
**Nothing passes.** The closest result is B 1/market/day.
* It meets these criteria: 0.83 trades/day, 10/14 months positive, and IS WR 66 %.
* OOS PF 1.17 misses the 1.3 bar. OOS WR is at the 58 % limit (57-60 % depending on the fill model).
* Its OOS edge depends on the London and COMEX legs, which are the two that were already known. The newly found legs (MGC Asia, MNQ late London, MNQ NY PM) lost their IS win rate out of sample.

With this exit, the FVG Pro family has only about two sessions (MNQ London with chase, MGC COMEX) that hold about 60 % WR over the whole year. Each gives about 0.25 trades/day. Adding other sessions or markets to reach about 1 trade/day lowers OOS WR to about 52-58 % and OOS PF to about 0.9-1.2.

An honest daily-trade version of this family therefore means accepting about 55 % WR, or keeping about 0.5 trades/day at about 65 %.
