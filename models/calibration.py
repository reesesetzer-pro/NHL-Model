"""
models/calibration.py — In-memory NHL calibration from settled shadow picks.

Same pattern as NBA: read settled SHADOW bets from `bets` table, bucket by
(market × probability), compute actual hit rate, expose lookup for edge_engine.

Sample-size-adaptive blend: weight on empirical scales linearly from 0 at
n=MIN_N up to 1.0 at n=FULL_TRUST_N. Picks raw probability when bucket lacks
data, blends increasingly toward empirical hit rate as n grows.

Mirrors NBA audit lessons (2026-05-02):
  - Original `<55%` bucket lumped longshots with close calls — finer
    low-prob buckets prevent the bucket-flatten manufacturing fake edges.
  - Fixed 40/60 blend was too gentle in deep buckets (overshoot 12-19pp);
    adaptive blend lets buckets with deep data carry their own weight.
  - FULL_TRUST_N=50 (not 20) — n=21 is too small to trust 100% empirical.
"""
from __future__ import annotations
import json
import pandas as pd

from models.auto_log_picks import fetch_shadow_picks


_BUCKETS = [
    ("<10%",   0.00, 0.10),
    ("10-25%", 0.10, 0.25),
    ("25-40%", 0.25, 0.40),
    ("40-55%", 0.40, 0.55),
    ("55-60%", 0.55, 0.60),
    ("60-70%", 0.60, 0.70),
    ("70-80%", 0.70, 0.80),
    ("80%+",   0.80, 1.01),
]

_MIN_N         = 8     # minimum n to use the bucket at all
_FULL_TRUST_N  = 50    # at n ≥ this, blend is 100% empirical


def _bucket_label(prob: float) -> str:
    for label, lo, hi in _BUCKETS:
        if lo <= prob < hi:
            return label
    return "<10%"


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


def load_calibration_lookup(min_n: int = _MIN_N) -> dict:
    """Compute lookup from settled shadow picks.

    Returns {(market, bucket): (hit_rate, n)} — n needed for adaptive blend.
    """
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
        n = len(g)
        if n < min_n:
            continue
        actual = float(g["is_win"].mean())
        out[(mkt, bucket)] = (actual, n)
    return out


def calibrate_prob(raw_prob: float, market: str, lookup: dict) -> float:
    """Blend raw model probability with empirical hit rate (adaptive weight)."""
    if raw_prob is None or raw_prob != raw_prob:
        return raw_prob
    bucket = _bucket_label(raw_prob)
    entry = lookup.get((market, bucket))
    if entry is None:
        return raw_prob
    actual, n = entry
    if n <= _MIN_N:
        w = 0.0
    elif n >= _FULL_TRUST_N:
        w = 1.0
    else:
        w = (n - _MIN_N) / (_FULL_TRUST_N - _MIN_N)
    blended = (1.0 - w) * raw_prob + w * actual
    return round(blended, 4)


if __name__ == "__main__":
    lookup = load_calibration_lookup()
    print(f"NHL calibration lookup ({len(lookup)} entries with n≥{_MIN_N}):")
    for k, (actual, n) in sorted(lookup.items()):
        if n <= _MIN_N: w = 0.0
        elif n >= _FULL_TRUST_N: w = 1.0
        else: w = (n - _MIN_N) / (_FULL_TRUST_N - _MIN_N)
        print(f"  {k}: actual {actual*100:.1f}%  n={n}  weight={w*100:.0f}%")
