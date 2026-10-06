from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import RecurringSchedule, Task, TaskCompletion, TaskTimeEntry


def generate_occurrences(days_ahead=30, through=None):
    today = timezone.localdate()
    through = through or today + timedelta(days=days_ahead)
    created = 0
    schedules = RecurringSchedule.objects.select_related("template").all()
    for schedule in schedules.iterator():
        first = schedule.starts_on
        if schedule.last_generated_through:
            first = max(first, schedule.last_generated_through + timedelta(days=1))
        if first > through:
            continue
        template = schedule.template
        legacy_completed_dates = set(TaskCompletion.objects.filter(
            task=template, occurrence_date__range=(first, through)
        ).values_list("occurrence_date", flat=True))
        with transaction.atomic():
            for offset in range((through - first).days + 1):
                occurrence_date = first + timedelta(days=offset)
                if not schedule.occurs_on(occurrence_date):
                    continue
                reminder_at = None
                if template.reminder_interval_minutes and template.due_time:
                    due_at = timezone.make_aware(
                        datetime.combine(occurrence_date, template.due_time),
                        timezone.get_current_timezone(),
                    )
                    reminder_at = due_at - timedelta(minutes=template.reminder_interval_minutes)
                occurrence, was_created = Task.objects.get_or_create(
                    recurring_template=template,
                    occurrence_date=occurrence_date,
                    defaults={
                        "title": template.title,
                        "notes": template.notes,
                        "category": template.category,
                        "due_date": occurrence_date,
                        "due_time": template.due_time,
                        "reminder_at": reminder_at,
                        "reminder_interval_minutes": template.reminder_interval_minutes,
                        "deliverable_minutes": template.deliverable_minutes,
                        "priority": template.priority,
                        "is_completed": occurrence_date in legacy_completed_dates,
                        "completed_at": timezone.now() if occurrence_date in legacy_completed_dates else None,
                    },
                )
                if occurrence.is_cancelled:
                    occurrence.is_cancelled = False
                    occurrence.notified_at = None
                    occurrence.title = template.title
                    occurrence.notes = template.notes
                    occurrence.category = template.category
                    occurrence.due_time = template.due_time
                    occurrence.reminder_at = reminder_at
                    occurrence.reminder_interval_minutes = template.reminder_interval_minutes
                    occurrence.deliverable_minutes = template.deliverable_minutes
                    occurrence.priority = template.priority
                    occurrence.save(update_fields=(
                        "is_cancelled", "notified_at", "title", "notes", "category", "due_time",
                        "reminder_at", "reminder_interval_minutes", "deliverable_minutes",
                        "priority", "updated_at",
                    ))
                created += int(was_created)
            schedule.last_generated_through = through
            schedule.save(update_fields=("last_generated_through",))
    return created


def actual_seconds(task, now=None):
    now = now or timezone.now()
    total = 0
    for entry in task.time_entries.all():
        if entry.ended_at:
            total += entry.duration_seconds
        else:
            total += max(0, int((now - entry.started_at).total_seconds()))
    return total


def tracked_seconds_between(start, end, entries=None, now=None):
    now = now or timezone.now()
    if entries is None:
        from django.db.models import Q

        entries = TaskTimeEntry.objects.filter(
            started_at__lt=end,
        ).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start))
    total = 0
    for entry in entries:
        entry_start = max(start, entry.started_at)
        entry_end = min(end, entry.ended_at or now)
        if entry_end > entry_start:
            total += int((entry_end - entry_start).total_seconds())
    return total


def due_datetime(task):
    if task.due_date:
        return timezone.make_aware(
            datetime.combine(task.due_date, task.due_time or time(23, 59)),
            timezone.get_current_timezone(),
        )
    return None


def stop_active_timers():
    stopped_at = timezone.now()
    active = TaskTimeEntry.objects.filter(ended_at__isnull=True)
    count = active.count()
    for entry in active:
        entry.stop(stopped_at)
    return count
