# ChannelBot

![Test & deploy](https://github.com/magusch/ChannelBot/workflows/Basic%20CI/badge.svg)
[![CodeFactor](https://www.codefactor.io/repository/github/magusch/channelbot/badge?s=2dddd084faca7dfc56c595e695a9ecf05d98207c)](https://www.codefactor.io/repository/github/magusch/channelbot)

Backend platform that automates scraping, AI processing, scoring and publishing of city
events. It started life as a Telegram bot, but today it is primarily a **FastAPI + Celery
service**: a REST API for events, places, users, search and content generation, backed by
a nightly automation pipeline. Telegram and VK are now just two of the publishing channels.

Target cities: Saint Petersburg / Kazan (configured via `settings.json`).

## What's inside

- **FastAPI** REST API — auth (JWT + Telegram WebApp), events, users/favorites, places,
  full-text + semantic search, content generator, image uploads, on-demand task triggers.
- **Celery + Redis** — nightly pipeline (scrape → score → promote → moderate → prepare →
  embed → distribute → publish) plus on-demand tasks.
- **AI layer** — OpenAI, Anthropic (Claude) and Gemini for event extraction, moderation,
  text preparation and embeddings/semantic search (pgvector).
- **PostgreSQL** — events, places, users, content-generator data, scoring history.
- **S3-compatible storage** — event images.
- **Publishing** — Telegram and VK channels.

## Requirements

- Python 3.12+
- PostgreSQL (with the `pgvector` extension for semantic search)
- Redis 6.2+

## Installation & running

The project runs via Docker. A full local run without Docker is impractical (Redis, Celery
worker, Celery beat all need to be up).

```bash
# Build
docker-compose build

# Start all services (API + Worker + Beat + Redis)
docker-compose up -d

# Rebuild after changes
docker-compose up -d --build

# Logs
docker-compose logs -f celery_worker
docker-compose logs -f celery_beat

# Tests only
docker-compose -f docker-compose.test.yml run pytest
```

The Dockerfile uses the `SERVICE` env var to pick the process:
- `fastapi_app` — uvicorn on port 8005
- `celery_worker` — Celery worker
- `celery_beat` — Celery beat scheduler
- `pytest` — run tests

### Local development (without Docker)

```bash
pip install --upgrade pip
pip install pytest autoflake black isort -e .
# or
make install
```

You need a running PostgreSQL (Redis can come from Docker). Start components manually:

```bash
uvicorn main:app --host 0.0.0.0 --port 8005 --reload
celery -A davai_s_nami_bot.celery_app worker --loglevel=info
celery -A davai_s_nami_bot.celery_app beat --loglevel=info
```

## Environment variables

**Required**

| Variable | Description |
|---|---|
| `DSN_DATABASE_URL` | PostgreSQL connection string |
| `CELERY_BROKER_URL` | Redis URL for the Celery broker (default `redis://localhost:6379/0`) |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery results (default `redis://localhost:6379/0`) |
| `REDIS_HOST` | Redis host (default `localhost`) |
| `API_TOKEN` | Bearer token for API authorization |
| `SECRET_KEY` | JWT secret for user authentication |

**AI providers**

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic (Claude) API key |
| `GEMINI_API` | Google Gemini API key (used for embeddings / moderation) |

**Telegram / VK**

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `CHANNEL_ID` | Main Telegram channel ID |
| `DEV_CHANNEL_ID` | Dev Telegram channel ID |
| `VK_TOKEN` | VKontakte token |
| `VK_GROUP_ID` | VK group ID for posting |

**AWS S3 (image storage)**

| Variable | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_STORAGE_BUCKET_NAME` | Bucket name |
| `AWS_S3_ENDPOINT_URL` | Endpoint URL |
| `AWS_S3_PUBLIC_URL` | Public URL for file access |
| `AWS_REGION` | AWS region (default `us-east-1`) |

**Configuration**

| Variable | Description |
|---|---|
| `CONFIG_PATH` | Path to the settings file (default `settings.json`) |

## Automated pipeline (Celery Beat)

Times are in MSK (`Europe/Moscow`). The order of the nightly chain matters — each stage
sees the result of the previous one on the same day.

| Task | Time (MSK) | Condition | What it does |
|---|---|---|---|
| `full_update` | 04:40 | always | Scrape sources → NotApproved + approved-orgs straight into Events2Posts |
| `update_adaptive_scoring` | 03:00 | always | Recompute scoring weights from posted/rejected history |
| `auto_promote_by_score` | 05:00 | always | NotApproved.score ≥ 70 → Events2Posts (`is_ready=NULL`) |
| `auto_moderate_mid_score_events` | 05:10 (Mon/Wed/Fri) | always | AI-moderate score 40–69; low scores → rejected |
| `auto_route_to_api` | 05:15 | `auto_route_to_api.enabled` | Low-priority ReadyToPost → `OnlyApi` (off the channel queue, still in API) |
| `route_unschedulable_events` | 05:20 | `route_unschedulable.enabled` | ReadyToPost that can't fit the schedule before `to_date` → `OnlyApi` |
| `prepare_unprepared_events` | 05:25 | `prepare_events_limit > 0` | AI text preparation for `is_ready=NULL` events |
| `embed_unembedded_events` | 05:45 | always | Build embeddings for fresh events |
| `distribute_event_queue` | 06:00 | always | Rebalance the publish `queue` by urgency / category diversity |
| `catch_up_daily_tasks` | 06:30–17:30 hourly | always | Re-run any nightly stage that was missed |
| `process_reminders` | every 30 min | always | Reminders for users' favorite events |
| `schedule_posting_tasks` | every 5 min | `task_event_post = true` | Individual post scheduler |
| `schedule_generated_posting_tasks` | every 30 min | `task_digest_post = true` | Digest / generated-post scheduler |

`task_event_post` and `task_digest_post` are mutually exclusive.

### Event processing flow

```
Sources (timepad, radario, qtickets, ticketscloud, mts, kassir, afisha, yandex, culture, vk, telegram, cfg)
    ↓ full_update → update_events (scraper rotation by weekday)
EventsNotApproved (status: new, score computed)
    ├─ score >= 70 → auto_promote → Events2Posts (ReadyToPost, is_ready=NULL)
    ├─ score 40-69 → AI moderation → approved → Events2Posts
    └─ score < 40  → auto reject
Events2Posts (ReadyToPost, is_ready=NULL)
    ↓ prepare_unprepared_events (AI text prep)
Events2Posts (ReadyToPost, is_ready=True)
    ↓ distribute_event_queue (diversity / urgency)
    ↓ schedule_posting_tasks → post_to_telegram
Events2Posts (status: Posted)
```

Side branches: low-priority or unschedulable events are routed to `OnlyApi` — they stay
available through the API but never hit the channel. Expired events that the AI never
prepared end up as `Expired`.

## Configuration (settings.json)

```json
{
  "celery": {
    "worker_enabled": true,
    "beat_enabled": true
  },
  "features": {
    "task_event_post": true,
    "task_digest_post": false,
    "prepare_events_limit": 5,
    "city": "spb",
    "timezone": "Europe/Moscow",
    "escraper_parameters": {
      "timepad": {"city": "Санкт-Петербург", "days": 12},
      "radario": {"city": "spb"},
      "ticketscloud": {"city": "spb", "use_proxy": false},
      "culture": {"enabled": false}
    }
  }
}
```

Key parameters:
- `task_event_post` / `task_digest_post` — posting mode (mutually exclusive)
- `prepare_events_limit` — AI prep limit per night (0 = disabled)
- `auto_route_to_api` / `route_unschedulable` — channel-bypass routing to `OnlyApi`
- `escraper_parameters.*.enabled` — enable/disable a scraper
- `escraper_parameters.*.days` — scrape depth in days (overrides default 7)
- `escraper_parameters.*.use_proxy` — use the proxy
- `escraper_parameters.*.timeout_sec` — wall-clock timeout per scraper run (default 300)

## API

All requests except `/api/auth/*` require an `Authorization: Bearer <API_TOKEN>` header.

Task endpoints return a `task_id` — poll its status via `GET /api/tasks/status/{task_id}`.

### Authentication (`/api/auth/`)

| Method | URL | Description |
|---|---|---|
| POST | `/register` | Register |
| POST | `/login` | Login (username/password → JWT) |
| POST | `/refresh` | Refresh token |
| GET | `/me` | Current user |
| PUT | `/me` | Update profile |
| POST | `/telegram/login` | Auth via Telegram WebApp |

### Users (`/api/users/`)

| Method | URL | Description |
|---|---|---|
| POST | `/me/events/{event_id}` | Add to favorites |
| DELETE | `/me/events/{event_id}` | Remove from favorites |
| GET | `/me/events` | List favorites |

### Events (`/api/events/`)

| Method | URL | Description |
|---|---|---|
| GET | `/{event_id}` | Event by ID |
| POST | `/valid/` | List events (filters, 10 min cache) |
| POST | `/valid/{event_id}` | Event by ID (cached) |

### Tasks (`/api/tasks/`)

| Method | URL | Description |
|---|---|---|
| GET | `/status/{task_id}` | Celery task status |
| DELETE | `/{task_id}` | Cancel (revoke) a task |
| POST | `/schedule-full-update/` | Full update (scraping) |
| POST | `/schedule-update-events/` | Update events |
| POST | `/get-event-from-url/` | Fetch an event by URL |
| POST | `/param/` | Update parameters |
| GET | `/check-ai-balance/` | Check AI balance |
| POST | `/get-exhibitions/` | Get exhibitions |
| POST | `/recalculate-scores/` | Recompute event scores |
| POST | `/update-adaptive-scoring/` | Recompute adaptive scoring |
| POST | `/auto-promote-by-score/` | Promote score ≥ 70 into Events2Posts |
| POST | `/distribute-event-queue/` | Reorder the publish queue |
| POST | `/prepare-unprepared-events/` | AI text preparation |
| POST | `/auto-moderate-mid-score/` | AI moderation for score 40–69 |
| GET | `/adaptive-scoring/` | Current adaptive weights |

### AI (`/api/ai/`)

| Method | URL | Description |
|---|---|---|
| POST | `/update-event/` | Update an event via AI |
| POST | `/moderate-events/` | Moderate a list of events |
| POST | `/moderate-not-approved-events/` | Moderate unprocessed events |
| POST | `/prepare-events/` | Prepare event texts |
| POST | `/new-event-from-sites/` | Scrape from given sites |

### Images (`/api/images/`)

| Method | URL | Description |
|---|---|---|
| POST | `/upload-to-s3/` | Upload an image to S3 |
| POST | `/upload-event-images-to-s3/` | Upload event images |

### Content generator (`/api/content-generator/`)

| Method | URL | Description |
|---|---|---|
| POST | `/event-selection/` | Select events by filter |
| POST | `/generate-post/` | Generate a post |
| POST | `/generate-post-ai/` | Generate a post via AI |

### Search & places

| Method | URL | Description |
|---|---|---|
| GET | `/api/search/?query=...&type=event&limit=10` | Search events / places |
| POST | `/api/places/` | List places |
| POST | `/api/places/{place_id}` | Place by ID |

### Usage example

```bash
TOKEN="your-api-token"
BASE="http://localhost:8005/api"

# Trigger scraping from timepad
curl -X POST "$BASE/ai/new-event-from-sites/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sites": ["timepad"], "days": 7}'

# Poll task status
curl "$BASE/tasks/status/{task_id}" -H "Authorization: Bearer $TOKEN"

# Fetch events
curl -X POST "$BASE/events/valid/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit": 10, "page": 1}'

# Run auto-promote
curl -X POST "$BASE/tasks/auto-promote-by-score/" \
  -H "Authorization: Bearer $TOKEN"

# Inspect adaptive scoring
curl "$BASE/tasks/adaptive-scoring/" -H "Authorization: Bearer $TOKEN"
```

## Database migrations (Alembic)

```bash
alembic revision --autogenerate -m "description"   # create
alembic upgrade head                                # apply all
alembic downgrade -1                                # roll back one
alembic current                                     # current revision
```

The URL is taken from `DSN_DATABASE_URL`.

## Testing

```bash
pytest --verbose
# or
make test
```

Tests run against SQLite in-memory + `fakeredis` (no real PostgreSQL/Redis needed).

## Linters

```bash
make lint_inplace   # auto-format
make lint_check     # check only
```

- **black** (line-length=89)
- **isort** (project=davai_s_nami_bot)
- **autoflake** (remove unused imports)

## Deploy

```bash
make deploy
```
