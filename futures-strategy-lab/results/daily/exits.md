# Daily direction "exits": quick partial exit on frequent FVG Pro entries

**Result: PASS, with caveats (see below).** 0.95 trades/day. WR 67.8 % in IS and 77.4 % in OOS. PF 1.76 IS / 3.16 OOS. 12 of 14 months
positive. It still passes with the worst-case intrabar model, a 1-minute replay and 2-tick slippage, and on about 50 days of real CME futures.

Code: `lab/daily_exits.py`. Data: Dukascopy 1m proxies resampled to 15m, 2025-09-01 → 2026-10-14, 291 Globex days (151 IS / 140 OOS).
IS = entry < 2026-04-01. OOS = entry ≥ 2026-04-01. A win means the position's net $ > 0. Costs are $0.62/side/contract.
Stop, BE, time and EOD exits pay 1 tick (2 ticks in the robustness runs). Flat at 15:55 NY.

## The system
Entries are unchanged FVG Pro (BOS + FVG, limit at the gap edge, stop beyond the BOS leg). All are 15m with max 1 trade per component per day:

| Component | Window (NY) | min FVG | don't chase (>1 ATR) |
|---|---|---|---|
| MNQ Asia | 20:00–24:00 | 0.15 ATR | yes |
| MNQ London | 02:00–05:00 | 0.3 | yes |
| MNQ NY AM | 08:30–11:00 | 0.3 | yes |
| MGC COMEX | 08:20–10:30 | 0.3 | no |
| MGC Asia | 20:00–24:00 | 0.3 | yes |

Daily rule: on each Globex day, take the first fill per market. That is max 1 MNQ + 1 MGC, so at most 2 trades per day. The rule is causal: only an earlier fill blocks a later one.
**Exit:** 3 contracts. 2 of them exit at +0.5R. The stop on the last contract moves to break-even from the next bar, and its target is 2R.
Anything still open after 8 bars is closed at the next bar's open (about 2 h 15 min). The "no follow-through" exit is not used.

| | Trades | /day | WR | Exp R | PF | Net $ | Max DD |
|---|---|---|---|---|---|---|---|
| IS (Sep–Mar) | 152 | 1.01 | 67.8 % | +0.098 | 1.76 | +12,086 | 2,798 |
| OOS (Apr–Oct) | 124 | 0.89 | 77.4 % | +0.225 | 3.16 | +16,224 | 810 |
| Full year | 276 | 0.95 | 72.1 % | +0.155 | 2.20 | +28,310 | 2,798 |
| worst-case intrabar + 2 ticks, IS / OOS | 152 / 124 | | 67.8 / 76.6 % | +0.097 / +0.212 | 1.74 / 2.87 | | |
| 1-minute replay + 2 ticks, IS / OOS | 152 / 124 | | 67.8 / 78.2 % | +0.094 / +0.234 | 1.74 / 3.27 | | |
| Real CME MNQ+MGC, 2026-08-06..10-15 (50 days) | 45 | 0.90 | 82.2 % | +0.244 | 2.17 | +4,361 | 922 |

The net $ figures are for 3 MNQ / 3 MGC contracts.
Monthly net $: 25-09 +1725, 10 −1701, 11 +1474, 12 −238, 26-01 +6423, 02 +3351, 03 +1053, 04 +1010, 05 +1430, 06 +4105, 07 +5282,
08 +1447, 09 +1884, 10 +1065 → **12/14 positive**. 208 of 291 days have at least one trade.
Exits: 142 time stops, 73 break-even after TP1, 39 full stops, 21 at the 2R runner target, 1 EOD.
Average win is +0.49R and average loss is −0.70R. The high WR comes from many small wins.

## How it was chosen (IS only) — 496 configurations
1. **Stage 1 (384 configs).** Entries: MNQ Asia, London and NY AM (min FVG 0.15 or 0.3, chase 1.0) plus MGC COMEX 0.3.
   Exit grid: TP1 0.5/0.75/1R × 1/2 or 2/3 × stop to BE or −0.5R × runner 2/3R × time stop 4/8/12/16 × no-follow-through off or 3 bars (+0.5R).
   - TP1 at 0.5R gives the highest WR: 64–68 % IS. TP1 at 1R gives the highest PF, but only 59 % WR.
   - Stop at −0.5R after TP1 cuts the WR by about 15 points, because many −0.5R exits count as losses. The no-follow-through exit also lowers the WR.
   - With min FVG 0.15 on all sessions, IS PF stays below 1.3: MNQ Asia and NY AM lose money in IS.
     With 0.3 everywhere, the rate is only 0.76 trades/day.
   - IS-rule pick (IS ≥ 0.8 trades/day, PF ≥ 1.3, exp > 0, ≥ 5/7 months, then highest WR): IS 58.0 %, PF 1.30. It is on the edge and fails with 2-tick slippage (1.28).
