"""
Celery application setup.

Redis is reused as the Celery broker (the queue Celery reads tasks from)
-- it's already running for caching, so this avoids introducing a second
piece of infrastructure (e.g. RabbitMQ) just for task queuing. This is a
common real-world pattern for small-to-medium services.
"""

import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Read CELERY_* settings from Django's settings.py (namespace='CELERY'
# means e.g. CELERY_BROKER_URL in settings.py becomes broker_url here).
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py in each installed app (shortener/tasks.py).
app.autodiscover_tasks()
