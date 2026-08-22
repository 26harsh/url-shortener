# URL Shortener — Django + Postgres + Redis

A production-shaped URL shortener built to demonstrate real system design
decisions: collision-free short code generation, an indexed hot read path,
a cache-aside strategy, and an async-friendly write path for click counts.

## Architecture

```
Client -> Django (Gunicorn) -> Redis (cache-aside) -> Postgres
                              ^ hot path: GET /<short_code>
```

- **Django + Postgres**: core service — models, hash generation, redirects
- **Redis (django-redis)**: cache-aside layer in front of the redirect lookup
- **Docker Compose**: local dev topology mirrors production (same containers,
  different `.env` values when deployed)

## Key design decisions

**Short code generation — base62(id), not hash(url).**
Hashing the long URL (e.g. `md5(url)[:7]`) has a real collision risk (see
the birthday paradox) and forces a check-before-insert + retry loop, which
introduces a race condition under concurrent writes. Instead, the code is
derived from the row's auto-incrementing primary key via base62 encoding —
a deterministic bijection, so two different rows can never produce the same
code. Zero collision handling required. See `shortener/services.py`.

**Indexing.** `short_code` is `unique=True` (which Postgres indexes
automatically) — this is the only field queried on the hot path
(`GET /<short_code>`), so it's the only index that matters for read latency.

**Caching strategy — cache-aside, read path only.**
`resolve_short_url()` checks Redis first; on a miss it reads Postgres and
populates the cache with a TTL (`SHORT_URL_CACHE_TTL`, default 1 hour).
Writes (`create_short_url`) do not populate the cache proactively — new
URLs are rarely visited immediately after creation, so warming the cache
on write would waste memory on a free-tier Redis instance for little gain.

**Read-heavy vs write-heavy: async click counting.**
Redirects vastly outnumber URL creations. Incrementing `clicks` in Postgres
synchronously on every redirect would put a write on the read hot path.
Instead, `record_click()` increments an in-memory Redis counter, and
`python manage.py flush_click_counts` (meant to run on a schedule) batches
those counters into Postgres periodically. Click counts are eventually
consistent by design.

## Project structure

```
url-shortener/
├── config/                   # Django project settings/urls/wsgi
├── shortener/
│   ├── models.py             # ShortURL model
│   ├── services.py           # base62 encode/decode, create/resolve/click logic
│   ├── views.py               # thin HTTP layer over services.py
│   ├── urls.py
│   ├── admin.py
│   ├── management/commands/flush_click_counts.py
│   └── tests/test_services.py
├── templates/shortener/home.html
├── docker-compose.yml         # postgres + redis + web
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

## Running locally (Docker)

Requires Docker Desktop running.

```bash
# 1. Copy env file (already pre-filled with working local defaults;
#    a .env with a generated SECRET_KEY is included for convenience)
cp .env.example .env   # only if you deleted the provided .env

# 2. Build and start everything
docker compose build
docker compose up -d

# 3. Run migrations
docker compose exec web python manage.py migrate

# 4. (Optional) create an admin user
docker compose exec web python manage.py createsuperuser

# 5. Open the app
# http://localhost:8000            <- shorten form (UI)
# http://localhost:8000/admin      <- Django admin
```

### Sanity checks

```bash
# Django up?
curl http://localhost:8000

# Postgres reachable from inside the web container?
docker compose exec web python manage.py dbshell   # \q to exit

# Redis reachable?
docker compose exec web python manage.py shell
>>> from django.core.cache import cache
>>> cache.set('test', 'hello'); cache.get('test')
'hello'
```

### Try the API

```bash
curl -X POST http://localhost:8000/api/shorten/ \
  -H "Content-Type: application/json" \
  -d '{"long_url": "https://example.com/some/very/long/path"}'

# -> {"short_code": "1", "short_url": "http://localhost:8000/1", ...}

curl -iL http://localhost:8000/1   # follow the redirect
```

### Run tests

```bash
docker compose exec web python manage.py test
```

### Flush click counters manually

```bash
docker compose exec web python manage.py flush_click_counts
```

In production this would run on a schedule (cron, systemd timer, or
Celery beat) rather than manually.

## Stopping / resetting

```bash
docker compose down          # stop containers, keep DB data
docker compose down -v       # stop containers AND wipe DB volume
```

## Deploying to AWS (free tier)

See the project roadmap — planned next steps:
1. AWS account + billing alarm ($1 threshold) + IAM user (not root)
2. RDS Postgres (db.t3.micro, free tier) replaces the `db` container
3. EC2 (t4g.micro, free tier) runs this same `Dockerfile` via
   `docker compose` (minus the local `db` service)
4. Nginx reverse proxy in front of Gunicorn (stands in for a load
   balancer on a single-instance free-tier deployment — ALB has no
   free tier)
5. Redis: either self-hosted on the same EC2 instance, or Upstash
   (managed, free tier, closer to how a real team would run it)

Nothing in the Django code changes for this move — only `.env` values
(`DB_HOST` -> RDS endpoint, `REDIS_HOST`/`REDIS_URL` -> Upstash or
on-box Redis).
