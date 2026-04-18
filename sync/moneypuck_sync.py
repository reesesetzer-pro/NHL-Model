"""
moneypuck_sync.py
Downloads MoneyPuck team xG/Corsi stats and stores in the team_stats table.
Runs once daily — MoneyPuck updates after each game night.

Pulls two situations:
  - "all"   : overall team strength (used as primary model input)
  - "5on5"  : even-strength only (used as secondary signal)
"""

import requests
import hashlib
import pandas as pd
import io
from datetime import datetime, timezone

from config import MONEYPUCK_TEAMS_URL, MONEYPUCK_PLAYOFF_TEAMS_URL, CURRENT_SEASON
from utils.db import upsert


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


# MoneyPuck uses slightly different abbreviations in some seasons
_MP_ABBR_MAP = {
    "T.B":  "TBL",
    "N.J":  "NJD",
    "S.J":  "SJS",
    "L.A":  "LAK",
    "PHX":  "UTA",
    "ARI":  "UTA",
}

def _normalize_abbr(abbr: str) -> str:
    return _MP_ABBR_MAP.get(str(abbr).strip(), str(abbr).strip())


def _download_csv(url: str) -> pd.DataFrame:
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"[moneypuck] Download error {url}: {e}")
        return pd.DataFrame()


def _parse_rows(df: pd.DataFrame, season_type: str, now: str) -> list[dict]:
    rows = []
    if df.empty:
        return rows

    for situation in ["all", "5on5"]:
        sit_df = df[df["situation"] == situation] if "situation" in df.columns else df
        if sit_df.empty:
            continue

        for _, row in sit_df.iterrows():
            try:
                abbr      = _normalize_abbr(row.get("team", ""))
                ice_time  = float(row.get("iceTime", 0) or 0)
                if ice_time < 100:          # skip rows with almost no ice time
                    continue

                xgf = float(row.get("xGoalsFor",     0) or 0)
                xga = float(row.get("xGoalsAgainst",  0) or 0)
                gf  = float(row.get("goalsFor",       0) or 0)
                ga  = float(row.get("goalsAgainst",   0) or 0)
                gp  = int(row.get("gamesPlayed", row.get("games_played", 0)) or 0)

                # iceTime is in SECONDS — multiply by 3600 to get per-60-min rate
                xgf_per60 = (xgf / ice_time) * 3600
                xga_per60 = (xga / ice_time) * 3600
                gf_per60  = (gf  / ice_time) * 3600
                ga_per60  = (ga  / ice_time) * 3600

                xg_pct      = float(row.get("xGoalsPercentage", 0) or 0)
                corsi_pct   = float(row.get("corsiPercentage",  0) or 0)
                fenwick_pct = float(row.get("fenwickPercentage",0) or 0)

                row_id = _make_id(abbr, CURRENT_SEASON, season_type, situation)
                rows.append({
                    "id":           row_id,
                    "team_abbr":    abbr,
                    "season":       CURRENT_SEASON,
                    "season_type":  season_type,
                    "situation":    situation,
                    "games_played": gp,
                    "xgf_per60":    round(xgf_per60,  4),
                    "xga_per60":    round(xga_per60,  4),
                    "xg_pct":       round(xg_pct,     4),
                    "corsi_pct":    round(corsi_pct,  4),
                    "fenwick_pct":  round(fenwick_pct,4),
                    "gf_per60":     round(gf_per60,   4),
                    "ga_per60":     round(ga_per60,   4),
                    "updated_at":   now,
                })
            except Exception as e:
                print(f"[moneypuck] Row parse error: {e}")
                continue

    return rows


def run_moneypuck_sync(include_playoffs: bool = False) -> None:
    print("[moneypuck] Syncing team stats...")
    now  = datetime.now(timezone.utc).isoformat()
    rows = []

    # Regular season stats
    df_regular = _download_csv(MONEYPUCK_TEAMS_URL)
    rows.extend(_parse_rows(df_regular, "regular", now))

    # Playoff stats (only once playoffs are underway)
    if include_playoffs:
        df_playoff = _download_csv(MONEYPUCK_PLAYOFF_TEAMS_URL)
        rows.extend(_parse_rows(df_playoff, "playoffs", now))

    if rows:
        upsert("team_stats", rows, on_conflict="id")
        teams = {r["team_abbr"] for r in rows if r["situation"] == "all"}
        print(f"[moneypuck] {len(rows)} rows synced | {len(teams)} teams | season {CURRENT_SEASON}")
    else:
        print("[moneypuck] No rows — MoneyPuck may not have data for this season yet.")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    run_moneypuck_sync(include_playoffs=True)
