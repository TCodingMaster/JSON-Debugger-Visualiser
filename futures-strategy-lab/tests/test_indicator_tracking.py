"""The indicator's virtual-trade tracking (pine/fvg_pro_setups_indicator.pine,
steps 1-3 and resolveFill) transliterated to Python must reproduce the backtest
engine's trades exactly (no costs, TradingView intrabar model)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lab import data, engine, features, fvg_pro  # noqa: E402


def resolve_fill(o, h, l, c, side, entry, stop, rr):
    path = [o, l, h, c] if o - l <= h - o else [o, h, l, c]
    state, fill, tgt, exit_px, is_tp, start_k, a0 = 0, None, None, None, False, 1, o
    if (side > 0 and o <= entry) or (side < 0 and o >= entry):
        fill = o
        if (fill - stop) * side <= 0:
            state = 1
    else:
        for k in range(1, 4):
            if state == 0 and fill is None:
                a, b = path[k - 1], path[k]
                lo, hi = min(a, b), max(a, b)
                he, hs = lo <= entry <= hi, lo <= stop <= hi
                if he or hs:
                    de = abs(entry - a) if he else 1e18
                    ds = abs(stop - a) if hs else 1e18
                    if ds < de:
                        state = 1
                    else:
                        fill, start_k, a0 = entry, k, entry
    if state == 0 and fill is not None:
        tgt = fill + side * rr * (fill - stop) * side
        state = 2
        for k in range(start_k, 4):
            if state == 2:
                b = path[k]
                a = a0 if k == start_k else path[k - 1]
                lo, hi = min(a, b), max(a, b)
                hs, ht = lo <= stop <= hi, lo <= tgt <= hi
                if hs or ht:
                    ds = abs(stop - a) if hs else 1e18
                    dt = abs(tgt - a) if ht else 1e18
                    state, is_tp = 3, dt < ds
                    exit_px = tgt if is_tp else stop
    return state, fill, tgt, exit_px, is_tp


def indicator_trades(feat, inst, setups, rr, expiry, max_trades, flat=15 * 60 + 55):
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    by = {}
    for s in setups:
        by.setdefault(s.bar, []).append(s)
    after_flat = lambda m: flat <= m < 18 * 60  # noqa: E731
    out = []
    day_key, day_trades = None, 0
    p = None   # pending: (side, entry, stop, inval, bar)
    act = None  # (side, entry, stop, tgt, bar)
    for i in range(feat.n):
        new_day = day_key is None or feat.day[i] != day_key
        if new_day:
            day_key, day_trades = feat.day[i], 0
        m = feat.mod[i]
        if act:
            side, e, st, tg, b0 = act
            px, why = None, ""
            if new_day or after_flat(m):
                px, why = o[i], "eod"
            else:
                gap_stop = o[i] <= st if side > 0 else o[i] >= st
                hit_s = l[i] <= st if side > 0 else h[i] >= st
                hit_t = h[i] >= tg if side > 0 else l[i] <= tg
                tfirst = (h[i] - o[i] < o[i] - l[i]) if side > 0 else (o[i] - l[i] < h[i] - o[i])
                if gap_stop:
                    px, why = o[i], "sl"
                elif hit_s and hit_t and tfirst:
                    px, why = tg, "tp"
                elif hit_s:
                    px, why = st, "sl"
                elif hit_t:
                    gt = o[i] >= tg if side > 0 else o[i] <= tg
                    px, why = (o[i] if gt else tg), "tp"
            if px is not None:
                out.append((b0, i, why, round(px, 6)))
                act = None
        if p and act is None:
            side, e, st, inv, pb = p
            cancel = i - pb > expiry or new_day or after_flat(m) or day_trades >= max_trades
            if not cancel:
                state, fill, tgt, xp, is_tp = resolve_fill(o[i], h[i], l[i], c[i], side, e, st, rr)
                if state == 1:
                    cancel = True
                elif state >= 2:
                    act = (side, fill, st, tgt, i)
                    day_trades += 1
                    p = None
                    if state == 3:
                        out.append((i, i, "tp" if is_tp else "sl", round(xp, 6)))
                        act = None
                elif (side > 0 and c[i] < inv) or (side < 0 and c[i] > inv):
                    cancel = True
            if cancel:
                p = None
        if i in by and act is None and day_trades < max_trades and not after_flat(m):
            for s in by[i]:
                risk = (s.entry - s.stop) * s.side
                if risk >= 4 * inst.tick and (a[i] <= 0 or risk <= 3 * a[i]):
                    p = (s.side, s.entry, s.stop, s.invalidate, i)
    return out


@pytest.mark.parametrize("sym,seed,max_trades", [("MNQ", 3, 1), ("MGC", 8, 2), ("MNQ", 21, 1)])
def test_indicator_tracking_matches_engine(sym, seed, max_trades):
    df = data.synthetic(sym, days=40, seed=seed)
    inst = data.Instrument(sym, data.get_instrument(sym).tick, data.get_instrument(sym).point_value, 1, 0.0)
    f = features.build(df, inst.tick)
    p = {**fvg_pro.DEFAULTS, "rr": 1.5, "max_trades": max_trades}
    setups = fvg_pro.generate(f, inst, p)
    eng = engine.run(f, setups, inst, engine.EngineConfig(slippage_ticks=0, max_trades_per_day=max_trades, intrabar="path"))
    idx = {t: k for k, t in enumerate(f.df.index.map(lambda x: x.isoformat()))}
    ref = [(idx[t.entry_time], idx[t.exit_time], t.reason, t.exit) for t in eng]
    got = indicator_trades(f, inst, setups, 1.5, p["expiry"], max_trades)
    assert len(ref) > 10
    assert [x[:3] for x in got] == [x[:3] for x in ref]
    # exit prices agree to within one tick (a 1.5R target can fall between ticks)
    assert all(abs(g[3] - r[3]) <= inst.tick + 1e-9 for g, r in zip(got, ref))
