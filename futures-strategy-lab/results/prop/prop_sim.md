# Prop direction "prop": prop-firm simulation of Leto and the best verified extended portfolio. Result: Leto passes a Topstep-style 50K evaluation about half the time, but over 3 months it pays out only about $50–80/month in expectation

**Bottom line**

- **Recommended set-up (chosen on IS only): Leto at 4 MNQ + 1 MGC (MCL 0) on a Topstep-style 50K account.**
  - **IS:** pass 44.8 %, median 41 trading days to pass, P(max-loss breach within 3 months) 7.2 %. Expected trader payout $51/month. 0.97 winning days per week.
  - **OOS:** pass 68.7 %, median 40 days, breach 2.4 %, $82/month, 0.90 winning days per week.
- **The 5-winning-day payout rule is the bottleneck, not the edge.** Leto makes about 1 winning day (≥ $150) per week at any size we allowed.
  - Once funded, it takes a median **23–25 trading days (about 5 weeks)** to collect 5 winning days.
  - Add a median of about 41 days to pass the evaluation, and most 3-month paths never reach a payout. P(at least one payout within 3 months) is 20 % IS and 26 % OOS.
  - Not one of the 59 weeks in the data has 5 winning days. **Weekly payouts are out of reach** with the legs that survived verification.
- **The extended portfolio does not help.** It is MNQ 01–07 "time2" + MGC COMEX with the $75 cross rule (3.15 trades/week). On IS its PF is weaker (1.57 vs 1.84 at the chosen sizes). Under the < 10 % bust constraint the IS rule can only size it at 1 MNQ + 2 MGC, which gives $19/month IS and $6/month OOS.
- **Uncertainty is large.** Re-sampling the 31 IS weeks (outer bootstrap) puts the recommended size's 3-month bust probability anywhere from 1.7 % to 16 % (10th–90th percentile). In 25 % of those alternative histories it is ≥ 10 %.
  - With bars rebuilt at +1, +2 or +4 minutes, the OOS bust probability rises to 13–21 %.
  - With intraday drawdown measured on 1m MAE instead of closed trades, the IS bust probability is 11.0 %. That is over the limit, and with that rule the IS choice would drop to 3 MNQ + 1 MGC ($18/month IS, $28/month OOS).
- **FTMO-style rules (proxy only).** FTMO sells CFDs, not CME futures. Its static 10 % loss limit is almost never hit at these sizes (bust < 1 %), but the 10 % + 5 % targets take too long.
  - At 4 MNQ + 3 MGC (largest allowed size): pass 15 % IS / 9 % OOS within 3 months, $36 / $10 per month.
  - Once funded, the same size pays about $1,200/month with < 1 % bust. That number only matters if the evaluation is passed.

Code: `lab/prop_sim.py`. Outputs: `results/prop/prop_sim_select.json` (IS-only selection), `prop_sim.json` (OOS and robustness), `prop_sim_real.json` (real CME check).

## Inputs: which legs were allowed

Rule: use only legs whose verifier verdict is "trustworthy" with bar_shift_ok, plus the Leto baseline.

| Direction | Verdict / bar_shift_ok | What was usable |
|---|---|---|
| legs | trustworthy / **true** | Only Leto MNQ London passes its gate. The 7-leg pre-gate portfolio fails, so it is not used. |
| daily | trustworthy / false | bar_shift_ok is false **only** because of the baseline MGC Leto leg (OOS PF 1.01 at +4 min). The new leg **MNQ 01–07 time2** passes IS/OOS PF ≥ 1.15 at every offset 0..4, so it is used. |
| concepts | trustworthy / false | All new legs fail the gate, so none are used. |

There is no verified MCL leg, so **MCL = 0 contracts** throughout.

The two portfolios simulated:

1. **Leto**: MNQ 15m 02:00–05:00 (mf 0.3, chase 1.0) + MGC 15m 08:20–10:30 (mf 0.3, no chase). Max 1 trade per day each, independent.
2. **Extended ("ext")**: MNQ 15m 01:00–07:00 with "time2" (a 2nd trade only after a loss or a time-stop exit) + the same MGC leg. MGC is skipped for the day once MNQ's closed trades reach ≥ $75 per 2 MNQ (scaled with size).

**Execution is unchanged** (`lab.prop_daily.simulate` / `fvg_pro.generate`):
- signals decided at bar close; orders work from the next bar;
- ½ at 1R → BE → runner 3R, time stop 8 bars, flat 15:55.

New only for sizing:
- **1 contract:** a half-out is impossible, so the leg exits **all at 1R**.
- **3 contracts:** 2 out at 1R, 1 runner.
- Costs: data.py commissions and 1 tick slippage, plus the 2-tick, conservative-intrabar and 1m-replay variants.

