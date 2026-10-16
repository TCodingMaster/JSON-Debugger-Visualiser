# Forward-test logger (TradingView MCP)

`tools/tv_trade_logger.py` reads the Strategy Tester of TradingView Desktop through the community
TradingView MCP server (https://github.com/tradesdontlie/tradingview-mcp) and appends every new trade
to `forward_trades.csv`, printing a running summary (positions, win rate, PF, net $) next to the
backtest numbers. It runs on your own computer, where TradingView Desktop runs.

1. Install Node.js 18+ and Python 3.10+.
2. `git clone https://github.com/tradesdontlie/tradingview-mcp.git && cd tradingview-mcp && npm install`
3. Start TradingView Desktop with remote debugging (scripts in that repo:
   `scripts/launch_tv_debug_mac.sh`, `scripts\launch_tv_debug.bat`, `scripts/launch_tv_debug_linux.sh`).
4. Open MNQ1! 15m with "FVG Pro L" (your settings) and keep the Strategy Tester visible.
5. `pip install mcp`, then:
   `python tv_trade_logger.py --server /path/to/tradingview-mcp/src/server.js --since 2026-10-19`
   (`--list-tools` shows the server's tools; `--interval 300` = poll every 5 minutes.)
6. For gold, run a second logger with `--out forward_trades_mgc.csv` while the MGC1! chart is active
   (the Strategy Tester shows only the active chart's strategy).

Partial exits appear as several rows; the summary groups them into one position by entry time.
Tested against a simulated MCP server; tool names are discovered automatically (first tool whose
name contains "trade"), override with `--trades-tool` if the server names it differently.
