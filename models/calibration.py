"""
models/calibration.py — In-memory NHL calibration from settled shadow picks.

Same pattern as NBA: read settled SHADOW bets from `bets` table, bucket by
(market × probability), compute actual hit rate, expose lookup for edge_engine.
"""
from __future__ import annotations
import json
import pandas as pd

from models.auto_log_picks import fetch_shadow_picks


_BUCKETS = [
    ("<55%",   0.00, 0.55),
    ("55-60%", 0.55, 0.60),
    ("60-70%", 0.60, 0.70),
    ("70-80%", 0.70, 0.80),
    ("80%+",   0.80, 1.01),
]


def _bucket_label(prob: float) -> str:
    for label, lo, hi in _BUCKETS:
        if lo <= prob < hi:
            return label
    return "<55%"


def _extract_model_prob(notes: str) -> float | None:
    """Pull model_prob from the JSON meta blob in notes."""
    if not notes or "meta=" not in notes:
        return None
    try:
        meta_str = notes.split("meta=", 1)[1].split(" actual=")[0]
        meta = json.loads(meta_str)
        return float(meta.get("model_prob")) if meta.get("model_prob") is not None else None
    except Exception:
        return None


def load_calibration_lookup(min_n: int = 8) -> dict:
    settled = fetch_shadow_picks(only_pending=False, settled_only=True)
    if settled.empty:
        return {}
    settled["model_prob"] = settled["notes"].apply(_extract_model_prob)
    settled = settled.dropna(subset=["model_prob"])
    settled = settled[settled["result"].isin(["win", "loss"])]
    if settled.empty:
        return {}
    settled["bucket"] = settled["model_prob"].apply(_bucket_label)
    settled["is_win"] = (settled["result"] == "win").astype(int)

    out = {}
    for (mkt, bucket), g in settled.groupby(["market", "bucket"]):
        if len(g) < min_n:
            continue
        out[(mkt, bucket)] = float(g["is_win"].mean())
    return out


def calibrate_prob(raw_prob: float, market: str, lookup: dict) -> float:
    if raw_prob is None or raw_prob != raw_prob:
        return raw_prob
    bucket = _bucket_label(raw_prob)
    actual = lookup.get((market, bucket))
    if actual is None:
        return raw_prob
    return round(0.40 * raw_prob + 0.60 * actual, 4)


if __name__ == "__main__":
    lookup = load_calibration_lookup()
    print(f"NHL calibration lookup ({len(lookup)} entries with n≥8):")
    for k, v in sorted(lookup.items()):
        print(f"  {k}: actual {v*100:.1f}%")