**Checks (`trunc`):**
- At 2 + 2 contracts the code reproduces prop_daily exactly: Leto MNQ 70 trades PF 2.50, MGC 78 trades PF 1.70, MNQ 01–07 time2 121 trades PF 1.82, ext portfolio 186 trades PF 1.80, +$13,271.
- Truncation: trades built from 1m data cut at 2025-12-15, 2026-04-01 and 2026-07-20 match the full run for every trade closed before the cut. Tested at sizes 1+1, 3+3 and 4+2 for both portfolios, including the cross rule and the daily tables.

## Prop rules simulated (50K, start balance $50,000)

**Topstep-style evaluation**
- Target +$3,000.
- Trailing max loss $2,000 from the highest **end-of-day** balance, locked at $50,000. A breach is an intraday low at or below that level, and the account is lost.
- Daily loss limit $1,000: trading stops and the day is liquidated at −$1,000. This is not a fail.
- Consistency: the best day must be ≤ 50 % of total profit at the time of passing.
- At least 2 trading days.

**Topstep-style funded account**
- Same max loss and daily loss limit.
- Payout when there are **≥ 5 winning days (day net ≥ +$150)** since the last payout and the balance is above start.
- Payout = min(50 % of profit, $5,000). The trader keeps 90 %.
- After the first payout the max loss is fixed at the start balance.

**FTMO-style (rule proxy)**
- Phase 1 target 10 % ($5,000), phase 2 target 5 % ($2,500), each with ≥ 4 trading days.
- Static max loss 10 % (equity floor $45,000). Daily loss 5 % ($2,500) from the day's start = account lost.
- Funded: 80 % of profit paid every 10 trading days (about 14 calendar days).

**Simulation set-up**
- Horizon: 3 months = 63 trading days, **one attempt per path**. A bust ends the path; no resets or fees are modelled.
- Bootstrap: whole calendar weeks of the daily P&L, including 0-trade days, drawn with replacement. 5,000 paths with a fixed seed. IS and OOS are bootstrapped separately.
- "Replay": the real day sequence from each week start, for 63 days. There are 18 IS and 17 OOS start points. They overlap heavily, so they are not independent.
- Intraday low:
  - **closed** basis (pre-registered): cumulative closed-trade P&L in exit order;
  - **MAE** basis: the open trade's 1m max adverse excursion at full size, capped at the stop. It was added after the first OOS run, so it is reported, but **the pre-registered pick stays on the closed basis**.

## Selection rule (fixed before OOS; `select` uses IS only)

1. For each portfolio × firm, try every size MNQ 1..4 × MGC 1..3 (MCL 0).
2. A size is feasible if its IS-bootstrap P(max-loss breach within 3 months, evaluation or funded) is < 10 %.
3. Pick the feasible size with the highest IS expected trader payout per month; a tie goes to fewer contracts.
4. Recommended portfolio: the Topstep-style pick with the higher IS payout; within 5 %, Leto wins.

The IS rule's picks:

| Portfolio / firm | Size (MNQ / MGC / MCL) | IS payout/month | IS P(bust) |
|---|---|---|---|
| **Leto / Topstep** (recommended) | **4 / 1 / 0** | $51 | 7.2 % |
| Ext / Topstep | 1 / 2 / 0 | $19 | 9.8 % |
| Leto / FTMO | 4 / 3 / 0 (largest allowed) | $36 | 0.4 % |
| Ext / FTMO | 4 / 3 / 0 | $31 | 0.3 % |

Post-hoc picks on the MAE basis, not the recommendation: Leto/Topstep 3/1 (bust 3.5 %, $18), Ext/Topstep 3/1 (bust 9.4 %, $13), FTMO unchanged.

The Topstep IS grid shows the trade-off. Every size that pays more busts more:

| Leto, Topstep, IS | 2/2 | 3/2 | 4/1 | 4/2 | 4/3 |
|---|---|---|---|---|---|
| P(pass) | 47.8 % | 56.0 % | 44.8 % | 65.0 % | 70.7 % |
| P(bust, 3 months) | 14.7 % | 20.3 % | **7.2 %** | 25.6 % | 40.8 % |
| Payout/month | $65 | $106 | **$51** | $167 | $268 |

## Per leg (full year; IS PF / OOS PF; winning days use the stated contracts)

