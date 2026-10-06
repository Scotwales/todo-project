import logging
import os
import sys
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tasks"

    def ready(self):
        if "runserver" not in sys.argv:
            return
        if os.environ.get("RUN_MAIN") not in ("true", "1") and "--noreload" not in sys.argv:
            return
        try:
            from .scheduler import start_scheduler
            start_scheduler()
        except Exception:
            logger.exception("Unable to start task reminder scheduler")
