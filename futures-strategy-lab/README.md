# Futures Strategy Lab

Finds strategy concepts from credible (non-guru) futures traders, turns each into
objective rules, **backtests them automatically on MNQ and MGC**, and ranks them
with an Easy Score in `mock.html`.

Your plan is built in:

| Rule | Value |
|---|---|
| Planned reward:risk | fixed **2:1** on every trade (stop = 1R, target = 2R) |
| Size | **2 MNQ** ($4 per point) or **1 MGC** ($10 per point) |
| Goals | win rate ≥ **60 %**, average realized RR ≥ **1.5** |
| Core playbook | liquidity sweep → rejection block → FVG respected |

At a fixed 2R target the breakeven win rate is 33.3 %. A 60 % win rate at 2R is
+0.8R per trade, which is very rare. The lab shows how far each concept is from it.

## Quick start

```bash
cd futures-strategy-lab
pip install -r requirements.txt
python lab.py backtest --source yf     # free Yahoo data: 5-minute bars, last ~60 days
open mock.html                          # or double-click it
```

Longer history (better statistics):

```bash
python lab.py backtest --source yf --interval 1h --period 730d           # 2 years of 1h bars
python lab.py backtest --csv MNQ=mnq_5m.csv --csv MGC=mgc_5m.csv          # your own data
```

CSV formats detected automatically: TradingView "Export chart data", NinjaTrader 8
exports (`yyyyMMdd HHmmss;o;h;l;c;v`) and any `datetime,open,high,low,close,volume`
file. Naive timestamps are assumed to be New York time (`--tz` to change).

`python lab.py backtest --source synthetic` runs on random-walk demo data. It only
checks the pipeline: those numbers say nothing about any strategy, and the
dashboard shows a warning banner for them.

## Commands

| Command | What it does |
|---|---|
| `backtest` | Runs every concept × symbol, writes `lab-data.js` (for mock.html), `results/summary.md` and one trade-list CSV per run |
| `sweep` | Grid search for the core playbook's settings; picks on in-sample, reports **out-of-sample** so you can see what survives |
| `concepts` | Lists the concept database |
| `discover` | Searches YouTube (free Data API key) for new concepts and filters out gurus; writes `data/discovered.json` for review |

Useful flags: `--be 1` (move stop to break-even at 1R), `--slippage 2`,
`--max-trades 1`, `--strategies lsrb_fvg turtle_soup`, `--param wick_ratio=0.5`.

## The concepts

| id | Concept | Source |
|---|---|---|
| `lsrb_fvg` | Liquidity sweep + rejection block + FVG (your playbook) | ICT vocabulary, mechanized |
| `turtle_soup` | False break of a 20-bar extreme | Linda Raschke (*Street Smarts*, 1995) |
| `oops_reclaim` | Open outside yesterday's range, reclaim | Larry Williams (1987 Robbins World Cup) |
| `orb_failure` | Failed opening-range breakout | Al Brooks / Toby Crabel |
| `session_sweep` | Asia/London/overnight high-low sweep at NY open | Fabio Valentini-style session liquidity |
| `irb_trend` | Inventory Retracement Bar | Rob Hoffman |
| `va_rejection` | Value-area re-entry ("80 % rule") | Jim Dalton / Market Profile |
| `vwap_band_sweep` | Sweep beyond the ±2σ VWAP band, reclaim | Prop-desk VWAP concepts (loose attribution) |
| `brooks_h2l2` | Second-entry pullback in a trend | Al Brooks |

Each entry in `data/concepts.json` lists the credibility evidence and the guru
red flags. Credentials that couldn't be confirmed from a primary source say
"unverified". The coded rules are this lab's reading of each concept, not the
trader's exact method.

## Easy Score (0–100, A–F)

Weighted average of five components; you can change the weights live in mock.html.

* **Backtest (40)**: win rate vs 60 %, expectancy (R per trade), profit factor and drawdown, scaled down when there are fewer than 100 trades.
* **Playbook fit (20)**: overlap with sweep / rejection block / FVG.
* **Credibility (15)**: the source's track record minus red flags.
* **Ease (15)**: how mechanical and simple the rules are.
* **Robustness (10)**: out-of-sample expectancy, in-sample vs out-of-sample win-rate stability, and results on both instruments.

Fewer than 10 trades → the score is *provisional* (qualitative components only).

## How the backtester avoids lying to you

* Every level (prior-day high/low, overnight, Asia, London, opening range, swing pivots, value area) is used only after it has fully formed. A test checks that cutting off future data never changes past signals.
* Signals are decided on a bar's close; orders work from the next bar.
* Stop and target inside the same bar → the stop is assumed hit first.
* On the bar an order fills, events follow the open → nearer extreme → farther extreme → close path model. A pending order is cancelled if price reaches its stop before the entry.
* Costs: commission per contract per side ($0.62 MNQ, $0.82 MGC; adjust in `lab/data.py`), plus 1 tick of slippage on stop/market fills and stop-outs.
* The engine is tested against ground truth: random entries with a 2R target on a random walk win ~33 %, as they should.
* Every result includes in-sample/out-of-sample (70/30) splits and a 2,000-run Monte Carlo drawdown distribution.

## TradingView Bar Replay journal

mock.html has a journal for trades you replay by hand in TradingView. It computes
R and $ from your sizing, tracks how often your checklist was followed (sweep /
rejection block / FVG), and compares you to the goals. It saves in your browser
and can export or import CSV. Use it to check that you read the rules the same
way the code does.

## Tests

```bash
pip install pytest && python -m pytest -q tests
```

*All results are hypothetical and for education only. Not financial advice.*
