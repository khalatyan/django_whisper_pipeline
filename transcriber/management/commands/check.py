from django.core.management.base import BaseCommand
import logging

from transcriber.tasks import run_ready_tasks

logger = logging.getLogger(__name__)

class Command(BaseCommand):

    def handle(self, *args, **options):
        run_ready_tasks()