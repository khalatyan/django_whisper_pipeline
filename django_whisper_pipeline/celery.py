from __future__ import absolute_import
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_whisper_pipeline.settings")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_whisper_pipeline.settings')

app = Celery("django_whisper_pipeline")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "check-tasks-every-5-minutes": {
        "task": "transcriber.tasks.run_ready_tasks",
        "schedule": crontab(minute="*/1"),
    },
}
