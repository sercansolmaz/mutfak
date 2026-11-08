# Mutfak

*Türkçe: [README.tr.md](README.tr.md)*

Mutfak ("the kitchen") collects your YouTube channel's new comments every night, turns them into
insights with an LLM, and lets your audience vote on the video topics you approve. It runs on your
own server with one command.

If your channel is the shop, this is the kitchen where viewers' orders are prepared.

## What it does

1. **Collector**: every night at 03:00 (Europe/Istanbul) it fetches new comments for the whole
   channel with the YouTube Data API v3. It needs only an API key, no OAuth. A normal night costs
   about 1 quota unit out of the free 10,000.
2. **Analysis**: an LLM via [OpenRouter](https://openrouter.ai) (default
   `deepseek/deepseek-v4.1-flash`, configurable) groups topic requests, finds questions waiting for
   your answer, and spots recurring criticism and the news and products viewers mention. Product,
   company and model names are written out on the cards.
3. **Private panel** (`/panel`, password protected): insight cards, open questions and the approval
   queue. Nothing found by the system is published until you approve it.
4. **Public request board** (`/mutfak`): your approved topics as kitchen order tickets, and visitor
   votes. Visitors can only vote.
5. **Telegram bot** (optional): a short morning report with Approve and Reject buttons. It answers
   only you.

```
YouTube API ──> collector ──> SQLite <── analysis ──> OpenRouter
                                 │
           ┌─────────────────────┼─────────────────────┐
     private panel        public board           Telegram bot
       (/panel)             (/mutfak)          (report + buttons)
```

## Privacy and safety

- **YouTube's 30-day rule:** every night, comment text and author names older than 30 days are
  deleted. Topics and counts stay.
- **Author names never reach the LLM.** Comments are sent with short ids only, and `@mentions` are
  masked.
- **Prompt injection:** comments are sent as JSON data, and the system prompt says they are data,
  never instructions. The model has no tools. Its JSON answer is validated: unknown ids and kinds,
  links and over-long text are dropped, and nothing is published automatically.
- **The public board** shows no commenter names, no comment text and no numbers computed from
  comments. Only visitor votes are counted.
- **Votes:** one vote per visitor cookie, and at most 20 per topic from one IP address. IPs are
  stored only as a keyed hash. A second tap takes the vote back.
- **Telegram messages** contain topic titles and numbers only.
- **Third-party requests:** none for visitors. The font
  ([Recursive](https://github.com/arrowtype/recursive), OFL) is served from your server.

## Setup

You need a Linux server with Docker and Docker Compose, a domain (or subdomain) and these keys:

| Key | Where to get it |
|---|---|
| `YOUTUBE_API_KEY` | Google Cloud Console → APIs & Services → Credentials. Restrict it to "YouTube Data API v3". |
| `YOUTUBE_CHANNEL_ID` | YouTube Studio → Settings → Channel → Advanced settings (starts with `UC`) |
| `OPENROUTER_API_KEY` | https://openrouter.ai/keys |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional. Create a bot with @BotFather; your chat id from @userinfobot |

```sh
git clone <this repo> mutfak && cd mutfak
cp .env.example .env && chmod 600 .env
# fill in .env (each value is explained in Turkish), then:
docker compose up -d --build
```

Point an A record for your domain to the server first. Caddy gets the HTTPS certificate by itself.
Every service restarts automatically, also after a reboot.

The first run fetches the last 30 days of comments. After that, only new ones are fetched.

### Useful commands

```sh
docker compose exec worker python -m app.worker once     # run the nightly job now
docker compose exec worker python -m app.worker report   # send the Telegram report now
docker compose logs -f worker                            # watch the nightly job
```

### Settings (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `DOMAIN` | | Domain for the board and the panel |
| `PANEL_PASSWORD` | | Password for `/panel` |
| `SECRET_KEY` | | Long random value for cookies and IP hashing |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4.1-flash` | Any OpenRouter model id |
| `RUN_AT` | `03:00` | Nightly job time (Europe/Istanbul) |
| `REPORT_AT` | `09:00` | Telegram morning report time |

## Project layout

```
app/
  collector.py   YouTube fetching
  analyzer.py    OpenRouter call, prompt and output validation
  db.py          SQLite schema and the 30-day rule
  telegram.py    report and approve/reject buttons
  worker.py      nightly schedule and the Telegram listener
  web.py         Flask: /mutfak, /panel
  templates/, static/
compose.yaml  Dockerfile  Caddyfile  .env.example
```

Three containers: `web` (Flask + gunicorn), `worker` (schedule + Telegram), `caddy` (HTTPS). Data
lives in a single SQLite file on the `data` volume.

## Running the coding agent as a separate, unprivileged user

This project was built with an AI coding agent (Claude Code) running as `root`, to keep the video
simple. For real use, don't do that.

**Why:** an agent works with untrusted text. Web pages, API responses, and in this project YouTube
comments can all contain instructions. As root, a single mistake or a successful prompt injection
can read every secret on the machine, change system files or delete data. A separate user limits
the damage to what that user may touch.

**How:**

1. Create a user without sudo: `adduser --disabled-password agent`. Give it only the project
   folder: `chown -R agent: /srv/mutfak`.
2. Keep the secrets away from it. Make `.env` owned by your own user with `chmod 600`, so the agent
   can't read the keys. In Claude Code you can also add `"deny": ["Read(.env)"]` to the permissions
   in `.claude/settings.json`.
3. **Don't add the agent to the `docker` group.** Docker group membership is equivalent to root.
   Let the agent edit code and run tests; you run `docker compose up -d --build` yourself. Use
   rootless Docker if the agent must run containers.
4. Review the agent's commits before you deploy them.

## License

[MIT](LICENSE). The Recursive font is under the SIL Open Font License
([app/static/fonts/OFL.txt](app/static/fonts/OFL.txt)).