| Leg | Contracts | Trades (/wk) | WR | Exp R | PF | Net $ | Max DD | +months | IS / OOS PF | Win days/wk | Worst day | Trailing EOD DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Leto MNQ London | 2 | 70 (1.19) | 67.1 % | +0.256 | 2.50 | 5,626 | 583 | 12/14 | 2.05 / 3.06 | 0.44 | −502 | 583 |
| Leto MNQ London | 4 | 70 (1.19) | 67.1 % | +0.256 | 2.50 | 11,253 | 1,165 | 12/14 | 2.05 / 3.06 | 0.71 | −1,003 | 1,165 |
| Leto MGC COMEX | 1 (all at 1R) | 78 (1.32) | 61.5 % | +0.161 | 1.66 | 2,832 | 508 | 9/14 | 1.54 / 1.91 | 0.34 | −306 | 508 |
| Leto MGC COMEX | 2 | 78 (1.32) | 60.3 % | +0.183 | 1.70 | 5,999 | 1,030 | 8/14 | 1.66 / 1.77 | 0.61 | −611 | 1,030 |
| Leto MGC COMEX | 3 | 78 (1.32) | 61.5 % | +0.176 | 1.68 | 8,831 | 1,503 | 8/14 | 1.62 / 1.82 | 0.73 | −917 | 1,503 |
| MNQ 01–07 time2 | 1 (all at 1R) | 120 (2.03) | 60.0 % | +0.138 | 1.64 | 2,964 | 623 | 11/14 | **1.28** / 2.03 | 0.24 | −318 | 521 |
| MNQ 01–07 time2 | 2 | 121 (2.05) | 60.3 % | +0.189 | 1.82 | 7,590 | 1,257 | 12/14 | 1.52 / 2.14 | 0.66 | −636 | 1,054 |
| MNQ 01–07 time2 | 4 | 121 (2.05) | 60.3 % | +0.189 | 1.82 | 15,179 | 2,514 | 12/14 | 1.52 / 2.14 | 0.98 | −1,271 | 2,107 |

## Portfolios at the IS-chosen sizes

**Recommended: Leto 4 MNQ + 1 MGC, Topstep-style**

| | Trades (/wk) | WR | Exp R | PF | Net $ | Max DD | +months | Win days/wk | Worst day | Trailing EOD DD | Weeks with ≥ 5 win days |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Full | 148 (2.51) | 64.2 % | +0.206 | 2.19 | 14,085 | 1,322 | 13/14 | 0.95 | −1,003 | 1,322 | 0 / 59 |
| IS | 80 (2.58) | 61.3 % | +0.194 | 1.84 | 5,902 | 1,322 | 6/7 | 0.97 | −1,003 | 1,322 | 0 / 31 |
| OOS | 68 (2.34) | 67.6 % | +0.220 | 2.71 | 8,183 | 1,133 | 7/7 | 0.90 | −814 | 1,133 | 0 / 29 |

A single MNQ London stop at 4 contracts (worst day −$1,003) uses up the whole $1,000 daily loss limit.

**Prop results for the same size (3-month horizon, one attempt)**

| Leto 4/1, Topstep | P(pass) | Median days to pass | P(bust) (eval / funded) | P(≥ 1 payout) | Payout/month (trader 90 %) |
|---|---|---|---|---|---|
| IS bootstrap | 44.8 % | 41 | 7.2 % (3.4 / 3.8) | 20.0 % | **$51** |
| IS replay (n = 18) | 5.6 % | 57 | 0 % | 0 % | $0 |
| IS bootstrap, MAE basis | 44.7 % | 41 | **11.0 %** | 20.0 % | $50 |
| OOS bootstrap | 68.7 % | 40 | 2.4 % (0.9 / 1.5) | 26.4 % | **$82** |
| OOS replay (n = 17) | 82.4 % | 40 | 0 % | 35.3 % | $111 |
| OOS bootstrap, MAE basis | 68.7 % | 40 | 5.9 % | 26.4 % | $81 |
| Real CME, 2026-08-06..10-15 (50 days, one replay) | passed on day 40 | — | not lost | 0 payouts in the 10 days left | — |

Payout/month spread from the outer bootstrap of weeks (10th / 50th / 90th percentile): IS $8 / $44 / $164, OOS $13 / $73 / $214.

**Context only, not used for selection**
- **Already funded at the start (IS / OOS):**
  - $441 / $581 per month;
  - median **23 / 25 funded trading days to the first payout**;
  - 3-month P(bust) 35 % / 11 %. Payouts move the max loss to the start balance, so the cushion becomes thin.
- **6-month horizon (IS / OOS):** pass 81 % / 97 %, P(bust) 33 % / 14 %, $178 / $347 per month.

**Robustness (OOS bootstrap, Topstep, Leto 4/1)**

