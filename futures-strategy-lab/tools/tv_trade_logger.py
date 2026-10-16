"""Forward-test trade logger: TradingView Desktop -> TradingView MCP -> CSV.

Uses the community TradingView MCP server (github.com/tradesdontlie/tradingview-mcp), which reads
TradingView Desktop through the Chrome DevTools Protocol. Every few minutes the logger asks the
server for the Strategy Tester's trade list, appends trades it has not seen before to a CSV and
prints a running summary (positions, win rate, profit factor, net $) next to the backtest numbers.

Run it on YOUR computer (TradingView Desktop must run there):

    git clone https://github.com/tradesdontlie/tradingview-mcp.git
    cd tradingview-mcp && npm install
    # start TradingView Desktop with remote debugging (see that repo: scripts/launch_tv_debug_*)
    pip install mcp
    python tv_trade_logger.py --server /path/to/tradingview-mcp/src/server.js --since 2026-10-19

Open the chart with the FVG Pro L strategy (e.g. MNQ1! 15m) and leave it open. The Strategy
Tester only shows the strategy of the active chart, so log MNQ and MGC in two TradingView windows
(or run one logger per chart while it is active).

Options: --interval seconds between polls (default 300), --out CSV path, --list-tools to print
the server's tools (tool names are discovered automatically: the first tool whose name contains
"trade"; override with --trades-tool / --results-tool).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKTEST = "backtest (1 yr): MNQ London WR ~60-67 %, PF ~2.2 | MGC COMEX WR ~62-64 %, PF ~1.7-1.9"


def _payload(result) -> object:
    """MCP tool result -> Python object (JSON text content if possible)."""
    texts = [c.text for c in getattr(result, "content", []) if getattr(c, "type", "") == "text"]
    raw = "\n".join(texts)
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001 - some servers return text; keep it
        m = re.search(r"(\[.*\]|\{.*\})", raw, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:  # noqa: BLE001
                pass
        return raw


def _trade_list(obj) -> list[dict]:
    """Find the list of trade dicts anywhere in the payload."""
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        return obj
    if isinstance(obj, dict):
        for k in ("trades", "data", "items", "list", "result", "closedTrades"):
            if k in obj:
                found = _trade_list(obj[k])
                if found:
                    return found
        for v in obj.values():
            found = _trade_list(v)
            if found:
                return found
    return []


def _get(d: dict, *names):
    low = {k.lower().replace("_", "").replace(" ", ""): v for k, v in d.items()}
    for n in names:
        v = low.get(n.lower().replace("_", "").replace(" ", ""))
        if v not in (None, ""):
            return v
    return ""


def _num(x) -> float:
    try:
        return float(str(x).replace(",", "").replace("$", "").replace("USD", "").strip())
    except Exception:  # noqa: BLE001
        return 0.0


def normalise(t: dict) -> dict:
    return {
        "entry_time": _get(t, "entryTime", "entry_time", "entryDate", "dateEntry", "openTime", "entry date"),
        "exit_time": _get(t, "exitTime", "exit_time", "exitDate", "dateExit", "closeTime", "exit date"),
        "side": _get(t, "side", "direction", "type", "entryType"),
        "entry_price": _get(t, "entryPrice", "entry_price", "priceEntry", "entry price"),
        "exit_price": _get(t, "exitPrice", "exit_price", "priceExit", "exit price"),
        "contracts": _get(t, "contracts", "qty", "quantity", "size"),
        "profit": _get(t, "profit", "netProfit", "pnl", "net p&l", "profitUSD"),
        "signal": _get(t, "exitSignal", "exitComment", "signal", "comment", "exit signal"),
        "raw": json.dumps(t, sort_keys=True, default=str),
    }


def key(n: dict) -> str:
    return "|".join(str(n[k]) for k in ("entry_time", "exit_time", "side", "entry_price", "exit_price", "profit")) \
        if any(n[k] for k in ("entry_time", "exit_time", "profit")) else n["raw"]


def summary(rows: list[dict]) -> str:
    # one position per entry time (a partial exit shows as several rows)
    pos: dict[str, float] = {}
    for r in rows:
        pos[str(r["entry_time"]) + str(r.get("symbol", ""))] = pos.get(str(r["entry_time"]) + str(r.get("symbol", "")), 0.0) + _num(r["profit"])
    p = list(pos.values())
    if not p:
        return "no trades logged yet"
    wins = [x for x in p if x > 0]
    gl = -sum(x for x in p if x <= 0)
    pf = sum(wins) / gl if gl > 0 else float("inf")
    return (f"{len(p)} positions ({len(rows)} rows) | WR {len(wins) / len(p):.0%} | PF {pf:.2f} | "
            f"net ${sum(p):,.0f}   [{BACKTEST}]")


def load_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


FIELDS = ["logged_at", "symbol", "entry_time", "exit_time", "side", "entry_price", "exit_price",
          "contracts", "profit", "signal", "raw"]


async def poll_once(args, seen: set[str], rows: list[dict]) -> int:
    params = StdioServerParameters(command=args.node, args=[args.server])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            if args.list_tools:
                print("\n".join(tools))
                return 0
            ttool = args.trades_tool or next((t for t in tools if "trade" in t.lower() and "screenshot" not in t.lower()), None)
            if not ttool:
                raise SystemExit(f"no trades tool found; tools are: {tools}")
            symbol = ""
            stool = next((t for t in tools if "chart" in t.lower() and ("state" in t.lower() or "info" in t.lower())), None)
            if stool:
                try:
                    st = _payload(await s.call_tool(stool, {}))
                    symbol = str(_get(st, "symbol", "ticker")) if isinstance(st, dict) else ""
                except Exception:  # noqa: BLE001
                    pass
            trades = _trade_list(_payload(await s.call_tool(ttool, {})))
            new = 0
            for t in trades:
                n = normalise(t)
                n["symbol"] = symbol
                k = symbol + "|" + key(n)
                if k in seen:
                    continue
                if args.since and str(n["entry_time"]) and str(n["entry_time"]) < args.since:
                    seen.add(k)            # pre-forward-test trade: remember, do not log
                    continue
                seen.add(k)
                n["logged_at"] = datetime.now().isoformat(timespec="seconds")
                rows.append(n)
                new += 1
                with open(args.out, "a", newline="", encoding="utf-8") as fh:
                    wtr = csv.DictWriter(fh, fieldnames=FIELDS)
                    if fh.tell() == 0:
                        wtr.writeheader()
                    wtr.writerow({k2: n.get(k2, "") for k2 in FIELDS})
                print(f"NEW  {symbol} {n['side']} {n['entry_time']} -> {n['exit_time']}  {n['signal']}  ${_num(n['profit']):,.2f}")
            rtool = args.results_tool or next((t for t in tools if "strategy" in t.lower() and "result" in t.lower()), None)
            if rtool:
                try:
                    res = _payload(await s.call_tool(rtool, {}))
                    with open(os.path.splitext(args.out)[0] + "_strategy_results.json", "w", encoding="utf-8") as fh:
                        json.dump({"at": datetime.now().isoformat(timespec="seconds"), "symbol": symbol, "results": res},
                                  fh, indent=2, default=str)
                except Exception:  # noqa: BLE001
                    pass
            return new


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", required=True, help="path to tradingview-mcp/src/server.js")
    ap.add_argument("--node", default="node")
    ap.add_argument("--out", default="forward_trades.csv")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--since", default="", help="only log trades entered on/after this date (YYYY-MM-DD)")
    ap.add_argument("--trades-tool", default="")
    ap.add_argument("--results-tool", default="")
    ap.add_argument("--list-tools", action="store_true")
    ap.add_argument("--once", action="store_true", help="poll once and exit")
    args = ap.parse_args()

    rows = load_csv(args.out)
    seen = {r.get("symbol", "") + "|" + key({**r}) for r in rows}
    print(f"logging to {args.out}; {summary(rows)}")
    while True:
        try:
            new = asyncio.run(poll_once(args, seen, rows))
            if args.list_tools:
                return
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            print(f"[{stamp}] {new} new | {summary(rows)}")
        except Exception as e:  # noqa: BLE001 - keep running (TradingView closed, etc.)
            print(f"[{datetime.now():%H:%M}] poll failed: {e!r}", file=sys.stderr)
            if args.list_tools:
                raise
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
