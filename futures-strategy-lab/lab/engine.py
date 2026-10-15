"""Bar-by-bar execution simulator.

Strategies emit `Setup`s (decided on the CLOSE of `bar`); the engine works
orders from the next bar on. Conservative assumptions throughout:

* Open position, stop and target both inside one bar -> stop assumed first.
* On the bar an order fills, the intrabar order of events follows the OHLC
  path model (open -> nearer extreme -> farther extreme -> close).
* Stop entries, market entries and stop-loss exits pay `slippage_ticks`;
  limit entries and take-profits fill at their price (or better on a gap).
* A pending order is cancelled if price trades through its stop before it
  fills, if a bar closes beyond its invalidation level, at expiry or at the
  flatten time. Open positions are flattened at the flatten time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .data import Instrument
from .features import Features, hm


@dataclass
class Setup:
    bar: int                  # signal known at the close of this bar
    side: int                 # +1 long, -1 short
    entry_type: str           # "limit" | "stop" | "market"
    entry: float              # ignored for market
    stop: float
    rr: float = 2.0
    expiry: int = 20          # bars the order stays working
    invalidate: float | None = None  # cancel if a bar closes beyond this (against the trade)
    note: str = ""


@dataclass
class Trade:
    entry_time: str
    exit_time: str
    side: str
    entry: float
    stop: float
    target: float
    exit: float
    risk_pts: float
    r: float                  # net R (after costs) relative to planned $ risk
    pnl: float                # net $
    reason: str               # tp | sl | be | eod
    bars: int
    note: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class EngineConfig:
    flatten: str = "15:55"
    max_trades_per_day: int = 2
    slippage_ticks: int = 1
    be_at_r: float = 0.0       # move stop to entry once price reaches this R (0 = off)
    min_risk_ticks: int = 4
    max_risk_atr: float = 3.0  # skip setups with a stop wider than this × ATR
    contracts: int | None = None  # override the instrument default
    # "conservative": stop first when stop and target share a bar.
    # "path": TradingView's broker-emulator assumption (open -> nearer extreme -> farther extreme).
    intrabar: str = "conservative"
    extra: dict = field(default_factory=dict)


def run(feat: Features, setups: list[Setup], inst: Instrument, cfg: EngineConfig) -> list[Trade]:
    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    idx = feat.df.index
    n = feat.n
    flat = hm(cfg.flatten)
    tick = inst.tick
    slip = cfg.slippage_ticks * tick
    qty = cfg.contracts or inst.contracts
    costs = 2 * inst.commission * qty
    by_bar: dict[int, list[Setup]] = {}
    for s in setups:
        by_bar.setdefault(s.bar, []).append(s)

    def after_flat(i):
        return flat <= feat.mod[i] < 18 * 60

    trades: list[Trade] = []
    pending: Setup | None = None
    pend_age = 0
    pos = None  # dict(side, entry, stop, target, risk, i0, be_done, setup)
    day_count: dict[int, int] = {}

    def close_pos(i, price, reason):
        nonlocal pos
        side = pos["side"]
        pts = (price - pos["entry"]) * side
        pnl = pts * inst.point_value * qty - costs
        risk_usd = pos["risk"] * inst.point_value * qty
        trades.append(Trade(
            entry_time=idx[pos["i0"]].isoformat(), exit_time=idx[i].isoformat(),
            side="long" if side > 0 else "short", entry=pos["entry"], stop=pos["stop0"],
            target=pos["target"], exit=inst.round_price(price), risk_pts=round(pos["risk"], 6),
            r=round(pnl / risk_usd, 4), pnl=round(pnl, 2), reason=reason, bars=i - pos["i0"],
            note=pos["setup"].note))
        pos = None

    for i in range(n):
        new_day = i > 0 and feat.day[i] != feat.day[i - 1]

        # 1) manage open position on bar i
        if pos is not None:
            side, stop, target = pos["side"], pos["stop"], pos["target"]
            if new_day or after_flat(i):
                close_pos(i, o[i] - side * slip, "eod")
            else:
                gap_through = (o[i] <= stop) if side > 0 else (o[i] >= stop)
                hit_stop = (l[i] <= stop) if side > 0 else (h[i] >= stop)
                hit_tgt = (h[i] >= target) if side > 0 else (l[i] <= target)
                if gap_through:
                    close_pos(i, o[i] - side * slip, "be" if pos["be_done"] else "sl")
                elif hit_stop and hit_tgt and cfg.intrabar == "path" and (
                        (h[i] - o[i] < o[i] - l[i]) if side > 0 else (o[i] - l[i] < h[i] - o[i])):
                    # open is nearer the target side: TradingView assumes it is reached first
                    close_pos(i, target, "tp")
                elif hit_stop:
                    close_pos(i, stop - side * slip, "be" if pos["be_done"] else "sl")
                elif hit_tgt:
                    gap_tgt = (o[i] >= target) if side > 0 else (o[i] <= target)
                    close_pos(i, o[i] if gap_tgt else target, "tp")
                elif cfg.be_at_r > 0 and not pos["be_done"]:
                    trig = pos["entry"] + side * cfg.be_at_r * pos["risk"]
                    if (h[i] >= trig) if side > 0 else (l[i] <= trig):
                        pos["stop"] = pos["entry"]
                        pos["be_done"] = True

        # 2) work the pending order (only when flat)
        if pending is not None and pos is None:
            s = pending
            pend_age += 1
            if (new_day or after_flat(i) or pend_age > s.expiry
                    or day_count.get(feat.day[i], 0) >= cfg.max_trades_per_day):
                pending = None
            else:
                res = _resolve_fill_bar(s, o[i], h[i], l[i], c[i], slip)
                if res is None:  # untouched: check FVG/level invalidation on the close
                    if s.invalidate is not None and ((c[i] < s.invalidate) if s.side > 0 else (c[i] > s.invalidate)):
                        pending = None
                elif res[0] == "cancel":
                    pending = None
                else:
                    _, fill, target, exit_px, reason = res
                    pending = None
                    pos = dict(side=s.side, entry=fill, stop=s.stop, stop0=s.stop, target=target,
                               risk=(fill - s.stop) * s.side, i0=i, be_done=False, setup=s)
                    day_count[feat.day[i]] = day_count.get(feat.day[i], 0) + 1
                    if exit_px is not None:
                        close_pos(i, exit_px, reason)

        # 3) accept new setups decided at this bar's close
        if pos is None and i in by_bar:
            for s in by_bar[i]:
                if day_count.get(feat.day[i], 0) >= cfg.max_trades_per_day or after_flat(i):
                    continue
                ref = c[i] if s.entry_type == "market" else s.entry
                risk = (ref - s.stop) * s.side
                if risk < cfg.min_risk_ticks * tick or (feat.atr[i] > 0 and risk > cfg.max_risk_atr * feat.atr[i]):
                    continue
                pending, pend_age = s, 0  # newest valid setup replaces an older pending one

    if pos is not None:
        close_pos(n - 1, c[n - 1], "eod")
    return trades


def _resolve_fill_bar(s: Setup, o, h, l, c, slip):
    """Resolve one bar for a pending order with the usual OHLC path model:
    open -> nearer extreme -> farther extreme -> close (TradingView's default
    assumption without bar magnifier). Returns None (not touched),
    ("cancel",) (stop level traded before the entry -> setup void) or
    ("fill", fill_price, target, exit_price | None, reason)."""
    side = s.side
    path = [o, l, h, c] if (o - l) <= (h - o) else [o, h, l, c]
    if s.entry_type == "market":
        fill = o + side * slip
    else:
        fill = None
        # gap through the entry at the open: fill at the open (better for limits, worse for stops)
        if s.entry_type == "limit" and ((o <= s.entry) if side > 0 else (o >= s.entry)):
            fill = o
        elif s.entry_type == "stop" and ((o >= s.entry) if side > 0 else (o <= s.entry)):
            fill = o + side * slip
        if fill is not None and ((fill - s.stop) * side <= 0):
            return ("cancel",)
    seg_start = 0
    if fill is None:
        # walk the path until either the entry or the stop level is touched
        for k in range(1, len(path)):
            a, b = path[k - 1], path[k]
            lo, hi = min(a, b), max(a, b)
            hits = []
            if lo <= s.entry <= hi:
                hits.append((abs(s.entry - a), "entry"))
            if lo <= s.stop <= hi:
                hits.append((abs(s.stop - a), "stop"))
            if hits:
                hits.sort()
                if hits[0][1] == "stop":
                    return ("cancel",)
                fill = s.entry + (side * slip if s.entry_type == "stop" else 0.0)
                path = [s.entry] + path[k:]
                seg_start = 1
                break
        if fill is None:
            return None
    risk = (fill - s.stop) * side
    if risk <= 0:
        return ("cancel",)
    target = fill + side * s.rr * risk
    # after the fill, walk the rest of the bar for stop / target
    for k in range(max(1, seg_start), len(path)):
        a, b = path[k - 1], path[k]
        lo, hi = min(a, b), max(a, b)
        hits = []
        if lo <= s.stop <= hi:
            hits.append((abs(s.stop - a), 0, "sl"))
        if lo <= target <= hi:
            hits.append((abs(target - a), 1, "tp"))
        if hits:
            hits.sort()
            reason = hits[0][2]
            return ("fill", fill, target, (s.stop - side * slip) if reason == "sl" else target, reason)
    return ("fill", fill, target, None, "")


def trades_r(trades: list[Trade]) -> np.ndarray:
    return np.array([t.r for t in trades], dtype=float)
