from unittest.mock import patch

from django.test import TestCase
from django.core.cache import cache

from shortener.services import (
    generate_random_code,
    create_short_url,
    resolve_short_url,
    SHORT_CODE_LENGTH,
    MAX_GENERATION_ATTEMPTS,
)
from shortener.models import ShortURL


class RandomCodeGenerationTests(TestCase):
    def test_generates_correct_length(self):
        code = generate_random_code()
        self.assertEqual(len(code), SHORT_CODE_LENGTH)

    def test_generates_different_codes(self):
        codes = {generate_random_code() for _ in range(200)}
        self.assertGreater(len(codes), 190)  # allow for astronomically rare dupes

    def test_retries_on_collision(self):
        with patch('shortener.services.generate_random_code') as mock_gen:
            mock_gen.side_effect = ['taken-1', 'taken-1', 'free-code']
            ShortURL.objects.create(short_code='taken-1', long_url='https://existing.example.com')

            obj = create_short_url('https://new.example.com')

            self.assertEqual(obj.short_code, 'free-code')
            self.assertEqual(mock_gen.call_count, 3)

    def test_raises_after_max_attempts_exhausted(self):
        with patch('shortener.services.generate_random_code') as mock_gen:
            mock_gen.return_value = 'always-taken'
            ShortURL.objects.create(short_code='always-taken', long_url='https://existing.example.com')

            with self.assertRaises(RuntimeError):
                create_short_url('https://new.example.com')

            self.assertEqual(mock_gen.call_count, MAX_GENERATION_ATTEMPTS)


class CreateAndResolveTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_create_assigns_short_code(self):
        obj = create_short_url("https://example.com/some/path")
        self.assertTrue(obj.short_code)
        self.assertEqual(len(obj.short_code), SHORT_CODE_LENGTH)

    def test_resolve_returns_long_url(self):
        obj = create_short_url("https://example.com/some/path")
        resolved = resolve_short_url(obj.short_code)
        self.assertEqual(resolved, "https://example.com/some/path")

    def test_resolve_unknown_code_returns_none(self):
        self.assertIsNone(resolve_short_url("doesnotexist"))

    def test_resolve_hits_cache_on_second_call(self):
        obj = create_short_url("https://example.com/cache-me")
        resolve_short_url(obj.short_code)  # populates cache
        obj.delete()  # remove from DB entirely
        # Should still resolve from cache even though the DB row is gone
        self.assertEqual(resolve_short_url(obj.short_code), "https://example.com/cache-me")
