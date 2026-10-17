# Prop direction "concepts": new non-FVG intraday concepts as extra legs next to Leto. Result: FAIL

**Bottom line.** No new concept passes the protocol. 1,476 configs were tested in 10 concept families on MNQ, MGC and MCL, at 15m and 5m, with 2 exits.

- **IS gate:** only 13 configs are IS-eligible: 8 MGC London-range retests, 4 MGC first-bar pullbacks and 1 MNQ EMA20 pullback.
- **Picks:** the three per-concept picks under the pre-registered IS rule all fail the bar-shift OOS gate (IS and OOS PF ≥ 1.15 at every offset).
- **Closest result:** Leto + MGC London-range retest + MNQ EMA20 pullback. It reaches the frequency target on paper:
  - 7.9 trades/week, 59.0 % WR, PF 1.56;
  - 1.94 winning days/week, against 0.98 for Leto alone.
- **Why the closest result fails:**
  - At bar offset 1 its OOS PF is 0.98.
  - The MGC leg's OOS PF is 0.90 on the standard bars.
  - On 50 days of real CME data both new legs lose (PF 0.99 and 0.76).

Code: `lab/prop_concepts.py`. JSON: `results/prop/concepts_grid.json`, `concepts_grid2.json`, `concepts.json`, `concepts_real.json`, `concepts_extra.json`.

Data: Dukascopy 1m proxies (NQ, XAU, WTI), 2025-09-01..2026-10-14. That is 291 Globex days (IS 151 / OOS 140), or about 59 weeks. IS = entry < 2026-04-01.

Costs and sizing:
- Commissions as in data.py, 2 contracts per leg.
- Stop, BE, time and EOD exits pay 1 tick.
- Market entries pay 1 more tick per contract.
- Win = position net $ > 0. Winning day = Globex-day net ≥ +$150 at 2 contracts per leg.

## Concepts implemented (all decided at bar close, order from the next bar, max 1 trade/leg/day)

Session opens: MNQ 09:30, MGC 08:20, MCL 09:00 NY.

| Family | Signal | Entry / stop | Grid |
|---|---|---|---|
| rbrk: OR / IB / Asia / London range break | first *fresh* close beyond the range: or15, or30 or ib60 after the open; Asia 20-24 range from 02:00; London 02-05 range from the session open; window 60/120/180 min | market, or retest limit at the level (90 min, cancelled on a close beyond the range mid); stop at range mid, 1 ATR, or signal-bar extreme | 360 |
| va80: 80 % rule | opens outside the prior RTH value area, then 1-2 closes back inside within 120/240 min → trade toward the other VA edge | market; stop at session extreme or 1 ATR | 48 |
| vwr: VWAP band reversion on balanced days | previous close outside VWAP ± 1.5/2 sd, this close back inside; ≥ 60 min after the open; session range ≤ 0.7 / 1.0 / ∞ × daily ATR | market; stop at 3-bar extreme | 36 |
| gap: fade / go | open-vs-prior-close gap of 0.1-0.2 … 0.6-1.0 × daily ATR; fade if still open after the first bar, go if the first bar closes with the gap | market; stop at first-bar extreme or 1 ATR | 96 |
| fbm: large first bar | first session bar with body ≥ 0.5 / 0.8 / 1.2 ATR, close in its outer 30 % | market, or limit at the bar's 50 %; stop at the far end or 1 ATR | 72 |
| imom: intraday momentum | open→+30 min move ≥ 0.15 / 0.25 daily ATR → enter 14:30 / 15:00 in that direction | stop 0.15 / 0.25 daily ATR, hold to 15:55 | 48 (hold exit) |
| ema_pb (stage 2) | EMA20/50 trend, the bar tags EMA20 and closes back with a trend body; am window (open+15..+165 min) or pm window (12:30-15:00) | market; stop at bar extreme | 24 |
| vwap_pb (stage 2) | 30/60/120 min of closes on one side of VWAP, the bar tags VWAP and closes back | market; stop at bar extreme | 36 |
| box (stage 2) | 4 or 6 bars inside ≤ 1.5 / 2.5 ATR, then a close beyond the box | market; stop at box mid or box far side | 96 |
| oncont (stage 2) | Globex open → session open move ≥ 0.25 / 0.5 daily ATR, and the first bar closes the same way | market; stop at first-bar extreme or 1 ATR | 48 |

