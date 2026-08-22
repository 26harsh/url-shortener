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

