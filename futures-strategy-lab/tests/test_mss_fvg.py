"""MSS + sweep + FVG: Pine transliteration must match lab/mss_fvg.py."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lab import data, features, mss_fvg  # noqa: E402
from lab.features import hm  # noqa: E402


def pine_like(feat, inst, p):
    """pine/mss_sweep_fvg_strategy.pine (signal part), using bars-back offsets."""
    h, l, c, a = feat.h, feat.l, feat.c, feat.atr
    L, tick = p["pivot_len"], inst.tick
    win = np.zeros(feat.n, bool)
    for s_, e_ in p["windows"]:
        win |= (feat.mod >= hm(s_)) & (feat.mod < hm(e_))
    sh = psh = sl = psl = math.nan
    sh_bar = sl_bar = None
    shs, sls = [], []
    used_up = used_dn = None
    armed, pend, out = [], [], []
    for bi in range(feat.n):
        H = lambda k: h[bi - k]  # noqa: E731
        Lo = lambda k: l[bi - k]  # noqa: E731
        if bi >= 2 * L:
            hiR = lambda k: max(h[bi - k - L + 1: bi - k + 1])  # noqa: E731
            loR = lambda k: min(l[bi - k - L + 1: bi - k + 1])  # noqa: E731
            if H(L) > hiR(L + 1) and H(L) >= hiR(0):
                psh, sh, sh_bar = sh, H(L), bi - L
                shs.append((sh_bar, sh))
            if Lo(L) < loR(L + 1) and Lo(L) <= loR(0):
                psl, sl, sl_bar = sl, Lo(L), bi - L
                sls.append((sl_bar, sl))

        def gap(k, side):
            if bi - k - 2 < 0:
                return None
            if side > 0 and Lo(k) > H(k + 2) and Lo(k) - H(k + 2) >= p["min_fvg_atr"] * a[bi - k]:
                return H(k + 2), Lo(k)
            if side < 0 and H(k) < Lo(k + 2) and Lo(k + 2) - H(k) >= p["min_fvg_atr"] * a[bi - k]:
                return H(k), Lo(k + 2)
            return None

        def last_before(hist, before):
            for b, v in reversed(hist):
                if b < before:
                    return v
            return math.nan

        for side in (1, -1):
            mss, start = False, None
            if side > 0 and bi > 2 * L:
                mss = not math.isnan(psh) and sh < psh and c[bi] > sh and used_up != sh_bar
                if mss:
                    used_up, start = sh_bar, sh_bar
            if side < 0 and bi > 2 * L:
                mss = not math.isnan(psl) and sl > psl and c[bi] < sl and used_dn != sl_bar
                if mss:
                    used_dn, start = sl_bar, sl_bar
            if not mss:
                continue
            span = min(bi - start, 400)
            ext, ext_off = (Lo(span), span) if side > 0 else (H(span), span)
            for j in range(span, -1, -1):
                if side > 0 and Lo(j) < ext:
                    ext, ext_off = Lo(j), j
                if side < 0 and H(j) > ext:
                    ext, ext_off = H(j), j
            liq = last_before(sls if side > 0 else shs, start)
            if math.isnan(liq) or not (ext < liq if side > 0 else ext > liq):
                continue
            got = False
            for off in range(0, ext_off - 2 + 1):
                g = gap(off, side)
                if g:
                    got = True
                    armed.append([side, g[0], g[1], bi])
                    break
            if not got:
                pend.append([side, bi])
        keep = []
        for ps, pm in pend:
            if pm == bi:
                keep.append([ps, pm])
                continue
            g = gap(0, ps)
            if g:
                armed.append([ps, g[0], g[1], bi])
            elif bi - pm < p["fvg_after"]:
                keep.append([ps, pm])
        pend = keep
        keep = []
        for side, bot, top, born in armed:
            k = True
            if born != bi:
                if bi - born > p["expiry"]:
                    k = False
                elif (side > 0 and c[bi] < bot) or (side < 0 and c[bi] > top):
                    k = False
                else:
                    touched = l[bi] <= top if side > 0 else h[bi] >= bot
                    held = (c[bi] > top if side > 0 else c[bi] < bot) if p["respect"] == "strict" else \
                        (c[bi] >= bot if side > 0 else c[bi] <= top)
                    if touched and held:
                        k = False
                        if win[bi]:
                            st = bot - p["stop_ticks"] * tick if side > 0 else top + p["stop_ticks"] * tick
                            out.append((bi, side, round(st, 4)))
            if k:
                keep.append([side, bot, top, born])
        armed = keep
    return out


@pytest.mark.parametrize("sym,seed", [("MNQ", 3), ("MGC", 8)])
def test_mss_pine_transliteration_matches(sym, seed):
    df = data.synthetic(sym, days=25, seed=seed)
    inst = data.get_instrument(sym)
    f = features.build(df, inst.tick)
    p = dict(mss_fvg.DEFAULTS)
    py = [(s.bar, s.side, round(s.stop, 4)) for s in mss_fvg.generate(f, inst, p)]
    assert len(py) > 10
    assert py == pine_like(f, inst, p)


def test_mss_no_lookahead():
    df = data.synthetic("MGC", days=15, seed=6)
    inst = data.get_instrument("MGC")
    f = features.build(df, inst.tick)
    cut = f.n // 2
    f2 = features.build(df.iloc[:cut], inst.tick)
    k = lambda s: (s.bar, s.side, s.stop)  # noqa: E731
    full = [k(s) for s in mss_fvg.generate(f, inst) if s.bar < cut - 1]
    part = [k(s) for s in mss_fvg.generate(f2, inst) if s.bar < cut - 1]
    assert full == part
