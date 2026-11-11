FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Istanbul

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Pre-baked historical analysis shown at /mutfak/arsiv (aggregate data only).
# web.py prefers /srv/data/archive_report.json; this is the fallback.
COPY archive_report.json /srv/archive_report.json.bundled

# Run as an unprivileged user; the data volume is owned by it.
RUN useradd --system --uid 10001 mutfak \
 && mkdir -p /srv/data \
 && chown mutfak /srv/data \
 && chown mutfak /srv/archive_report.json.bundled
USER mutfak

EXPOSE 8000

# Single-container mode (Coolify deploys one app): run the nightly/Telegram
# worker in the background (with restart-on-crash loop) and gunicorn in front.
CMD ["sh", "-c", "if [ ! -f /srv/data/archive_report.json ] && [ -f /srv/archive_report.json.bundled ]; then cp /srv/archive_report.json.bundled /srv/data/archive_report.json; fi; while true; do python -m app.worker; echo '[start] worker exited; restarting in 5s' >&2; sleep 5; done & exec gunicorn --bind 0.0.0.0:8000 --workers 2 --access-logfile - app.web:app"]
