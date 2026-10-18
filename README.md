# Twitter Monitor

Standalone Twitter/X image monitor, carved out of `onlinefabster/bot`.

Polls a configured set of watched Twitter accounts through the shared
[`webscraper`](https://github.com/onlinefabster/webscraper) service, downloads
new media and uploads each image to a self-hosted **Immich** server into an
album named `twitter/{username}` (with the username tagged on the photo's
description). Ships a web dashboard showing monitor status and the history of
downloaded images.

The scraping, URL-dedup and sha256-content-dedup behaviour is identical to the
original bot monitor — only the delivery target changed (Telegram → Immich), and
each uploaded image is archived locally on the data volume.

## Architecture

Wrapped into one container (FastAPI app + APScheduler worker):

- **`skills/twitter_image_monitor.py`** — poll loop: get image URLs from the
  webscraper, fetch bytes, sha256 dedup, upload to Immich, archive locally.
- **`clients/immich_client.py`** — Immich REST client (album ensure + asset
  upload + description tagging).
- **`clients/web_agent_client.py`** — client for the webscraper
  `/scrape/twitter/media` endpoint.
- **`services/twitter_db.py`** — SQLite DB on the data volume
  (`twitter_monitor.db`): watches, seen URLs, signatures, uploads, run history.
- **`app/`** — FastAPI app: control/status API + static dashboard.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set IMMICH_BASE_URL / IMMICH_API_KEY, TWITTER_SCRAPER_BASE_URL
uvicorn app.main:app --reload --port 8081
```

Scraper note (same caveat as webscraper): Twitter scraping needs the real,
authenticated `TWITTER_SESSION_FILE` on the webscraper — the monitor itself
cannot be integration-tested without a live browser session.

## Commands

```bash
# Add / list / remove watched accounts and trigger a run via the API
curl -X POST localhost:8081/api/watch -H 'Content-Type: application/json' -d '{"username":"@someone"}'
curl localhost:8081/api/status
curl -X POST localhost:8081/api/poll-now

# Migrate the account list from the old bot DB (does NOT copy seen/signatures)
python tools/migrate_db.py --src /path/to/schedules.db

# Smoke test Immich connectivity (scratch account only!)
python tools/test_immich.py
```

## Deploy

```bash
docker compose up -d --pull always
curl http://127.0.0.1:18055/health
```

Runtime data lives under `/docker/twitter-monitor/data` on the host (DB +
`archive/twitter/{username}/` images). Image is built by GitHub Actions on push
to `main` and published to `ghcr.io/onlinefabster/twitter-monitor:latest`.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `TWITTER_SCRAPER_BASE_URL` | `http://ser:18023` | webscraper service |
| `IMMICH_BASE_URL` | `http://immich:2283` | Immich server |
| `IMMICH_API_KEY` | — | Immich API key (required) |
| `MONITOR_CRON` | `*/30 * * * *` | poll schedule |
| `TWITTER_MAX_PER_ACCOUNT` | `10` | max uploads per account per run |
| `TWITTER_IMAGE_FETCH_TIMEOUT` | `30` | image download timeout (s) |
| `DB_PATH` | `/app/data/twitter-monitor.db` | sqlite db |
| `ARCHIVE_DIR` | `/app/data/archive` | local image archive (dashboard) |
| `TZ` | `Europe/Amsterdam` | scheduler timezone |