- **Exits (chosen on IS, per config):** either `p13` (half at 1R → BE → runner 3R) or `f1` (all at 1R). Both use a 120-min time stop and go flat at 15:55 or the new Globex day.
- **Daily ATR:** the mean session range of the 14 *prior* sessions.
- **Look-ahead check:** truncation checks pass. Setups built on df[:k] equal the full-data setups for bars < k−1, at offsets 0 and 2.
  - 984 comparisons over the stage-1 families and 624 over stage 2.
  - Run with `python -m lab.prop_concepts trunc`.

Stage 2 was added after stage 1 failed. It used new families only, and its rule was written into the docstring before it was run. It used the same IS rule and the same gate.

## Selection rule (pre-registered in the code docstring; IS only)

**IS-eligible.** A config must have all of these:
- ≥ 30 IS trades at offset 0;
- IS expectancy > 0;
- IS WR ≥ 55 % at offset 0, and a mean over the offsets ≥ 55 %;
- IS PF ≥ 1.15 at **every** offset (0..4 for 15m, 0..2 for 5m);
- median IS PF ≥ 1.30.

**Score.** (min IS PF − 1) × √(IS trades). Each (concept, market) is represented by its best-scoring config.

**Protocol gate.** IS PF ≥ 1.15 and OOS PF ≥ 1.15 at every offset.

**Combination.** Up to 3 gated legs in score order, with no same-market overlap of signal windows.

## Result of the IS stage
- 13 of 1,476 configs are IS-eligible:
  - rbrk: 8, all of them MGC 5m "London range → retest in the COMEX window, stop at range mid";
  - fbm: 4, all MGC 15m;
  - ema_pb: 1, MNQ 15m am.
- No va80, vwr, gap, imom, vwap_pb, box or oncont config is IS-eligible in any market. They fall short in one of three ways:
  - WR under 55 %: imom is about 50 %, gap fades 37-57 %;
  - IS PF under 1.15 at some offset;
  - too few trades: va80 makes 14-44 IS trades.
- No MCL config of any family is eligible.

## Gate (IS PF / OOS PF at each bar offset; trades IS/OOS)

