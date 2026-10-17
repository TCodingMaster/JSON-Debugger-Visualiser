# daily / levels: sweep of PDH/PDL, ON, Asia or London high/low, then FVG / IFVG reversal. Result: FAIL

Code: `lab/daily_levels.py`. Run it with `PYTHONPATH=. python -m lab.daily_levels <cmd>`:
- `trunc` runs the no-look-ahead check. It passes for 15m FVG, 15m FVG+IFVG and 5m-after-15m-sweep.
- `grid` and `grid2` run the two grids.
- `final` runs the portfolios plus the robustness and neighbour checks.
- `real` runs the check on real CME futures.

Data: Dukascopy 1m proxies covering 2025-09-01..2026-10-14, 291 Globex days (151 IS, 140 OOS). IS means entry before 2026-04-01.

Execution: the simulator is `daily_portfolio.simulate`, which matches `wr60_exits`.
- Positions are 2 contracts. Half exits at 1R, then the stop moves to BE, and the runner targets 3R.
- Time stop is 8 bars. Flat at 15:55.
- Costs follow `data.py`, with 1 tick of slippage.
- A win is a position with net $ > 0.

## Rules (short side; long mirrors it)
- **Levels:** PDH, ONH (known at 09:30), Asia high (known at 00:00) and London high (known at 05:00).
  - A level becomes armed after a bar closes below it.
  - A sweep is a later bar, inside the window, whose high goes above the level. Each level can be swept once per day.
- **Entry, within `look` bars after the sweep:**
  - **FVG:** a bearish FVG that forms after the sweep bar. A limit order sits at its near edge or at its CE.
  - **IFVG:** a bullish FVG from the `ifvg_back` bars up to the sweep, which a close then goes through. A limit order sits at the gap bottom.
  - In both cases the stop is the sweep extreme + 2 ticks. The setup is cancelled on a close beyond the far edge, or after 8 bars.
- **5m variant:** the sweep only counts once the 15m bucket that contains it has closed back inside the level. The FVG/IFVG is then taken on 5m.
- **Options:**
  - reclaim (a close back inside is required);
  - chase filter;
  - 1h trend filter (20h EMA slope), either with the trend or against it;
  - stop at the FVG far edge instead of the sweep extreme.

## Search: 516 strategy configs + 2 portfolios + 23 neighbours (about 545 in total)
- **Grid 1 (324 configs):** MNQ and MGC × level set {pd, sess, all} × window {London 02-05, NY 08:30-11:30, day 00-11:30} × {fvg, ifvg, both} × min FVG {0.15, 0.3} × reclaim on 15m. Also the 5m-after-15m-sweep version.
  - Mean WR was 47.7 % IS and 45.2 % OOS. The IS→OOS WR correlation was −0.11.
  - The 5m-after-15m versions reached 41-55 % OOS WR.
  - The top IS-WR configs (64-74 %) have only 11-30 trades. They fell to 33-47 % OOS.
- **Grid 2 (192 configs), all-day bases:** entry edge/ce × stop sweep/FVG × trend {off, with, against} × chase × level set × {15m, 5m-after-15m}.
  - Mean WR was 39 % IS and 44 % OOS. The FVG-edge stop drops WR to about 32 %.
  - No config with at least 0.4 trades/day reaches 58 % IS WR.
  - **Selection (IS only), best IS WR per market among configs with ≥ 0.4 trades/day:**
    - MGC: 15m, Asia/London/ON levels, CE entry, counter-trend. IS 57.7 % / PF 1.14, OOS 64.6 % / PF 1.88.
    - MNQ: 15m, all levels, CE, counter-trend. IS 52 % / PF 0.99, OOS 46 % / PF 0.75.

## Closest result: daily portfolio, at most 1 trade per market per day
The portfolio is the two existing verified legs (Leto MNQ London and MGC COMEX) plus the new levels legs.

| Portfolio (standard :00 bars) | trades/day | IS WR / PF | OOS WR / PF | Year WR / exp / PF / net / DD | + months |
|---|---|---|---|---|---|
| P3 Leto+COMEX+lvlMGC | 0.797 | 59.3 % / 1.37 | 67.0 % / 2.16 | 62.5 % / +0.20R / 1.62 / +$13.9k / $2.9k | 13/14 |
| P4 = P3 + lvlMNQ | 1.19 | 58.2 % / 1.32 | 60.5 % / 1.51 | 59.2 % / +0.17R / 1.40 / +$14.0k / $3.2k | 11/14 |

- **Fill-model checks:** both hold up under conservative intrabar, 2-tick slippage, conservative + 2 ticks, and 1-minute replay.
  - P4 IS ranges over 58.2-59.8 % WR and PF 1.31-1.35.
  - P4 OOS ranges over 60.5-62.5 % WR and PF 1.43-1.51.
- **Real CME futures, 2026-08-06..10-15:**
  - P4: 53 trades, 57 % WR, PF 1.37. The proxy over the same window gave 62 % WR and PF 1.56.
  - P3: 57 % WR, PF 1.48.
- **Neighbours of P4** (each levels parameter moved one step, 23 runs):
  - IS WR 54-59 %, IS PF 1.15-1.67.
  - OOS WR 57-63 %, OOS PF 1.24-1.89.

**Bar-alignment test, which fails.** For this test the 15m bars are rebuilt from the 1m data, shifted by 1-4 minutes.

| Shift | P4 IS WR / PF | P4 OOS WR / PF | lvlMGC alone IS PF | lvlMNQ alone IS PF | Leto alone IS / OOS PF | COMEX alone IS / OOS PF |
|---|---|---|---|---|---|---|
| 0 | 58.2 % / 1.32 | 60.5 % / 1.51 | 1.14 | 0.99 | 2.05 / 3.06 | 1.66 / 1.77 |
| 1 | 52.8 % / 1.07 | 56.5 % / 1.37 | 0.76 | 0.67 | 2.36 / 1.76 | 1.66 / 1.34 |
| 2 | 49.4 % / 0.91 | 53.3 % / 1.28 | 0.57 | 0.64 | 1.76 / 2.45 | 1.87 / 2.08 |
| 3 | 56.7 % / 1.28 | 57.8 % / 1.49 | 1.09 | 0.90 | 1.62 / 3.76 | 2.04 / 1.51 |
| 4 | 56.1 % / 1.16 | 56.6 % / 1.39 | 0.80 | 1.01 | 1.94 / 2.31 | 1.71 / 1.01 |

## Verdict
**Nothing passes.** Sweep + FVG/IFVG reversal on these levels is a coin flip:
- WR is about 45-50 % with this exit, on 15m and on 5m-after-15m, for both MNQ and MGC.
- The IS ranking does not predict OOS.

The only pass-looking result is P4 at standard bar alignment. It meets every numeric criterion on paper, and it holds under the conservative fill model, 2 ticks of slippage and the 1m replay. It still fails, for two reasons:
1. **The levels legs are bar-alignment luck.** Shifting the bars by 1-4 minutes moves the MGC levels leg to IS PF 0.57-1.09, and P4 drops to IS WR 49-57 %.
2. **Most of the edge comes from the two existing legs.** The MNQ levels leg loses money on its own (year PF 0.85).

Both existing FVG Pro legs pass the alignment test. Leto keeps IS PF 1.6-2.4 and OOS PF 1.8-3.8 at every shift. That is new evidence that those two legs are real.

The honest daily option is unchanged: Leto + COMEX at about 0.5 trades/day and 62-67 % WR. Adding sweep-level trades to reach 1 trade/day adds noise, not edge.
