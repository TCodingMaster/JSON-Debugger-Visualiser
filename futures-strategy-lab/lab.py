#!/usr/bin/env python3
"""Futures Strategy Lab — command line.

  python lab.py backtest --source yf                    # free Yahoo data (5m, last ~60 days)
  python lab.py backtest --source yf --interval 1h --period 730d
  python lab.py backtest --csv MNQ=mnq_5m.csv --csv MGC=mgc_5m.csv
  python lab.py backtest --source synthetic             # demo only, numbers mean nothing
  python lab.py sweep --csv MNQ=mnq_5m.csv              # parameter grid for lsrb_fvg with OOS check
  python lab.py components --source yf                  # sweep / rejection / FVG tested alone and combined
  python lab.py concepts                                # list the concept database
  python lab.py discover --api-key KEY                  # find new candidates on YouTube

Then open mock.html in a browser.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys

from lab import data, engine, metrics, report, strategies


def _parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def _datasets(args) -> tuple[dict, str, str]:
    if args.csv:
        ds = {}
        for spec in args.csv:
            sym, _, path = spec.partition("=")
            if not path:
                raise SystemExit("--csv expects SYMBOL=path, e.g. --csv MNQ=mnq_5m.csv")
            ds[data.get_instrument(sym).symbol] = data.load_csv(path, tz=args.tz)
        return ds, "real", "CSV: " + ", ".join(args.csv)
    if args.source == "yf":
        tickers = {"MNQ": "MNQ=F", "MGC": "MGC=F"}
        ds = {s: data.load_yfinance(tickers[s], args.interval, args.period) for s in args.symbols}
        return ds, "real", f"Yahoo Finance {args.interval} bars, period {args.period} (front-month continuous, unadjusted)"
    ds = {s: data.synthetic(s, days=args.days, seed=args.seed) for s in args.symbols}
    return ds, "synthetic", (f"Synthetic random-walk bars ({args.days} sessions) with injected stop-runs. "
                             "For checking the pipeline only — these numbers are not evidence.")


def _cfg(args) -> engine.EngineConfig:
    return engine.EngineConfig(flatten=args.flatten, max_trades_per_day=args.max_trades,
                               slippage_ticks=args.slippage, be_at_r=args.be)


def cmd_backtest(args):
    ds, mode, note = _datasets(args)
    sids = list(strategies.REGISTRY) if args.strategies == ["all"] else args.strategies
    res = report.run_all(ds, sids, _cfg(args), _parse_params(args.param))
    path = report.export(res, mode, note)
    print("\n" + (path.parent / "results" / "summary.md").read_text())
    print(f"wrote {path} — open mock.html to explore")


def cmd_sweep(args):
    """Small grid over the core playbook's knobs. Picks on in-sample, reports
    out-of-sample, so you can see how much of the edge survives."""
    ds, mode, _ = _datasets(args)
    grid = {"wick_ratio": [0.3, 0.4, 0.5], "fvg_window": [5, 10, 15], "entry": ["ce", "proximal"],
            "min_fvg_atr": [0.05, 0.1, 0.2]}
    keys = list(grid)
    for sym, df in ds.items():
        inst = data.get_instrument(sym)
        from lab import features
        feat = features.build(df, inst.tick)
        rows = []
        for combo in itertools.product(*grid.values()):
            ov = dict(zip(keys, combo))
            trades = engine.run(feat, strategies.generate("lsrb_fvg", feat, inst, ov), inst, _cfg(args))
            m = metrics.summarize(trades, mc_runs=200)
            if m["trades"] >= 10:
                rows.append((m["is"]["expectancy_r"], ov, m))
        rows.sort(key=lambda r: -r[0])
        print(f"\n[{sym}] {mode} data — top 10 by IN-SAMPLE expectancy (judge them by the OOS columns)")
        print(f"{'params':60s} {'n':>4s} {'IS WR':>6s} {'IS exp':>7s} {'OOS n':>5s} {'OOS WR':>6s} {'OOS exp':>7s}")
        for _, ov, m in rows[:10]:
            print(f"{json.dumps(ov):60s} {m['trades']:4d} {m['is']['win_rate']:6.1%} {m['is']['expectancy_r']:+7.3f} "
                  f"{m['oos']['trades']:5d} {m['oos']['win_rate']:6.1%} {m['oos']['expectancy_r']:+7.3f}")


def cmd_components(args):
    """Sweep / rejection block / FVG tested alone and in every combination."""
    from datetime import datetime, timezone
    from lab import components

    ds = {}
    if args.csv:
        for spec in args.csv:
            sym, _, path = spec.partition("=")
            df = data.load_csv(path, tz=args.tz)
            mins = int(round(df.index.to_series().diff().median().total_seconds() / 60))
            ds[(data.get_instrument(sym).symbol, f"{mins}m")] = df
        mode, note = "real", "CSV: " + ", ".join(args.csv)
    elif args.source == "yf":
        for sym in args.symbols:
            for tf in args.timeframes:
                ds[(sym, tf)] = data.load_yfinance({"MNQ": "MNQ=F", "MGC": "MGC=F"}[sym], tf, args.period)
        mode = "real"
        note = f"Yahoo Finance {', '.join(args.timeframes)} bars, last {args.period} (front-month continuous)."
    else:
        for sym in args.symbols:
            ds[(sym, "5m")] = data.synthetic(sym, days=args.days, seed=args.seed)
        mode, note = "synthetic", "Synthetic demo data: these numbers are not evidence."
    for (sym, tf), df in ds.items():
        print(f"[{sym} {tf}] {len(df):,} bars {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}")
    if args.study == "ob":
        combos, windows = components.OB_COMBOS, components.OB_WINDOWS
        params = {"asia_levels": True}
        title = "Liquidity sweep + order block + FVG respected (NY 10:00-13:00, Asia 20:00-04:00 ET)"
        js_name, var, md_name = "lab-ob.js", "LAB_OB", "sweep_ob_fvg.md"
    else:
        combos, windows, params = components.COMBOS, components.WINDOWS, None
        title = "Concepts only: sweep (S), rejection block (R), FVG respected (F)"
        js_name, var, md_name = "lab-concepts.js", "LAB_COMPONENTS", "concepts_only.md"
    rows = components.run_study(ds, _cfg(args), windows=windows, combos=combos, params=params)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_mode": mode,
               "data_note": note, "title": title, "combos": combos, "windows": windows,
               "rows": rows, "pooled": components.pooled(rows, combos)}
    out = report.ROOT / js_name
    out.write_text(f"// generated by `python lab.py components --study {args.study}` — do not edit\nwindow.{var} = "
                   + json.dumps(payload, allow_nan=False) + ";\n")
    md = report.ROOT / "results" / md_name
    md.parent.mkdir(exist_ok=True)
    md.write_text(components.markdown(rows, note, combos, title))
    print(f"\nwrote {out} and {md}")


def cmd_concepts(args):
    for c in report.load_concepts():
        print(f"{c['id']:16s} {c['name']}\n{'':16s} source: {c['source']['trader']}  "
              f"(credibility {c['source']['credibility_score']}/10, playbook fit {c['playbook_fit']}/10)")


def cmd_discover(args):
    from lab import discover
    out = discover.discover(args.api_key, per_query=args.per_query)
    print(f"wrote {out} — review candidates, then add vetted ones to data/concepts.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def data_args(p):
        p.add_argument("--source", choices=["yf", "synthetic"], default="synthetic")
        p.add_argument("--csv", action="append", help="SYMBOL=path (repeatable); overrides --source")
        p.add_argument("--tz", default=None, help="timezone of naive CSV timestamps (default America/New_York)")
        p.add_argument("--symbols", nargs="+", default=["MNQ", "MGC"])
        p.add_argument("--interval", default="5m")
        p.add_argument("--period", default="60d")
        p.add_argument("--days", type=int, default=250, help="synthetic sessions")
        p.add_argument("--seed", type=int, default=7)
        p.add_argument("--flatten", default="15:55")
        p.add_argument("--max-trades", type=int, default=2)
        p.add_argument("--slippage", type=int, default=1, help="ticks on stop/market fills")
        p.add_argument("--be", type=float, default=0.0, help="move stop to entry at this R (0 = off)")

    p = sub.add_parser("backtest", help="run every concept on every symbol and export for mock.html")
    data_args(p)
    p.add_argument("--strategies", nargs="+", default=["all"], choices=["all", *strategies.REGISTRY])
    p.add_argument("--param", action="append", help="override a strategy parameter, e.g. wick_ratio=0.5")
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser("sweep", help="parameter grid for lsrb_fvg with in/out-of-sample split")
    data_args(p)
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("components", help="test sweep / rejection block / FVG alone and combined")
    data_args(p)
    p.add_argument("--timeframes", nargs="+", default=["2m", "5m", "15m"])
    p.add_argument("--study", choices=["srf", "ob"], default="srf",
                   help="srf: sweep/rejection/FVG; ob: sweep + order block + FVG in NY 10-13 and Asia 20-04")
    p.set_defaults(fn=cmd_components)

    p = sub.add_parser("concepts", help="list the concept database")
    p.set_defaults(fn=cmd_concepts)

    p = sub.add_parser("discover", help="search YouTube for new concepts (needs a free API key)")
    p.add_argument("--api-key")
    p.add_argument("--per-query", type=int, default=15)
    p.set_defaults(fn=cmd_discover)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
