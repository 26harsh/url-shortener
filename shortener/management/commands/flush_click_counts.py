"""
Flushes click counters accumulated in Redis into Postgres in a single
batch UPDATE per short_code, then clears the Redis counters.

Why this exists: the redirect view increments a Redis counter (cheap,
in-memory, no DB round trip) instead of running an UPDATE on the
ShortURL row on every single redirect. This command is meant to run on
a schedule (e.g. every minute via cron / a Celery beat task / a systemd
timer) to reconcile those counters into the durable database.

This is the concrete implementation of the "read-heavy vs write-heavy"
talking point: redirects (reads, high volume) never block on a DB write;
click totals (writes) are eventually consistent instead of immediately
consistent, which is an acceptable trade-off for an analytics counter.

Run manually:
    python manage.py flush_click_counts
"""

from django.core.management.base import BaseCommand
from django.db import transaction, models
from django_redis import get_redis_connection

from shortener.models import ShortURL
from shortener.services import CACHE_KEY_PREFIX


class Command(BaseCommand):
    help = "Flush Redis click counters into Postgres."

    def handle(self, *args, **options):
        redis_conn = get_redis_connection("default")
        # django-redis prefixes keys internally (e.g. ":1:shorturl:clicks:abc"),
        # so we search broadly and parse the short_code off the tail.
        pattern = f"*{CACHE_KEY_PREFIX}:clicks:*"
        keys = redis_conn.keys(pattern)

        if not keys:
            self.stdout.write("No pending click counts to flush.")
            return

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

        self.stdout.write(self.style.SUCCESS(f"Flushed click counts for {flushed} short URL(s)."))
