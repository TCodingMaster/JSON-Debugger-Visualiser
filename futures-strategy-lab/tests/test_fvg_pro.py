"""FVG Pro: the Pine logic transliterated line by line must produce the same
setups as lab/fvg_pro.py (guards the Python <-> Pine mirror)."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lab import data, features, fvg_pro  # noqa: E402


def pine_like_setups(feat, inst, p):
    """Literal transliteration of pine/fvg_pro_strategy.pine (setup part):
    series accessed with bars-back offsets, same evaluation order."""
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    L, buf = p["pivot_len"], p["buffer_ticks"] * inst.tick
    win = np.zeros(feat.n, bool)
    for s_, e_ in p["windows"]:
        win |= (feat.mod >= fvg_pro.hm(s_)) & (feat.mod < fvg_pro.hm(e_))
    last_sh = last_sl = used_up = used_dn = math.nan
    wait_bar, wait_side, out = [], [], []
    for bi in range(feat.n):
        H = lambda k: h[bi - k]  # noqa: E731  high[k]
        Lo = lambda k: l[bi - k]  # noqa: E731
        if bi >= 2 * L:
            hiR = lambda k: max(h[bi - k - L + 1: bi - k + 1])  # noqa: E731  ta.highest(high, L)[k]
            loR = lambda k: min(l[bi - k - L + 1: bi - k + 1])  # noqa: E731
            if H(L) > hiR(L + 1) and H(L) >= hiR(0):
                last_sh = H(L)
            if Lo(L) < loR(L + 1) and Lo(L) <= loR(0):
                last_sl = Lo(L)
        bos_up = not math.isnan(last_sh) and c[bi] > last_sh and (math.isnan(used_up) or last_sh != used_up)
        bos_dn = not math.isnan(last_sl) and c[bi] < last_sl and (math.isnan(used_dn) or last_sl != used_dn)
        if bos_up:
            used_up = last_sh
        if bos_dn:
            used_dn = last_sl

        def gap_at(k, side):
            if bi - k - 2 < 0:
                return None
            if side > 0 and Lo(k) > H(k + 2) and Lo(k) - H(k + 2) >= p["min_fvg_atr"] * a[bi - k]:
                return H(k + 2), Lo(k)
            if side < 0 and H(k) < Lo(k + 2) and Lo(k + 2) - H(k) >= p["min_fvg_atr"] * a[bi - k]:
                return H(k), Lo(k + 2)
            return None

        sets = []

        def add(side, bos, k, bot, top):
            a_, b_ = bi - k, min(bi - bos + p["stop_lookback"], bi)
            st = (min(Lo(j) for j in range(a_, b_ + 1)) - buf) if side > 0 else (max(H(j) for j in range(a_, b_ + 1)) + buf)
            sets.append((side, bot, top, st))

        for side, ev in ((1, bos_up), (-1, bos_dn)):
            if ev:
                got = False
                for off in range(min(p["fvg_before"], bi - 2), -1, -1):
                    g = gap_at(off, side)
                    if g:
                        got = True
                        add(side, bi, bi - off, *g)
                        break
                if not got:
                    wait_bar.append(bi)
                    wait_side.append(side)
        keep_b, keep_s = [], []
        for wb, ws in zip(wait_bar, wait_side):
            if wb == bi:
                keep_b.append(wb); keep_s.append(ws)  # noqa: E702
                continue
            g = gap_at(0, ws)
            if g:
                add(ws, wb, bi, *g)
            elif bi - wb < p["fvg_after"]:
                keep_b.append(wb); keep_s.append(ws)  # noqa: E702
        wait_bar, wait_side = keep_b, keep_s
        if win[bi]:
            for side, bot, top, st in sets:
                entry = (top if side > 0 else bot) if p["entry"] == "edge" else inst.round_price((bot + top) / 2)
                out.append((bi, side, round(entry, 4), round(st, 4)))
    return out


@pytest.mark.parametrize("sym,seed", [("MNQ", 3), ("MGC", 8)])
def test_pine_transliteration_matches_python(sym, seed):
    df = data.synthetic(sym, days=20, seed=seed)
    inst = data.get_instrument(sym)
    f = features.build(df, inst.tick)
    p = dict(fvg_pro.DEFAULTS)
    # same order matters: the engine lets the last setup of a bar win
    py = [(s.bar, s.side, round(s.entry, 4), round(s.stop, 4)) for s in fvg_pro.generate(f, inst, p)]
    pine = pine_like_setups(f, inst, p)
    assert len(py) > 20
    assert py == pine


def test_fvg_pro_no_lookahead():
    df = data.synthetic("MNQ", days=15, seed=4)
    inst = data.get_instrument("MNQ")
    f, cut = features.build(df, inst.tick), None
    cut = f.n // 2
    f2 = features.build(df.iloc[:cut], inst.tick)
    k = lambda s: (s.bar, s.side, s.entry, s.stop)  # noqa: E731
    full = [k(s) for s in fvg_pro.generate(f, inst) if s.bar < cut - 1]
    part = [k(s) for s in fvg_pro.generate(f2, inst) if s.bar < cut - 1]
    assert full == part