| Pick (IS score) | off 0 | off 1 | off 2 | off 3 | off 4 | gate |
|---|---|---|---|---|---|---|
| MGC 5m London-range retest, W 120, stop mid, p13 (5.99) | 70/57 · 1.93/**0.90** | 76/60 · 1.86/**1.11** | 76/64 · 1.72/1.31 | – | – | **fail** |
| MNQ 15m EMA20 pullback am, f1 (2.86) | 94/90 · 1.54/1.40 | 93/90 · 1.33/**0.72** | 90/88 · 1.32/**1.10** | 88/88 · 1.30/1.15 | 90/85 · 1.53/1.60 | **fail** |
| MGC 15m first-bar 50 % pullback, b 0.5, p13 (2.58) | 45/46 · 1.38/**0.58** | 49/42 · 2.15/**0.42** | 47/42 · 2.17/**0.53** | 57/40 · 1.52/**0.40** | 48/40 · 1.41/**0.64** | **fail** |

OOS WR by offset:
- MGC range retest: 51 / 60 / 63 %.
- MNQ EMA pullback: 57 / 39 / 49 / 52 / 58 %.
- MGC first bar: 48 / 38 / 38 / 33 / 45 %.

## Per leg (standard bars, 1 tick, 2 contracts)

| Leg | Trades (/wk) | WR | Exp R | PF | Net $ | Max DD | +months /14 | IS n / WR / PF | OOS n / WR / PF | Win days/wk | Worst day | Trail EOD DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Leto MNQ London | 70 (1.20) | 67.1 % | +0.256 | 2.50 | 5,626 | 583 | 12 | 35 / 65.7 % / 2.05 | 35 / 68.6 % / 3.06 | 0.45 | −502 | 583 |
| Leto MGC COMEX | 78 (1.34) | 60.3 % | +0.183 | 1.70 | 5,999 | 1,030 | 8 | 45 / 57.8 % / 1.66 | 33 / 63.6 % / 1.77 | 0.62 | −611 | 1,030 |
| MGC London-range retest (5m) | 127 (2.18) | 57.5 % | +0.112 | 1.38 | 5,009 | 2,282 | 9 | 70 / 62.9 % / 1.93 | 57 / 50.9 % / **0.90** | 0.72 | −545 | 2,282 |
| MNQ EMA20 pullback am (15m) | 184 (3.16) | 56.5 % | +0.141 | 1.46 | 10,297 | 2,364 | 11 | 94 / 56.4 % / 1.54 | 90 / 56.7 % / 1.40 | 1.44 | −816 | 2,364 |

Robustness of the two new legs (IS / OOS PF):

| Leg | 2 ticks | conservative | conservative + 2 ticks | 1m replay |
|---|---|---|---|---|
| MGC range retest | 1.91 / 0.89 | 1.89 / 0.90 | 1.87 / 0.89 | 1.93 / 0.90 |
| MNQ EMA pullback | 1.52 / 1.39 | 1.50 / 1.40 | 1.48 / 1.39 | 1.47 / 1.41 |

The fill model and the slippage are not the problem. The bar boundaries are.

## Portfolio: Leto + closest legs (each leg independent, max 1/day; 24 same-market overlapping positions)

| Variant | Trades/wk | WR | Exp R | PF | Net $ | Max DD | +months | IS WR / PF | OOS WR / PF | Win days/wk (IS / OOS) | Worst day | Trail EOD DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Leto only | 2.54 | 63.5 % | +0.217 | 1.94 | 11,625 | 1,382 | 12 | 61.3 % / 1.76 | 66.2 % / 2.25 | 0.98 (1.06 / 0.89) | −870 | 1,382 |
| Leto + 2 closest, base | **7.89** | 59.0 % | +0.158 | 1.56 | 26,931 | 3,092 | 12 | 59.8 % / 1.71 | 58.1 % / 1.41 | **1.94** (2.02 / 1.86) | −952 | 2,960 |
| 2 ticks | 7.89 | 59.0 % | +0.152 | 1.55 | 26,306 | 3,132 | 12 | 59.8 % / 1.70 | 58.1 % / 1.40 | 1.92 | −955 | 3,001 |
| conservative | 7.89 | 59.5 % | +0.153 | 1.55 | 26,371 | 2,932 | 12 | 60.2 % / 1.69 | 58.6 % / 1.41 | 1.91 | −1,252 | 2,629 |
| cons + 2 ticks | 7.89 | 59.5 % | +0.148 | 1.53 | 25,747 | 2,971 | 12 | 60.2 % / 1.67 | 58.6 % / 1.39 | 1.89 | −1,257 | 2,669 |
| 1m replay | 7.89 | 59.0 % | +0.151 | 1.55 | 26,500 | 3,092 | 12 | 59.8 % / 1.68 | 58.1 % / 1.42 | 1.94 | −985 | 2,960 |
| offset 1 | 7.77 | 55.5 % | +0.099 | 1.27 | 14,325 | 5,765 | 10 | 59.3 % / 1.63 | 51.6 % / **0.98** | 1.75 | −966 | **5,765** |
| offset 2 | 7.53 | 58.2 % | +0.119 | 1.48 | 22,124 | 2,964 | 11 | 58.6 % / 1.57 | 57.9 % / 1.39 | 1.91 | −1,116 | 2,654 |
| offset 3 | 7.61 | 59.6 % | +0.139 | 1.48 | 21,613 | 2,650 | 11 | 60.1 % / 1.58 | 59.1 % / 1.39 | 1.86 | −1,187 | 2,650 |
| offset 4 | 7.58 | 60.1 % | +0.160 | 1.56 | 25,579 | 2,623 | 12 | 60.6 % / 1.66 | 59.5 % / 1.47 | 1.98 | −1,043 | 2,527 |

The 5m MGC leg uses offset 2 where 3 and 4 are shown.

Payout weeks (≥ $150 days, out of 59 weeks):

| | Weeks with ≥ 3 winning days | Weeks with ≥ 5 winning days |
|---|---|---|
| Leto | 3 | 0 |
| Leto + 2 closest | 20 | 1 |

**Real CME futures, 2026-08-06..10-15 (50 days, MNQ + MGC):**

| | Real data | Proxy, same window |
|---|---|---|
| Leto | 25 tr, 60.0 %, PF 1.91, +$1,588 | 24 tr, 66.7 %, PF 2.48 |
| MGC range retest | 26 tr, 53.8 %, PF 0.99 | 23 tr, 43.5 %, PF 0.54 |
| MNQ EMA pullback | 35 tr, 40.0 %, PF 0.76, −$1,312 | 34 tr, 50.0 %, PF 1.32 |
| Leto + both | 86 tr, 50.0 %, PF 1.02, +$239; 1.80 winning days/wk | 81 tr, 53.1 %, PF 1.20; 2.00 winning days/wk |

## Post-hoc note (NOT a selection, the rule did not pick it)

Of the 13 IS-eligible configs, exactly one passes the gate: **MGC 5m London-range retest, W 180, stop at range mid, all at 1R**. It is a neighbour of the MGC pick.
- **Shifts.** IS / OOS PF is 1.68/1.26, 1.52/1.40 and 1.51/1.69 at offsets 0/1/2.
- **Year.** 139 trades (2.4/wk), 59.0 % WR, PF 1.47, OOS PF 1.26, 1.22 winning days/wk.
- **With Leto.** 4.9 trades/wk (0.99/day), 61.3 % WR, PF 1.69, OOS 60.3 % / PF 1.64, 1.67 winning days/wk, trailing EOD DD $2,115.

The whole MGC London-range-retest family is the only one with a consistent IS edge: OOS PF is 0.90-1.69 across its 8 eligible variants and their offsets. It is still a selection made after seeing the OOS, and its real-data PF is about 1.0, so it is not accepted.

## Verdict
**Nothing passes.** None of the suggested concepts adds a bar-shift-robust 0.3-0.6 trades/day at ≥ 55 % WR on MNQ, MGC or MCL: ORB/IB, Asia or London breaks, VWAP-band reversion, the 80 % VA rule, gap fade/go, first-bar momentum, imom, EMA or VWAP pullbacks, box breakouts and overnight continuation were all tried.

The closest combination hits 7.9 trades/week and about 2 winning days/week on the standard bars. It drops to OOS PF 0.98 when the bars move by 1 minute, and loses on real CME data. For a funded account, Leto alone (2.5 trades/wk, about 1 winning day/wk) is still the only verified edge. Using these legs would mean accepting a breakeven-to-small edge in exchange for frequency.

## Reproduce
```
cd futures-strategy-lab
PYTHONPATH=. python -m lab.prop_concepts trunc      # look-ahead check (all families); "trunc 2" = stage 2 only
PYTHONPATH=. python -m lab.prop_concepts grid       # stage 1 grid x offsets (4 cores, ~10 min)
PYTHONPATH=. python -m lab.prop_concepts grid2      # stage 2 grid
PYTHONPATH=. python -m lab.prop_concepts final      # IS selection, gate, portfolios, robustness
PYTHONPATH=. python -m lab.prop_concepts real       # real CME futures sanity check
PYTHONPATH=. python -m lab.prop_concepts extra      # leg robustness, payout weeks, post-hoc info
```
