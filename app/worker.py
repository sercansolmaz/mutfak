"""Nightly job runner.

    python -m app.worker        # wait for RUN_AT every night (default 03:00)
    python -m app.worker once   # run the nightly job right now
"""
import fcntl
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import analyzer, collector, db

TZ = ZoneInfo("Europe/Istanbul")


def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def nightly():
    """Run the nightly job, but never two at once (e.g. scheduler + a manual 'once')."""
    lock_path = os.path.join(os.path.dirname(db.DB_PATH), "nightly.lock")
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another run is in progress, skipping")
            return
        _nightly()


def _nightly():
    """Collect new comments, analyze them, then apply the 30-day rule.
    Each stage runs even if an earlier one failed, so the 30-day rule always applies."""
    with db.connect() as conn:
        run_id = conn.execute(
            "INSERT INTO runs(started_at) VALUES(?)", (db.now_iso(),)
        ).lastrowid
    r = {"fetched": 0, "quota_units": 0, "analyzed": 0, "new_topics": 0, "purged": 0}
    errors = []
    try:
        with db.connect() as conn:
            r["fetched"], r["quota_units"] = collector.collect(conn)
    except Exception as exc:
        errors.append(f"collect: {exc}")
    try:
        with db.connect() as conn:
            r["analyzed"], r["new_topics"] = analyzer.analyze(conn)
    except Exception as exc:
        errors.append(f"analyze: {exc}")
    try:
        with db.connect() as conn:
            r["purged"] = db.purge_old(conn)
    except Exception as exc:
        errors.append(f"purge: {exc}")
    status, message = ("error" if errors else "ok"), " | ".join(errors)[:500]
    with db.connect() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, fetched=?, quota_units=?, analyzed=?, new_topics=?, "
            "purged=?, status=?, message=? WHERE id=?",
            (db.now_iso(), *r.values(), status, message, run_id),
        )
    log(f"run {run_id}: {status} " + " ".join(f"{k}={v}" for k, v in r.items()) + f" {message}")


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
