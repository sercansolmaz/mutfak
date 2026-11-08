"""Flask web app: public request board (/mutfak) and private panel (/panel)."""
import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from app import db

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY must be set in .env (at least 32 characters)")
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")

VOTES_PER_IP = 20               # max votes per topic from one IP address
VOTER_COOKIE = "mutfak_oy"
THEME_COOKIE = "tema"
LOGIN_LIMIT, LOGIN_WINDOW = 5, 15 * 60   # 5 wrong passwords per 15 minutes per IP

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # behind Caddy
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=14 * 24 * 3600,
)
db.init()
_failed_logins = defaultdict(list)


# ── helpers ────────────────────────────────────────────

def ip_hash():
    """Votes store a keyed hash of the IP address, never the address itself."""
    ip = request.remote_addr or ""
    return hmac.new(SECRET_KEY.encode(), ip.encode(), hashlib.sha256).hexdigest()


def same_origin():
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    return re.match(rf"^https?://{re.escape(request.host)}(/|$)", origin) is not None


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("panel"):
            return redirect(url_for("login"))
        if request.method == "POST" and not hmac.compare_digest(
            request.form.get("csrf", ""), session.get("csrf", "")
        ):
            abort(400)
        return view(*args, **kwargs)
    return wrapper


@app.context_processor
def template_globals():
    theme = request.cookies.get(THEME_COOKIE)
    return {
        "theme": theme if theme in ("light", "dark") else "",
        "csrf_token": csrf_token,
        "channel_url": f"https://www.youtube.com/channel/{CHANNEL_ID}" if CHANNEL_ID else "",
    }


TZ = ZoneInfo("Europe/Istanbul")
MONTHS = "Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık".split()


def _local(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)


@app.template_filter("local_date")
def local_date(ts):
    d = _local(ts)
    return f"{d.day} {MONTHS[d.month - 1]}"


@app.template_filter("local_datetime")
def local_datetime(ts):
    d = _local(ts)
    return f"{d.day} {MONTHS[d.month - 1]}, {d:%H:%M}"


@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


# ── public board ───────────────────────────────────────

@app.get("/")
def index():
    return redirect(url_for("board"))


@app.get("/mutfak")
def board():
    voter = request.cookies.get(VOTER_COOKIE, "")
    with db.connect() as conn:
        # Only approved requests and visitor votes. No comment text, no comment counts.
        topics = conn.execute(
            "SELECT t.id, t.title, t.summary, "
            "(SELECT COUNT(*) FROM votes v WHERE v.topic_id = t.id) AS votes "
            "FROM topics t WHERE t.kind = 'request' AND t.status = 'approved' "
            "ORDER BY votes DESC, t.updated_at DESC"
        ).fetchall()
        mine = {r["topic_id"] for r in conn.execute(
            "SELECT topic_id FROM votes WHERE voter_id = ?", (voter,)
        )}
    return render_template("board.html", topics=topics, mine=mine)


@app.post("/mutfak/oy/<int:topic_id>")
def vote(topic_id):
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    if not is_fetch and not same_origin():
        abort(403)
    voter = request.cookies.get(VOTER_COOKIE, "")
    new_voter = not re.fullmatch(r"[0-9a-f]{32}", voter)
    if new_voter:
        voter = secrets.token_hex(16)

    error = None
    with db.connect() as conn:
        topic = conn.execute(
            "SELECT id FROM topics WHERE id = ? AND kind = 'request' AND status = 'approved'",
            (topic_id,),
        ).fetchone()
        if not topic:
            abort(404)
        deleted = conn.execute(
            "DELETE FROM votes WHERE topic_id = ? AND voter_id = ?", (topic_id, voter)
        ).rowcount
        voted = False
        if not deleted:   # a second tap takes the vote back
            from_ip = conn.execute(
                "SELECT COUNT(*) FROM votes WHERE topic_id = ? AND ip_hash = ?",
                (topic_id, ip_hash()),
            ).fetchone()[0]
            if from_ip >= VOTES_PER_IP:
                error = "Bu ağdan bu konuya verilebilecek oy sınırı doldu."
            else:
                conn.execute(
                    "INSERT INTO votes(topic_id, voter_id, ip_hash, created_at) VALUES(?,?,?,?)",
                    (topic_id, voter, ip_hash(), db.now_iso()),
                )
                voted = True
        count = conn.execute(
            "SELECT COUNT(*) FROM votes WHERE topic_id = ?", (topic_id,)
        ).fetchone()[0]

    if is_fetch:
        resp = jsonify(voted=voted, count=count, error=error)
        if error:
            resp.status_code = 429
    else:
        resp = redirect(url_for("board") + f"#siparis-{topic_id}")
    if new_voter:
        resp.set_cookie(VOTER_COOKIE, voter, max_age=400 * 24 * 3600,
                        secure=True, httponly=True, samesite="Lax")
    return resp


