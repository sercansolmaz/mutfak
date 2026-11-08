"""Flask web app: public board (/mutfak) and private panel (/panel)."""
from flask import Flask, redirect

from app import db

app = Flask(__name__)
db.init()


@app.get("/")
def index():
    return redirect("/mutfak")


@app.get("/mutfak")
def board():
    return "Mutfak hazırlanıyor."


@app.get("/healthz")
def healthz():
    with db.connect() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}
