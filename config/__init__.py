# Ensures the Celery app is loaded whenever Django starts, so that
# @shared_task-decorated functions register correctly.
from .celery import app as celery_app

__all__ = ('celery_app',)
