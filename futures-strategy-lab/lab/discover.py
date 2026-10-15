"""Find new strategy concepts on YouTube and screen out gurus.

Uses the free YouTube Data API v3 (create a key in Google Cloud Console →
APIs & Services → YouTube Data API v3; set YOUTUBE_API_KEY). The quota
(10,000 units/day) covers ~90 searches/day.

Pipeline: search queries → videos → channels → score each channel for
credibility signals vs. guru red flags → tag each video with the concept
taxonomy below → write data/discovered.json for review. A human decides what
goes into data/concepts.json; nothing is promoted automatically.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3"

QUERIES = [
    "nasdaq futures day trading strategy backtest",
    "MNQ scalping strategy rules",
    "gold futures intraday strategy MGC",
    "liquidity sweep futures trading strategy",
    "fair value gap strategy backtested results",
    "order flow trading nasdaq futures professional",
    "robbins world cup trading championship interview",
    "prop trader futures strategy explained",
    "market profile value area strategy futures",
    "opening range breakout futures backtest",
]

TAXONOMY = {
    "liquidity_sweep": r"liquidity (sweep|grab|run)|stop (run|hunt)|swept|turtle soup|false break",
    "rejection_block": r"rejection block|rejection wick|pin ?bar",
    "fvg": r"fair value gap|\bfvg\b|imbalance",
    "order_block": r"order ?block",
    "opening_range": r"opening range|\borb\b",
    "vwap": r"\bvwap\b",
    "volume_profile": r"volume profile|market profile|value area|\bpoc\b",
    "order_flow": r"order ?flow|footprint|delta|absorption|\bdom\b",
    "trend": r"trend (following|continuation)|pullback|ema",
    "mean_reversion": r"mean reversion|reversal|fade",
}

GURU_FLAGS = {
    r"\$\d[\d,]*k?\s*(a|per|/)\s*(day|week|month)": "income claim",
    r"\b(9\d|100)\s?% win": "absurd win-rate claim",
    r"lambo|millionaire|quit (my|your) job|financial freedom|get rich": "lifestyle marketing",
    r"signals?\s+(group|service|channel)|copy my trades|vip (group|discord)": "sells signals",
    r"never lose|guaranteed|holy grail|secret strategy": "certainty marketing",
    r"funded in \d+ (day|hour)|pass (any|every) prop": "prop-challenge bait",
}

CRED_SIGNALS = {
    r"robbins|world cup trading": "trading competition",
    r"\bcta\b|hedge fund|prop(rietary)? (firm|desk|trader)|market maker|floor trader": "institutional background",
    r"audited|verified (track record|results)|broker statement": "verified results",
    r"backtest|statistics|sample size|expectancy": "quantitative process",
    r"market wizards|author of": "published author",
}


def _get(path: str, key: str, **params) -> dict:
    import requests

    params["key"] = key
    r = requests.get(f"{API}/{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def tag_text(text: str) -> list[str]:
    t = text.lower()
    return [tag for tag, pat in TAXONOMY.items() if re.search(pat, t)]


def screen_channel(text: str) -> dict:
    t = text.lower()
    flags = sorted({label for pat, label in GURU_FLAGS.items() if re.search(pat, t)})
    signals = sorted({label for pat, label in CRED_SIGNALS.items() if re.search(pat, t)})
    score = max(0, min(10, 5 + 2 * len(signals) - 3 * len(flags)))
    return {"guru_flags": flags, "credibility_signals": signals, "credibility_score": score,
            "verdict": "reject" if flags and score < 5 else ("review" if score < 7 else "promising")}


def discover(api_key: str | None = None, queries: list[str] | None = None, per_query: int = 15,
             out: Path | None = None) -> Path:
    key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SystemExit("Set YOUTUBE_API_KEY or pass --api-key (free key: Google Cloud → YouTube Data API v3)")
    videos: dict[str, dict] = {}
    for q in queries or QUERIES:
        res = _get("search", key, part="snippet", q=q, type="video", maxResults=per_query,
                   relevanceLanguage="en", order="relevance")
        for it in res.get("items", []):
            vid = it["id"]["videoId"]
            sn = it["snippet"]
            videos.setdefault(vid, {"video_id": vid, "title": sn["title"], "description": sn["description"],
                                    "channel_id": sn["channelId"], "channel": sn["channelTitle"],
                                    "published": sn["publishedAt"], "queries": []})["queries"].append(q)
    channel_ids = sorted({v["channel_id"] for v in videos.values()})
    channels = {}
    for k in range(0, len(channel_ids), 50):
        res = _get("channels", key, part="snippet,statistics", id=",".join(channel_ids[k:k + 50]))
        for it in res.get("items", []):
            text = it["snippet"].get("title", "") + " " + it["snippet"].get("description", "")
            channels[it["id"]] = {"channel": it["snippet"]["title"],
                                  "subscribers": int(it["statistics"].get("subscriberCount", 0) or 0),
                                  "videos": int(it["statistics"].get("videoCount", 0) or 0),
                                  **screen_channel(text)}
    rows = []
    for v in videos.values():
        ch = channels.get(v["channel_id"], {})
        vtext = v["title"] + " " + v["description"]
        vflags = screen_channel(vtext)["guru_flags"]
        rows.append({**v, "url": f"https://www.youtube.com/watch?v={v['video_id']}",
                     "tags": tag_text(vtext), "channel_screen": ch, "video_guru_flags": vflags,
                     "playbook_overlap": len({"liquidity_sweep", "rejection_block", "fvg"} & set(tag_text(vtext)))})
    rows = [r for r in rows if r["channel_screen"].get("verdict") != "reject" and not r["video_guru_flags"]]
    rows.sort(key=lambda r: (-r["channel_screen"].get("credibility_score", 0), -r["playbook_overlap"]))
    out = out or Path(__file__).resolve().parent.parent / "data" / "discovered.json"
    out.write_text(json.dumps({"queries": queries or QUERIES, "candidates": rows}, indent=2))
    return out