# ── private panel ──────────────────────────────────────

@app.route("/giris", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = request.remote_addr or ""
        now = time.time()
        _failed_logins[ip] = [t for t in _failed_logins[ip] if now - t < LOGIN_WINDOW]
        if not PANEL_PASSWORD:
            error = "Panel şifresi .env dosyasında tanımlı değil."
        elif len(_failed_logins[ip]) >= LOGIN_LIMIT:
            error = "Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin."
        elif hmac.compare_digest(request.form.get("password", "").encode(), PANEL_PASSWORD.encode()):
            session.clear()
            session.permanent = True
            session["panel"] = True
            return redirect(url_for("panel"))
        else:
            _failed_logins[ip].append(now)
            error = "Şifre yanlış."
    return render_template("login.html", error=error), (401 if error else 200)


@app.post("/cikis")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


TOPIC_COLUMNS = (
    "SELECT t.*, "
    "(SELECT COUNT(*) FROM topic_comments tc WHERE tc.topic_id = t.id) AS mentions, "
    "(SELECT COUNT(*) FROM votes v WHERE v.topic_id = t.id) AS votes FROM topics t "
)


def panel_counts(conn):
    return {
        "queue": conn.execute(
            "SELECT COUNT(*) FROM topics WHERE kind = 'request' AND status = 'pending'"
        ).fetchone()[0],
        "questions": conn.execute(
            "SELECT COUNT(*) FROM questions WHERE status = 'open'"
        ).fetchone()[0],
    }


@app.get("/panel")
@login_required
def panel():
    with db.connect() as conn:
        pending = conn.execute(
            TOPIC_COLUMNS + "WHERE kind = 'request' AND status = 'pending' "
            "ORDER BY mentions DESC, updated_at DESC"
        ).fetchall()
        approved = conn.execute(
            TOPIC_COLUMNS + "WHERE kind = 'request' AND status = 'approved' ORDER BY votes DESC"
        ).fetchall()
        counts = panel_counts(conn)
    return render_template("panel.html", section="queue", pending=pending,
                           approved=approved, counts=counts)


@app.get("/panel/ongoruler")
@login_required
def insights():
    with db.connect() as conn:
        topics = conn.execute(
            TOPIC_COLUMNS + "WHERE kind IN ('criticism', 'news') AND status != 'rejected' "
            "ORDER BY mentions DESC, updated_at DESC"
        ).fetchall()
        counts = panel_counts(conn)
    return render_template("panel.html", section="insights", counts=counts,
                           criticism=[t for t in topics if t["kind"] == "criticism"],
                           news=[t for t in topics if t["kind"] == "news"])


@app.get("/panel/sorular")
@login_required
def questions():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT q.comment_id, q.summary, c.text, c.video_id, c.published_at "
            "FROM questions q JOIN comments c ON c.id = q.comment_id "
            "WHERE q.status = 'open' ORDER BY c.published_at DESC"
        ).fetchall()
        counts = panel_counts(conn)
    return render_template("panel.html", section="questions", questions=rows, counts=counts)


@app.get("/panel/rapor")
@login_required
def runs():
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 14").fetchall()
        counts = panel_counts(conn)
    return render_template("panel.html", section="runs", runs=rows, counts=counts)


BACK = {"queue": "panel", "insights": "insights"}


@app.post("/panel/konu/<int:topic_id>")
@login_required
def topic_status(topic_id):
    with db.connect() as conn:
        db.set_topic_status(
            conn, topic_id, request.form.get("status", ""),
            title=request.form.get("title"), summary=request.form.get("summary"),
        )
    return redirect(url_for(BACK.get(request.form.get("back"), "panel")))


@app.post("/panel/soru/<comment_id>")
@login_required
def question_done(comment_id):
    with db.connect() as conn:
        conn.execute("UPDATE questions SET status = 'done' WHERE comment_id = ?", (comment_id,))
    return redirect(url_for("questions"))


@app.get("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="favicon.svg"), 301)


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
def apple_touch_icon():
    return redirect(url_for("static", filename="apple-touch-icon.png"), 301)


@app.get("/healthz")
def healthz():
    with db.connect() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}
