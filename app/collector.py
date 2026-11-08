"""Fetch new comments for the whole channel from YouTube Data API v3.

Uses commentThreads.list with allThreadsRelatedToChannelId: one request
(1 quota unit) returns up to 100 threads across all videos, each with a few
replies included at no extra cost. We walk pages newest-first and stop as
soon as we reach comments we have already seen.
"""
import os
from datetime import datetime, timedelta, timezone

import requests

from app import db

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
MAX_PAGES = 50          # hard cap per run (= max 50 quota units)
OVERLAP = timedelta(hours=1)


class YouTubeError(Exception):
    pass


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _fetch_page(api_key, channel_id, page_token=None):
    params = {
        "part": "snippet,replies",
        "allThreadsRelatedToChannelId": channel_id,
        "maxResults": 100,
        "order": "time",
        "textFormat": "plainText",
        "key": api_key,
    }
    if page_token:
        params["pageToken"] = page_token
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        # Never include the exception text: it can contain the URL with the key.
        raise YouTubeError(f"network error ({type(exc).__name__})") from None
    if resp.status_code != 200:
        try:
            msg = resp.json()["error"]["message"]
        except Exception:
            msg = "unknown error"
        raise YouTubeError(f"HTTP {resp.status_code}: {msg}")
    return resp.json()


def _comment_row(c, video_id, parent_id=None):
    s = c["snippet"]
    return {
        "id": c["id"],
        "video_id": video_id,
        "parent_id": parent_id,
        "author": s.get("authorDisplayName", ""),
        "author_channel": s.get("authorChannelId", {}).get("value", ""),
        "text": s.get("textDisplay", ""),
        "published_at": s["publishedAt"][:19] + "Z",
    }


def collect(conn):
    """Store new comments. Returns (new_comment_count, quota_units_used)."""
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID", "")
    if not api_key or not channel_id:
        raise YouTubeError("YOUTUBE_API_KEY or YOUTUBE_CHANNEL_ID is missing in .env")

    now = datetime.now(timezone.utc)
    oldest_allowed = now - timedelta(days=db.RETENTION_DAYS)
    last_seen = db.get_state(conn, "last_seen")
    # First run: go back 30 days. Later runs: only what is newer than last time.
    stop_before = max(_parse(last_seen) - OVERLAP, oldest_allowed) if last_seen else oldest_allowed

    new, units, page_token, newest = 0, 0, None, last_seen
    while units < MAX_PAGES:
        data = _fetch_page(api_key, channel_id, page_token)
        units += 1
        reached_old = False

        for thread in data.get("items", []):
            video_id = thread["snippet"].get("videoId", "")
            top = _comment_row(thread["snippet"]["topLevelComment"], video_id)
            rows = [top] + [
                _comment_row(r, video_id, parent_id=top["id"])
                for r in thread.get("replies", {}).get("comments", [])
            ]
            if max(_parse(r["published_at"]) for r in rows) < stop_before:
                reached_old = True
                break
            for r in rows:
                if r["author_channel"] == channel_id:   # skip the channel owner
                    continue
                if _parse(r["published_at"]) < oldest_allowed:
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO comments(id, video_id, parent_id, author, text, published_at) "
                    "VALUES(:id, :video_id, :parent_id, :author, :text, :published_at)",
                    r,
                )
                new += cur.rowcount
                if newest is None or r["published_at"] > newest:
                    newest = r["published_at"]

        page_token = data.get("nextPageToken")
        if reached_old or not page_token:
            break

    if newest:
        db.set_state(conn, "last_seen", newest)
    return new, units