| Variant | IS PF | OOS PF | OOS P(pass) | OOS P(bust) | OOS payout/month |
|---|---|---|---|---|---|
| base | 1.84 | 2.71 | 68.7 % | 2.4 % | $82 |
| 2 ticks | 1.83 | 2.68 | 68.3 % | 2.3 % | $80 |
| conservative intrabar | 1.85 | 2.64 | 68.0 % | 3.1 % | $84 |
| conservative + 2 ticks | 1.83 | 2.61 | 67.1 % | 3.1 % | $82 |
| 1m replay | 1.84 | 2.71 | 68.7 % | 2.4 % | $82 |
| bar offset +1 min | 2.03 | 1.70 | 50.6 % | **20.7 %** | $41 |
| bar offset +2 min | 1.78 | 2.39 | 68.7 % | **12.7 %** | $89 |
| bar offset +3 min | 1.69 | 2.79 | 65.2 % | 1.8 % | $76 |
| bar offset +4 min | 1.78 | 1.85 | 43.7 % | **12.8 %** | $49 |
| expectancy halved (IS mean/2 subtracted per trade) | 1.36 | 1.96 | 42.3 % | 5.7 % | $27 |

The IS version of the halved-expectancy stress gives 23.6 % pass, 14.5 % bust and $15/month.

**Extended portfolio at its IS pick (1 MNQ + 2 MGC, Topstep)**
- Full year: 186 trades (3.15/wk), 60.8 % WR, PF 1.77, +$9,160, 0.75 winning days/week, worst day −$741, trailing DD $1,240.
- IS: PF 1.57; pass 33.1 %, bust 9.8 % (12.5 % on the MAE basis), $19/month.
- OOS: PF 2.15; pass 22.3 %, bust 0.1 %, $6/month.
- Outer bootstrap of IS weeks: bust 2.6–28.7 %; 52 % of alternative histories are ≥ 10 %.
- Real CME, 50 days: PF 1.06, did not pass.
- Hindsight OOS-best size, 3 MNQ + 1 MGC: $129/month at 7.7 % bust. The IS rule could not have chosen it: its IS bust is 6.2 % with only $14/month.

**FTMO-style, 4 MNQ + 3 MGC (both portfolios)**
- Leto: pass 15.3 % IS / 9.1 % OOS (median about 51–56 days), bust ≤ 0.5 %, $36 / $10 per month. Replays: 0 of 35 passed within 3 months.
- Ext: pass 15.5 % / 31.6 %, $31 / $72 per month.
- Under these rules the limit is how far the maximum size reaches, not risk. Bigger sizes than the allowed MNQ ≤ 4 / MGC ≤ 3 would be needed to reach 10 % + 5 % in a reasonable time, and that is outside the brief.

## Honest assessment and uncertainty

1. **The data are short.** There are 31 IS weeks and 29 OOS weeks. A bust probability near 10 % cannot be estimated better than about ±5–8 points from this; see the outer-bootstrap ranges. The < 10 % constraint is met by the point estimate, not with confidence.
2. **IS looks worse than OOS for Leto** (PF 1.84 vs 2.71). The OOS numbers are probably the optimistic ones; base expectations on IS.
   - The IS replays started in Sep–Dec 2025 almost never passed (1 of 18).
   - With expectancy halved, the payout falls to $15–27/month.
3. **Results depend on the bar boundary.** Shifting bars by 1–4 minutes moves the recommended size's OOS bust from 1.8 % to 20.7 %. That says the 10 % bust budget should be read as roughly "10–20 %".
4. **Not modelled:**
   - evaluation and activation fees, resets, and payout minimums;
   - exact current firm rules: Topstep and FTMO change them often, so check the live rulebooks;
   - the 1m proxy vs real CME fills. Real CME over 50 days: Leto PF 2.69 at 4/1, versus PF 4.35 on the proxy for the same days.
5. **Fees decide the economics.** With an expected trader payout of about $50–80 per month in the first 3 months, any monthly evaluation subscription of similar size wipes out the expectation. The value is in the funded phase, where Leto earns about $440–580 per month, and in surviving to it.
6. **Verdict on the user's goal**
   - **Not met:** about 7 trades/week and frequent winning days for weekly payouts. The verified legs give 2.5 trades/week and about 1 winning day per week, and no week in the data reaches 5 winning days.
   - **Possible:** a Topstep-style account with Leto at 4 MNQ + 1 MGC passes about half the time and then pays roughly every 5–6 weeks.
   - Faster payouts need more independent, verified setups. Bigger size only trades payout for bust probability; see the IS grid.

Reproduce from `futures-strategy-lab`, each with `PYTHONPATH=.`:
- `python -m lab.prop_sim trunc`
- `python -m lab.prop_sim select` (about 10 s)
- `python -m lab.prop_sim final` (about 2 min)
- `python -m lab.prop_sim real`

Nothing was committed and no existing files were edited.
