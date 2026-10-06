import logging
from datetime import timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=timezone.get_current_timezone())


def check_reminders():
    from .models import PomodoroSession, Task
    close_old_connections()
    now = timezone.now()
    due = list(Task.objects.filter(reminder_at__lte=now, notified_at__isnull=True))
    for task in due:
        from .notifications import send_notification
        if send_notification("Task reminder", task.title):
            task.notified_at = now
            task.save(update_fields=["notified_at", "updated_at"])
    from .notifications import send_notification
    for session in PomodoroSession.objects.filter(completed_at__isnull=True):
        if session.started_at + timedelta(minutes=session.duration_minutes) <= now:
            session.completed_at = now
            session.save(update_fields=["completed_at"])
            send_notification("Pomodoro complete", "Your focus session has ended.")
    close_old_connections()


def start_scheduler():
    if scheduler.running:
        return
    scheduler.add_job(check_reminders, "interval", minutes=1, id="task-reminders", replace_existing=True)
    scheduler.start()
    logger.info("Task reminder scheduler started")
