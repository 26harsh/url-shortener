"""
Celery tasks -- work that runs OUTSIDE the request/response cycle, in a
separate worker process.

record_click is the concrete example here: incrementing a click counter
is fast on its own (a single Redis INCR), but "fast" still isn't "free" --
calling it directly inside the redirect view means the HTTP response
can't be sent until that Redis round trip completes. Dispatching it as a
Celery task means the view fires the task and returns the redirect
immediately; the increment happens in the worker process, fully
decoupled from the request.
"""

from celery import shared_task
from django.core.cache import cache
from django.db import transaction, models
from django_redis import get_redis_connection
from shortener.models import ShortURL

CACHE_KEY_PREFIX = "shorturl"


@shared_task
def record_click(short_code: str) -> None:
    """
    Runs in a Celery worker process, not in the web process that handled
    the redirect. Same Redis-counter approach as before (cheap, in-memory
    increment); flush_click_counts still periodically batches these into
    Postgres.
    """
    counter_key = f"{CACHE_KEY_PREFIX}:clicks:{short_code}"
    if cache.get(counter_key) is not None:
        cache.incr(counter_key)
    else:
        cache.set(counter_key, 1, timeout=None)

@shared_task
def flush_click_counts_task():
    """
    Periodic task (see CELERY_BEAT_SCHEDULE in settings.py) -- batches
    Redis click counters into Postgres on a schedule, replacing the need
    to run the flush_click_counts management command manually.
    """
    redis_conn = get_redis_connection("default")
    pattern = f"*{CACHE_KEY_PREFIX}:clicks:*"
    keys = redis_conn.keys(pattern)

    flushed = 0
    with transaction.atomic():
        for raw_key in keys:
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            short_code = key.split(":")[-1]

            raw_value = redis_conn.get(raw_key)
            if not raw_value:
                continue
            count = int(raw_value)

            ShortURL.objects.filter(short_code=short_code).update(
                clicks=models.F('clicks') + count
            )
            redis_conn.delete(raw_key)
            flushed += 1

    return f"Flushed {flushed} short URL(s)."

