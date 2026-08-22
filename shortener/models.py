from django.db import models
from django.utils import timezone


class ShortURL(models.Model):
    """
    A single shortened URL.

    short_code is the hot-path lookup key (every redirect queries by it),
    so it's unique + indexed. long_url has no index -- it's never queried
    by value in this design (we don't do "has this URL already been
    shortened" lookups, to keep the write path a single fast insert).
    """

    short_code = models.CharField(max_length=10, unique=True, db_index=True, blank=True)
    long_url = models.URLField(max_length=2048)
    clicks = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.short_code} -> {self.long_url[:50]}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < timezone.now()
