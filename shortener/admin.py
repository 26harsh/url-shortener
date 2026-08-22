from django.contrib import admin
from .models import ShortURL


@admin.register(ShortURL)
class ShortURLAdmin(admin.ModelAdmin):
    list_display = ('short_code', 'long_url', 'clicks', 'created_at', 'expires_at')
    search_fields = ('short_code', 'long_url')
    readonly_fields = ('created_at',)