2. **Stage 2 (96 configs).** Min FVG chosen per session (Asia/London/NY AM, each 0.15 or 0.3) × 12 exits from the TP1 0.5R family.
   Same rule, with IS ≥ 0.85 trades/day. Pick: Asia 0.15 / London 0.3 / NY AM 0.3, with the exit above. IS 67.4 % / PF 1.41.
   OOS was 78 % / 3.26, but only 0.79 trades/day over the year (231 trades), 2 short of the bar.
3. **Stage 3 (16 configs).** Add one more 15m component, min FVG 0.3, chase on or off. The windows tried were MNQ pre-London and late London, MGC Asia, London, late London and NY PM, and MCL.
   Rule: max 2 trades/day, so MCL is excluded. The pick must have IS WR ≥ 58 %, PF ≥ 1.3, ≥ 0.9 trades/day and ≥ 5/7 positive months; among those, the best IS PF wins.
   Pick: **MGC Asia, chase on** (IS PF 1.76). All 16 candidates were also positive OOS (WR 73–78 %, PF 2.1–3.2), so the pick is not a lone IS peak.

## Robustness (neighbours, one change at a time; full-year WR, IS / OOS PF)
TP1 0.75R: 64.5 %, 1.72 / 2.42 · half at TP1: 71.7 %, 1.88 / 3.13 · stop to −0.5R: 72.1 %, 1.75 / 3.15 · runner 3R: 72.1 %, 1.77 / 3.16 ·
time stop 6 / 12 / 16: 69.6–73.2 %, IS PF 1.74–1.91, OOS PF 2.83–3.19 · NFT 3 bars: 68.8 %, 1.77 / 2.36 ·
MGC Asia min FVG 0.15: 70.9 %, 1.85 / 2.57 · without chase: 71.1 %, 1.75 / 2.26 · on 10m: 66.0 %, **1.16** / 1.89 · on 30m: 69.5 %, **1.25** / 1.99.
Every exit neighbour passes. Only moving the extra component off 15m breaks the IS PF.

## Caveats
- **IS is much weaker than OOS.** Apr–Oct was an easy period: every variant does better there.
  The IS figures (68 %, PF 1.76, +0.10R) are the realistic expectation.
- **The edge is thin per trade.** Expectancy is +0.10R in IS. A win is often only +0.3R, and a loss is about −0.7 to −1R.
  The WR is ≥ 60 % because 2/3 of the position is taken at +0.5R. Profit per trade is small and depends on costs.
- **MNQ Asia loses in IS** (50 trades, PF 0.61; OOS PF 2.84) and MNQ NY AM is weak (17 trades). They are kept for frequency.
  January 2026 (+$6.4k, gold volatility) accounts for a large part of the IS profit.
- **The search was not blind to OOS.** I saw the OOS columns of stage 1 before I designed stages 2 and 3, which were done to fix the IS frequency gap.
  Every pick was made by a rule written down beforehand using IS numbers only, but the order of the research was not blind.
- **`daily_portfolio`'s "conservative" intrabar is optimistic for limit entries**: after the fill it visits the far extreme.
  So I added a `worst` mode (adverse extreme first, and on the fill bar the favourable move is assumed to come before the fill) and use that, plus the 1-minute replay.
- No look-ahead: setups are decided at the bar close, orders rest from the next bar, and BE / time / NFT exits act from the next bar.
  The truncation check for the 5 entry streams passes. With BE and no NFT, the simulator matches `daily_portfolio.simulate` trade for trade.

Reproduce: `cd futures-strategy-lab && PYTHONPATH=. python -m lab.daily_exits grid` (45 s), `final`, `grid2`, `final 2`, `stage3`, `real`, `trunc`.
Outputs: `results/daily/exits_grid.json`, `exits_final.json`, `exits_grid2.json`, `exits_final2.json`, `exits_stage3.json`, `exits_real.json`.
