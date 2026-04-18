"""
scheduler.py
APScheduler orchestrator — runs all sync jobs on their respective intervals.
Can be run standalone: python sync/scheduler.py
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    SYNC_ODDS_INTERVAL, SYNC_GOALIES_INTERVAL,
    SYNC_INJURIES_INTERVAL, SYNC_LINEUPS_INTERVAL,
    SYNC_SERIES_INTERVAL, SYNC_MONEYPUCK_INTERVAL,
)
from sync.odds_sync        import run_game_odds_sync, run_props_sync
from sync.goalies_sync     import run_goalie_sync
from sync.injuries_sync    import run_injuries_sync
from sync.lineups_sync     import run_lineups_sync
from sync.series_sync      import run_series_sync
from sync.moneypuck_sync   import run_moneypuck_sync
from models.edge_engine    import calculate_all_edges, calculate_all_prop_edges

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scheduler")


def run_all() -> None:
    """Cold-start — run every sync immediately."""
    log.info("🏒 Cold-start sync...")
    run_moneypuck_sync()        # team xG data first — needed by edge engine
    run_series_sync()           # backfills game_type before odds parse
    run_injuries_sync()
    run_goalie_sync()
    run_lineups_sync()
    run_game_odds_sync()
    calculate_all_edges()       # game-level edges → edges table
    run_props_sync()
    calculate_all_prop_edges()  # prop edges → props table
    log.info("✅ Cold-start complete.")


def main() -> None:
    run_all()

    scheduler = BlockingScheduler(timezone="America/New_York")

    scheduler.add_job(
        run_moneypuck_sync,
        trigger=IntervalTrigger(seconds=SYNC_MONEYPUCK_INTERVAL),
        id="moneypuck",
        name="MoneyPuck xG Sync",
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_series_sync,
        trigger=IntervalTrigger(seconds=SYNC_SERIES_INTERVAL),
        id="series",
        name="Playoff Series Sync",
        max_instances=1,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        run_injuries_sync,
        trigger=IntervalTrigger(seconds=SYNC_INJURIES_INTERVAL),
        id="injuries",
        name="Injuries Sync",
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_goalie_sync,
        trigger=IntervalTrigger(seconds=SYNC_GOALIES_INTERVAL),
        id="goalies",
        name="Goalies Sync",
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_lineups_sync,
        trigger=IntervalTrigger(seconds=SYNC_LINEUPS_INTERVAL),
        id="lineups",
        name="Lineups Sync",
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_game_odds_sync,
        trigger=IntervalTrigger(seconds=SYNC_ODDS_INTERVAL),
        id="odds_game",
        name="Game Odds Sync",
        max_instances=1,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        run_props_sync,
        trigger=IntervalTrigger(seconds=SYNC_ODDS_INTERVAL),
        id="odds_props",
        name="Props Sync",
        max_instances=1,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        calculate_all_prop_edges,
        trigger=IntervalTrigger(seconds=SYNC_ODDS_INTERVAL),
        id="prop_edges",
        name="Prop Edge Calc",
        max_instances=1,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        calculate_all_edges,
        trigger=IntervalTrigger(seconds=SYNC_ODDS_INTERVAL),
        id="game_edges",
        name="Game Edge Calc",
        max_instances=1,
        misfire_grace_time=120,
    )

    log.info("📅 Scheduler started.")
    log.info(f"   MoneyPuck: every {SYNC_MONEYPUCK_INTERVAL//3600}hr")
    log.info(f"   Series:    every {SYNC_SERIES_INTERVAL//60}min")
    log.info(f"   Injuries:  every {SYNC_INJURIES_INTERVAL//60}min")
    log.info(f"   Goalies:   every {SYNC_GOALIES_INTERVAL//60}min")
    log.info(f"   Lineups:   every {SYNC_LINEUPS_INTERVAL//60}min")
    log.info(f"   Odds:      every {SYNC_ODDS_INTERVAL//60}min")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
