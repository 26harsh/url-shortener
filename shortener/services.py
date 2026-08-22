"""
Business logic, deliberately kept out of models.py and views.py.

Why: this is the part of the project that's actually interesting in an
interview (short-code generation/collision handling, cache-aside
strategy). Keeping it here, framework-agnostic and easily unit-testable,
is itself a design decision worth being able to explain.
"""

import secrets

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import ShortURL

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)  # 62

CACHE_KEY_PREFIX = "shorturl"

# Length of generated short codes. At length 7 there are 62^7 (~3.5
# trillion) possible codes; by the birthday-paradox approximation,
# collisions only become likely after roughly sqrt(62^7) (~1.9 million)
# codes exist -- far beyond what this project will ever generate.
SHORT_CODE_LENGTH = 7

# How many times to retry generating a fresh random code if we happen to
# hit a collision (should basically never fire at this table size, but
# handling it correctly is the point -- not assuming it can't happen).
MAX_GENERATION_ATTEMPTS = 5


def generate_random_code(length: int = SHORT_CODE_LENGTH) -> str:
    """
    Cryptographically random short code.

    Uses `secrets`, not `random` -- `random` is a Mersenne Twister PRNG,
    predictable if enough output is observed, which matters here because
    short codes are literally public URLs. `secrets` draws from the OS's
    CSPRNG and is the correct module for anything token/URL/password-like.
    """
    return ''.join(secrets.choice(ALPHABET) for _ in range(length))


def base62_decode(short_code: str) -> int:
    """Kept for completeness/debugging -- decodes a base62 string back to
    an integer. Not used in the random-code generation flow below, since
    random codes aren't derived from a numeric id in the first place."""
    num = 0
    for char in short_code:
        num = num * BASE + ALPHABET.index(char)
    return num


def _cache_key(short_code: str) -> str:
    return f"{CACHE_KEY_PREFIX}:{short_code}"


def create_short_url(long_url: str, expires_at=None) -> ShortURL:
    """
    Random-code create flow, with a safe retry-on-collision loop:

      1. Generate a random candidate code.
      2. Attempt get_or_create(short_code=candidate) -- this pushes the
         uniqueness check down to the database's unique constraint rather
         than doing a separate "does this exist?" read followed by a
         second insert. That gap between check and insert is exactly
         where a race condition would otherwise live (two concurrent
         requests both see "not taken", both try to insert). get_or_create
         collapses that into effectively one atomic operation as far as
         the caller is concerned.
      3. If the code was already taken (created=False), loop and try a
         fresh random code, up to MAX_GENERATION_ATTEMPTS times.

    Only ONE database round trip in the common case (no collision) --
    simpler than the old two-write base62(id) approach, at the cost of a
    (vanishingly small) chance of needing a retry.
    """
    for _ in range(MAX_GENERATION_ATTEMPTS):
        code = generate_random_code()
        obj, created = ShortURL.objects.get_or_create(
            short_code=code,
            defaults={'long_url': long_url, 'expires_at': expires_at},
        )
        if created:
            return obj
        # collision -- code already existed, try again with a new one

    raise RuntimeError(
        f"Failed to generate a unique short code after "
        f"{MAX_GENERATION_ATTEMPTS} attempts. At the current table size "
        f"this should be astronomically unlikely -- if it ever actually "
        f"fires, increase SHORT_CODE_LENGTH."
    )


def resolve_short_url(short_code: str) -> str | None:
    """
    Cache-aside read for the redirect hot path.

    1. Check Redis first.
    2. On miss, hit Postgres, then populate the cache for next time.
    3. Return None if not found or expired (caller decides how to respond).

    This is intentionally the ONLY place that reads a short_code -> long_url
    mapping in the whole app, so the caching strategy lives in one function.
    """
    cache_key = _cache_key(short_code)
    cached_url = cache.get(cache_key)
    if cached_url is not None:
        return cached_url

    try:
        obj = ShortURL.objects.get(short_code=short_code)
    except ShortURL.DoesNotExist:
        return None

    if obj.is_expired:
        return None

    cache.set(cache_key, obj.long_url, timeout=settings.SHORT_URL_CACHE_TTL)
    return obj.long_url


# Note: click counting has moved to shortener/tasks.py as a Celery task
# (record_click), dispatched asynchronously from the view via .delay()
# rather than called synchronously here. Kept out of services.py so it's
# clear at a glance that nothing in this module blocks on task-queue
# infrastructure -- services.py stays synchronous and framework-light.
