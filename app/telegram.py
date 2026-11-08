"""Optional Telegram bot: a short morning report and Approve/Reject buttons.

Talks only to TELEGRAM_CHAT_ID; everyone else is ignored. Messages contain
topic titles and numbers only, never commenter names or comment text.
"""
import os
import time

import requests

from app import db

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DOMAIN = os.environ.get("DOMAIN", "")
MAX_BUTTONS = 10   # pending topics sent with buttons per report


def enabled():
    return bool(TOKEN and CHAT_ID)


def api(method, **params):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/{method}", json=params, timeout=70
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        # Never log the exception text: the URL contains the bot token.
        raise RuntimeError(f"Telegram {method}: network error ({type(exc).__name__})") from None
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description', 'error')}")
    return data["result"]


def _buttons(topic_id):
    return {"inline_keyboard": [[
        {"text": "Onayla", "callback_data": f"approved:{topic_id}"},
        {"text": "Reddet", "callback_data": f"rejected:{topic_id}"},
    ]]}


def send_report():
    """Morning report: last night's numbers, then new pending topics with buttons."""
    with db.connect() as conn:
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        pending = conn.execute(
            "SELECT t.id, t.title, (SELECT COUNT(*) FROM topic_comments tc WHERE tc.topic_id = t.id) AS n "
            "FROM topics t WHERE kind = 'request' AND status = 'pending' "
            "ORDER BY n DESC, t.id DESC"
        ).fetchall()
        questions = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE status = 'open'"
        ).fetchone()[0]
        top = conn.execute(
            "SELECT t.title, (SELECT COUNT(*) FROM votes v WHERE v.topic_id = t.id) AS votes "
            "FROM topics t WHERE kind = 'request' AND status = 'approved' "
            "ORDER BY votes DESC LIMIT 1"
        ).fetchone()
        last_report = db.get_state(conn, "telegram_last_report", "")
        db.set_state(conn, "telegram_last_report", db.now_iso())

    lines = ["Günaydın, Mutfak'tan sabah raporu."]
    if run:
        lines.append(f"Dün gece {run['fetched']} yeni yorum toplandı, {run['new_topics']} yeni konu çıktı.")
        if run["status"] == "error":
            lines.append(f"Gece çalışmasında hata var: {run['message'][:200]}")
    lines.append(f"Onay bekleyen konu: {len(pending)}")
    lines.append(f"Cevap bekleyen soru: {questions}")
    if top and top["votes"]:
        lines.append(f"Panoda en çok oy alan: {top['title']} ({top['votes']} oy)")
    if DOMAIN:
        lines.append(f"Panel: https://{DOMAIN}/panel")
    api("sendMessage", chat_id=CHAT_ID, text="\n".join(lines))

    # Buttons only for topics that are new since the last report (or all, the first time).
    with db.connect() as conn:
        fresh = [
            t for t in pending
            if not last_report or conn.execute(
                "SELECT created_at > ? FROM topics WHERE id = ?", (last_report, t["id"])
            ).fetchone()[0]
        ]
    for t in fresh[:MAX_BUTTONS]:
        api("sendMessage", chat_id=CHAT_ID, text=f"{t['title']}\n{t['n']} yorumda geçti",
            reply_markup=_buttons(t["id"]))
    if len(fresh) > MAX_BUTTONS:
        api("sendMessage", chat_id=CHAT_ID,
            text=f"{len(fresh) - MAX_BUTTONS} yeni konu daha panelde onay bekliyor.")


def _handle(update):
    cb = update.get("callback_query")
    if cb:
        chat = str((cb.get("message") or {}).get("chat", {}).get("id", ""))
        if chat != CHAT_ID or str(cb["from"]["id"]) != CHAT_ID:
            return   # not the owner: no answer at all
        status, _, topic_id = cb.get("data", "").partition(":")
        with db.connect() as conn:
            changed = topic_id.isdigit() and db.set_topic_status(conn, int(topic_id), status)
            row = conn.execute("SELECT title FROM topics WHERE id = ?",
                               (int(topic_id) if topic_id.isdigit() else -1,)).fetchone()
        word = {"approved": "Onaylandı, panoda", "rejected": "Reddedildi"}.get(status, "")
        api("answerCallbackQuery", callback_query_id=cb["id"],
            text=word if changed else "Bu konu bulunamadı.")
        if changed and row:
            api("editMessageText", chat_id=CHAT_ID, message_id=cb["message"]["message_id"],
                text=f"{word}: {row['title']}")
        return
    msg = update.get("message") or {}
    if str(msg.get("chat", {}).get("id", "")) != CHAT_ID:
        return   # strangers get no reply
    if (msg.get("text") or "").strip().startswith("/rapor"):
        send_report()
    else:
        api("sendMessage", chat_id=CHAT_ID,
            text="Raporu şimdi görmek için /rapor yazın. Onay düğmeleri sabah raporuyla gelir.")


def poll_forever(log):
    """Long-poll Telegram for button presses and commands (no webhook needed)."""
    offset = None
    while True:
        try:
            updates = api("getUpdates", timeout=50, offset=offset,
                          allowed_updates=["message", "callback_query"])
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    _handle(update)
                except Exception as exc:
                    log(f"telegram: {exc}")
        except Exception as exc:
            log(f"telegram: {exc}")
            time.sleep(15)
