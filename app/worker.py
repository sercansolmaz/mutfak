"""Nightly job runner.

    python -m app.worker        # wait for RUN_AT every night (default 03:00)
    python -m app.worker once   # run the nightly job right now
"""
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import collector, db

TZ = ZoneInfo("Europe/Istanbul")


def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def nightly():
    """Collect new comments, then apply the 30-day rule."""
    with db.connect() as conn:
        run_id = conn.execute(
            "INSERT INTO runs(started_at) VALUES(?)", (db.now_iso(),)
        ).lastrowid
    status, message, fetched, units, purged = "ok", "", 0, 0, 0
    try:
        with db.connect() as conn:
            fetched, units = collector.collect(conn)
        with db.connect() as conn:
            purged = db.purge_old(conn)
    except Exception as exc:
        status, message = "error", str(exc)[:500]
    with db.connect() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, fetched=?, quota_units=?, purged=?, status=?, message=? "
            "WHERE id=?",
            (db.now_iso(), fetched, units, purged, status, message, run_id),
        )
    log(f"run {run_id}: {status} new={fetched} quota={units} purged={purged} {message}")


def todays_run_time(now):
    hour, minute = map(int, os.environ.get("RUN_AT", "03:00").split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def next_run_after(now):
    target = todays_run_time(now)
    return target if target > now else target + timedelta(days=1)


def missed_today(now):
    """True if today's run time has passed but no run happened today (e.g. after a reboot)."""
    if now < todays_run_time(now):
        return False
    with db.connect() as conn:
        row = conn.execute("SELECT MAX(started_at) AS t FROM runs WHERE status = 'ok'").fetchone()
    if not row["t"]:
        return True
    last = datetime.strptime(row["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
    return last.astimezone(TZ).date() < now.date()


def main():
    db.init()
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        nightly()
        return
    if missed_today(datetime.now(TZ)):
        log("today's run was missed, running now")
        nightly()
    while True:
        target = next_run_after(datetime.now(TZ))
        log(f"next run at {target:%Y-%m-%d %H:%M}")
        while (remaining := (target - datetime.now(TZ)).total_seconds()) > 0:
            time.sleep(min(remaining, 60))
        nightly()


if __name__ == "__main__":
    main()
