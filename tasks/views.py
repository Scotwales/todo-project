import calendar
import logging
import os
import sqlite3
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from django.contrib import messages
from django.conf import settings
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.db.models import Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from openpyxl import Workbook
from .forms import BulkTaskForm, RestoreForm, TaskForm
from .models import (
    DesktopNotification, PomodoroSession, RecurringSchedule, Task, TaskCompletion,
    TaskExtensionHistory, TaskTimeEntry,
)
from .planning import actual_seconds, due_datetime, generate_occurrences, tracked_seconds_between
from config.release import APP_NAME, APP_VERSION, BUILD_DATE, RELEASE_NOTES
from config.startup import backup_connection_before_migration, validate_database_integrity
from config.user_settings import read_preferences, save_preferences

logger = logging.getLogger(__name__)


def _ordered_day_tasks(tasks, day, completed_recurring=None):
    occurring = [task for task in tasks if task.occurs_on(day)]
    recurring_ids = [task.id for task in occurring if task.recurrence != Task.Recurrence.NONE]
    if completed_recurring is None:
        completed_recurring = set(TaskCompletion.objects.filter(
            task_id__in=recurring_ids, occurrence_date=day
        ).values_list("task_id", flat=True))
    return sorted(occurring, key=lambda task: (
        task.is_completed if task.recurrence == Task.Recurrence.NONE else task.id in completed_recurring,
        task.due_time is None, task.due_time, -task.priority, task.created_at,
    ))


def _day_tasks(day):
    tasks = list(Task.objects.filter(
        due_date=day, recurrence=Task.Recurrence.NONE, is_cancelled=False,
    ).select_related("recurring_template"))
    return _ordered_day_tasks(tasks, day)


def _safe_next(request):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return "dashboard"


def dashboard(request):
    today = timezone.localdate()
    generate_occurrences(through=today)
    tasks = _day_tasks(today)
    completed_recurring = set()
    completed = sum(task.is_completed for task in tasks)
    workload_minutes = sum(task.deliverable_minutes or 0 for task in tasks if not task.is_completed)
    completed_estimate_minutes = sum(task.deliverable_minutes or 0 for task in tasks if task.is_completed)
    today_start = timezone.make_aware(datetime.combine(today, time.min), timezone.get_current_timezone())
    tomorrow_start = timezone.make_aware(
        datetime.combine(today + timedelta(days=1), time.min), timezone.get_current_timezone()
    )
    actual_today_seconds = tracked_seconds_between(
        today_start, tomorrow_start, TaskTimeEntry.objects.filter(task__in=tasks)
    )
    for task in tasks:
        task.actual_seconds = actual_seconds(task)
        task.weekdays = (
            task.recurring_template.recurring_schedule.weekdays
            if task.recurring_template_id and hasattr(task.recurring_template, "recurring_schedule")
            else []
        )
    week_start = today - timedelta(days=today.weekday())
    labels, completed_counts, created_counts = [], [], []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        labels.append(day.strftime("%a"))
        completed_counts.append(TaskCompletion.objects.filter(occurrence_date=day).count() +
                                Task.objects.filter(is_completed=True, completed_at__date=day, recurrence=Task.Recurrence.NONE).count())
        created_counts.append(Task.objects.filter(created_at__date=day).count())
    context = {
        "today": today, "tasks": tasks, "completed_recurring": completed_recurring,
        "completed_count": completed, "task_count": len(tasks), "pending_count": len(tasks) - completed,
        "workload_minutes": workload_minutes,
        "workload_hours": workload_minutes / 60,
        "completed_estimate_minutes": completed_estimate_minutes,
        "actual_today_minutes": actual_today_seconds // 60,
        "active_task_id": TaskTimeEntry.objects.filter(ended_at__isnull=True).values_list("task_id", flat=True).first(),
        "upcoming": Task.objects.filter(is_completed=False, is_cancelled=False, due_date__gt=today, recurrence=Task.Recurrence.NONE).order_by("due_date")[:5],
        "chart_labels": labels, "chart_completed": completed_counts, "chart_created": created_counts,
        "form": TaskForm(initial={"due_date": today}),
        "active_pomodoro": PomodoroSession.objects.filter(completed_at__isnull=True).first(),
    }
    return render(request, "tasks/dashboard.html", context)


def bulk_create(request):
    if request.method == "POST":
        form = BulkTaskForm(request.POST)
        if form.is_valid():
            values = form.cleaned_data
            due_date = values["due_date"] or timezone.localdate()
            interval = values["reminder_interval_minutes"]
            due_time = values["due_time"]
            reminder_at = None
            if interval is not None and due_time:
                due_at = timezone.make_aware(
                    datetime.combine(due_date, due_time), timezone.get_current_timezone()
                )
                reminder_at = due_at - timedelta(minutes=interval)
            Task.objects.bulk_create([
                Task(
                    title=title,
                    category=values["category"],
                    priority=values["priority"],
                    due_date=due_date,
                    due_time=due_time,
                    reminder_interval_minutes=interval,
                    reminder_at=reminder_at,
                    deliverable_minutes=values["deliverable_minutes"],
                )
                for title in values["titles"]
            ])
            messages.success(request, f"Added {len(values['titles'])} tasks.")
            return redirect("dashboard")
    else:
        form = BulkTaskForm(initial={"due_date": timezone.localdate()})
    return render(request, "tasks/bulk_create.html", {"form": form})


def daily_planner(request):
    day_text = request.GET.get("date", "")
    try:
        day = date.fromisoformat(day_text) if day_text else timezone.localdate()
    except ValueError:
        return HttpResponseBadRequest("Invalid planner date.")
    generate_occurrences(through=day)
    tasks = _day_tasks(day)
    timed_schedule = []
    flexible_tasks = []
    for task in tasks:
        duration = task.deliverable_minutes or 30
        if task.due_time:
            end_at = datetime.combine(day, task.due_time)
            start_at = end_at - timedelta(minutes=duration)
            timed_schedule.append({
                "task": task, "start": start_at, "end": end_at,
                "duration": duration,
            })
        else:
            flexible_tasks.append((task, duration))

    schedule = list(timed_schedule)
    cursor = datetime.combine(day, time(9, 0))
    for task, duration in flexible_tasks:
        start_at = cursor
        while True:
            end_at = start_at + timedelta(minutes=duration)
            conflict = next((
                item for item in schedule
                if start_at < item["end"] and end_at > item["start"]
            ), None)
            if conflict is None:
                break
            start_at = conflict["end"]
        cursor = end_at
        schedule.append({"task": task, "start": start_at, "end": end_at, "duration": duration})

    schedule.sort(key=lambda item: (item["start"], item["end"]))
    lane_ends = []
    for item in schedule:
        lane = next((index for index, end_at in enumerate(lane_ends) if end_at <= item["start"]), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(item["end"])
        else:
            lane_ends[lane] = item["end"]
        item["lane"] = lane
    lane_count = max(1, len(lane_ends))
    for item in schedule:
        item["top"] = max(0, (
            item["start"].hour * 60 + item["start"].minute - 8 * 60
        ) * 1.2)
        item["height"] = max(36, item["duration"] * 1.2)
        item["left"] = item["lane"] * (100 / lane_count)
        item["width"] = 100 / lane_count
    workload = sum(item["duration"] for item in schedule if not item["task"].is_completed)
    return render(request, "tasks/planner.html", {
        "day": day, "previous": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "schedule": schedule, "workload_minutes": workload,
        "hours": [{"label": datetime.combine(day, time(hour)).strftime("%-I %p") if os.name != "nt"
                   else datetime.combine(day, time(hour)).strftime("%I %p").lstrip("0"),
                   "top": (hour - 8) * 72} for hour in range(8, 21)],
    })


def analytics(request):
    today = timezone.localdate()
    try:
        days = min(90, max(7, int(request.GET.get("days", "7"))))
    except ValueError:
        days = 7
    start_day = today - timedelta(days=days - 1)
    due_tasks = Task.objects.filter(
        recurrence=Task.Recurrence.NONE, is_cancelled=False, due_date__range=(start_day, today), recurring_template__isnull=False
    )
    standalone_tasks = Task.objects.filter(
        recurrence=Task.Recurrence.NONE, is_cancelled=False, due_date__range=(start_day, today), recurring_template__isnull=True
    )
    due_count = due_tasks.count() + standalone_tasks.count()
    completed_count = due_tasks.filter(is_completed=True).count() + standalone_tasks.filter(is_completed=True).count()
    estimated_minutes = (due_tasks.aggregate(total=Sum("deliverable_minutes"))["total"] or 0) + (
        standalone_tasks.aggregate(total=Sum("deliverable_minutes"))["total"] or 0
    )
    now = timezone.now()
    period_start = timezone.make_aware(datetime.combine(start_day, time.min), timezone.get_current_timezone())
    period_end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min), timezone.get_current_timezone())
    entries = list(TaskTimeEntry.objects.filter(
        started_at__lt=period_end,
    ).filter(
        Q(ended_at__isnull=True) | Q(ended_at__gt=period_start)
    ))
    actual = tracked_seconds_between(period_start, period_end, entries, now=now)
    extended_count = TaskExtensionHistory.objects.filter(created_at__date__range=(start_day, today)).values("task_id").distinct().count()
    completion_rate = round(completed_count * 100 / due_count) if due_count else 0
    estimated_hours = estimated_minutes / 60
    actual_hours = actual / 3600
    time_efficiency = min(1, estimated_hours / actual_hours) if actual_hours else 1
    productivity_score = round(completion_rate * time_efficiency)
    labels, completed_by_day, effort_by_day = [], [], []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        labels.append(day.strftime("%b %d"))
        completed_by_day.append(Task.objects.filter(
            is_completed=True, completed_at__date=day, recurrence=Task.Recurrence.NONE,
        ).count())
        day_start = timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())
        day_end = timezone.make_aware(
            datetime.combine(day + timedelta(days=1), time.min), timezone.get_current_timezone()
        )
        effort_by_day.append(tracked_seconds_between(day_start, day_end, entries, now=now))
    return render(request, "tasks/analytics.html", {
        "days": days, "start_day": start_day, "today": today,
        "completed_count": completed_count, "extended_count": extended_count,
        "completion_rate": completion_rate, "estimated_hours": round(estimated_hours, 1),
        "actual_hours": round(actual_hours, 1), "productivity_score": productivity_score,
        "chart_labels": labels, "chart_completed": completed_by_day,
        "chart_seconds": effort_by_day,
    })


def _parse_month(request):
    try:
        year, month = int(request.GET.get("year", timezone.localdate().year)), int(request.GET.get("month", timezone.localdate().month))
        if month < 1 or month > 12 or year < 2000 or year > 2100:
            raise ValueError
        return year, month
    except (TypeError, ValueError):
        return timezone.localdate().year, timezone.localdate().month


def calendar_view(request):
    year, month = _parse_month(request)
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    grid_start = first - timedelta(days=first.weekday())
    month_end = date(year, month, last_day)
    grid_end = month_end + timedelta(days=(6 - month_end.weekday()) % 7)
    generate_occurrences(through=grid_end)
    calendar_tasks = list(Task.objects.filter(
        recurrence=Task.Recurrence.NONE, is_cancelled=False, due_date__range=(grid_start, grid_end)
    ).select_related("recurring_template"))
    days = []
    for offset in range((grid_end - grid_start).days + 1):
        day = grid_start + timedelta(days=offset)
        tasks = _ordered_day_tasks(calendar_tasks, day, set())
        days.append({"date": day, "tasks": tasks, "completed_recurring": set(), "in_month": day.month == month})
    previous = first - timedelta(days=1)
    next_month = first + timedelta(days=last_day)
    return render(request, "tasks/calendar.html", {
        "days": days, "month_name": first.strftime("%B %Y"), "year": year, "month": month,
        "previous": previous, "next_month": next_month, "today": timezone.localdate(),
    })


@require_POST
def create_task(request):
    form = TaskForm(request.POST)
    if form.is_valid():
        task = form.save()
        messages.success(request, f'Added “{task.title}”.')
        return redirect(_safe_next(request))
    for error in form.errors.values():
        messages.error(request, " ".join(error))
    return redirect(_safe_next(request))


@require_POST
def update_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    update_series = request.POST.get("apply_to_series") == "on" and task.recurring_template_id
    if update_series:
        task = task.recurring_template
    form = TaskForm(request.POST, instance=task)
    if form.is_valid():
        form.save()
        if update_series:
            today = timezone.localdate()
            schedule = RecurringSchedule.objects.filter(template=task).first()
            if schedule:
                schedule.starts_on = task.due_date or today
                schedule.last_generated_through = today - timedelta(days=1)
                schedule.save(update_fields=("starts_on", "last_generated_through"))
            for occurrence in task.occurrences.filter(due_date__gte=today, is_completed=False):
                if schedule and schedule.occurs_on(occurrence.occurrence_date):
                    occurrence.title = task.title
                    occurrence.notes = task.notes
                    occurrence.category = task.category
                    occurrence.due_time = task.due_time
                    occurrence.reminder_interval_minutes = task.reminder_interval_minutes
                    occurrence.reminder_at = None
                    if task.reminder_interval_minutes and task.due_time:
                        due_at = timezone.make_aware(
                            datetime.combine(occurrence.occurrence_date, task.due_time),
                            timezone.get_current_timezone(),
                        )
                        occurrence.reminder_at = due_at - timedelta(minutes=task.reminder_interval_minutes)
                    occurrence.deliverable_minutes = task.deliverable_minutes
                    occurrence.priority = task.priority
                    occurrence.is_cancelled = False
                    occurrence.notified_at = None
                else:
                    occurrence.is_cancelled = True
                fields = ["is_cancelled", "updated_at"]
                if schedule and not occurrence.is_cancelled:
                    fields.extend((
                        "title", "notes", "category", "due_time", "reminder_interval_minutes",
                        "reminder_at", "deliverable_minutes", "priority", "notified_at",
                    ))
                occurrence.save(update_fields=fields)
            messages.success(request, f'Updated “{task.title}” and refreshed its future occurrences.')
        else:
            messages.success(request, f'Updated “{task.title}”.')
    else:
        messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
    return redirect(_safe_next(request))


@require_POST
def duplicate_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    duplicate = Task.objects.create(
        title=task.title,
        notes=task.notes,
        category=task.category,
        due_date=task.due_date,
        due_time=task.due_time,
        reminder_at=task.reminder_at,
        reminder_interval_minutes=task.reminder_interval_minutes,
        deliverable_minutes=task.deliverable_minutes,
        recurrence=task.recurrence,
        priority=task.priority,
    )
    if task.recurrence != Task.Recurrence.NONE:
        source_schedule = getattr(task, "recurring_schedule", None)
        RecurringSchedule.objects.create(
            template=duplicate,
            frequency=task.recurrence,
            weekdays=source_schedule.weekdays if source_schedule else [],
            starts_on=duplicate.due_date or timezone.localdate(),
        )
    messages.success(request, f'Created a copy of “{task.title}”.')
    return redirect(_safe_next(request))


@require_POST
def toggle_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    try:
        occurrence = date.fromisoformat(request.POST.get("date", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid occurrence date.")
    if not task.occurs_on(occurrence):
        return HttpResponseBadRequest("This task does not occur on that date.")
    if task.recurrence == Task.Recurrence.NONE:
        task.is_completed = not task.is_completed
        task.completed_at = timezone.now() if task.is_completed else None
        task.save(update_fields=["is_completed", "completed_at", "updated_at"])
        if task.is_completed:
            _stop_active_timer(task)
    else:
        completion, created = TaskCompletion.objects.get_or_create(task=task, occurrence_date=occurrence)
        if not created:
            completion.delete()
    return redirect(_safe_next(request))


def _stop_active_timer(task=None):
    active = TaskTimeEntry.objects.filter(ended_at__isnull=True)
    if task is not None:
        active = active.filter(task=task)
    at = timezone.now()
    for entry in active:
        entry.stop(at)


@require_POST
def task_timer(request, task_id, action):
    if action not in ("start", "pause", "stop"):
        return JsonResponse({"error": "Choose start, pause, or stop."}, status=400)
    task = get_object_or_404(Task, pk=task_id)
    if action == "start":
        current = TaskTimeEntry.objects.filter(ended_at__isnull=True).first()
        if current and current.task_id == task.id:
            return JsonResponse({"status": "running", "task_id": task.id})
        _stop_active_timer()
        TaskTimeEntry.objects.create(task=task)
    else:
        _stop_active_timer(task)
    return JsonResponse({"status": action, "task_id": task.id, "actual_seconds": actual_seconds(task)})


def _extend_task(task, option, custom_minutes=None):
    allowed = {"15": 15, "30": 30, "60": 60, "120": 120}
    extension_type = TaskExtensionHistory.ExtensionType.DURATION
    if option == "tomorrow":
        local_now = timezone.localtime()
        baseline = due_datetime(task) or local_now
        if baseline < local_now:
            baseline = local_now
        tomorrow = (baseline + timedelta(days=1)).replace(
            hour=task.due_time.hour if task.due_time else baseline.hour,
            minute=task.due_time.minute if task.due_time else baseline.minute,
            second=0,
            microsecond=0,
        )
        minutes = max(1, int((tomorrow - baseline).total_seconds() // 60))
        new_due = tomorrow
        extension_type = TaskExtensionHistory.ExtensionType.TOMORROW
    elif option == "custom":
        try:
            minutes = int(custom_minutes)
        except (TypeError, ValueError):
            raise ValueError("Enter a custom extension from 1 to 1,440 minutes.")
        if not 1 <= minutes <= 1440:
            raise ValueError("Enter a custom extension from 1 to 1,440 minutes.")
        baseline = due_datetime(task) or timezone.localtime()
        new_due = baseline + timedelta(minutes=minutes)
        extension_type = TaskExtensionHistory.ExtensionType.CUSTOM
    elif option in allowed:
        minutes = allowed[option]
        baseline = due_datetime(task) or timezone.localtime()
        new_due = baseline + timedelta(minutes=minutes)
    else:
        raise ValueError("Choose a supported extension.")

    previous_due = due_datetime(task)
    task.due_date = timezone.localtime(new_due).date()
    task.due_time = timezone.localtime(new_due).time().replace(second=0, microsecond=0)
    task.reminder_at = new_due - timedelta(minutes=task.reminder_interval_minutes) if task.reminder_interval_minutes else None
    task.notified_at = (
        timezone.now()
        if task.reminder_at and task.reminder_at <= timezone.now()
        else None
    )
    task.save(update_fields=("due_date", "due_time", "reminder_at", "notified_at", "updated_at"))
    return TaskExtensionHistory.objects.create(
        task=task, extension_type=extension_type, minutes=minutes,
        previous_due_at=previous_due, extended_due_at=new_due,
    )


@require_POST
def extend_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    try:
        history = _extend_task(task, request.POST.get("option", ""), request.POST.get("custom_minutes"))
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    DesktopNotification.objects.filter(task=task, dismissed_at__isnull=True).update(
        dismissed_at=timezone.now(), actioned_at=timezone.now()
    )
    return JsonResponse({
        "status": "extended",
        "due_date": task.due_date.isoformat(),
        "due_time": task.due_time.strftime("%H:%M"),
        "minutes": history.minutes,
    })


@require_GET
def pending_notifications(request):
    items = DesktopNotification.objects.filter(
        dismissed_at__isnull=True, actioned_at__isnull=True,
        task__is_completed=False, task__is_cancelled=False,
    ).select_related("task")[:10]
    return JsonResponse({"notifications": [{
        "id": item.id,
        "task_id": item.task_id,
        "title": item.task.title,
        "kind": item.get_kind_display(),
        "created_at": timezone.localtime(item.created_at).isoformat(),
    } for item in items]})


@require_POST
def notification_action(request, notification_id, action):
    item = get_object_or_404(DesktopNotification.objects.select_related("task"), pk=notification_id)
    if action == "done":
        item.task.is_completed = True
        item.task.completed_at = timezone.now()
        item.task.save(update_fields=("is_completed", "completed_at", "updated_at"))
        _stop_active_timer(item.task)
    elif action == "extend":
        try:
            _extend_task(item.task, request.POST.get("option", ""), request.POST.get("custom_minutes"))
        except ValueError as error:
            return JsonResponse({"error": str(error)}, status=400)
    else:
        return JsonResponse({"error": "Unsupported notification action."}, status=400)
    item.actioned_at = timezone.now()
    item.dismissed_at = item.actioned_at
    item.save(update_fields=("actioned_at", "dismissed_at"))
    return JsonResponse({"status": action})


@require_POST
def dismiss_notification(request, notification_id):
    item = get_object_or_404(DesktopNotification, pk=notification_id)
    item.dismissed_at = timezone.now()
    item.save(update_fields=("dismissed_at",))
    return JsonResponse({"status": "dismissed"})


@require_POST
def delete_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    task.delete()
    messages.success(request, "Task deleted.")
    return redirect(_safe_next(request))


def export_excel(request):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tasks"
    sheet.append(["Title", "Notes", "Due date", "Due time", "Reminder", "Recurrence", "Priority", "Completed", "Created"])
    for task in Task.objects.all().order_by("due_date", "due_time"):
        sheet.append([task.title, task.notes, task.due_date.isoformat() if task.due_date else "",
                      task.due_time.isoformat() if task.due_time else "",
                      timezone.localtime(task.reminder_at).isoformat() if task.reminder_at else "",
                      task.get_recurrence_display(), task.get_priority_display(), task.is_completed,
                      timezone.localtime(task.created_at).isoformat()])
        for cell in sheet[sheet.max_row][:2]:
            cell.data_type = "s"
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="daily-tasks.xlsx"'
    workbook.save(response)
    return response


@require_GET
def backup_database(request):
    backup_dir = settings.DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"daily-backup-{timezone.localtime().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
    connection.ensure_connection()
    destination = sqlite3.connect(str(backup_path))
    try:
        connection.connection.backup(destination)
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
    response = HttpResponse(backup_path.read_bytes(), content_type="application/vnd.sqlite3")
    response["Content-Disposition"] = f'attachment; filename="{backup_path.name}"'
    return response


@require_POST
def restore_database(request):
    form = RestoreForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
        return redirect("settings")
    upload = form.cleaned_data["backup"]
    temp_path = None
    rollback_backup = None
    restored = False
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as temporary:
            temp_path = Path(temporary.name)
            for chunk in upload.chunks():
                temporary.write(chunk)
        source = sqlite3.connect(str(temp_path))
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("The backup failed SQLite integrity validation.")
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"tasks_task", "tasks_taskcompletion", "tasks_pomodorosession"}
            if not required.issubset(tables):
                raise ValueError("This file does not contain a compatible Daily backup.")
            columns = {
                "tasks_task": {"id", "title", "notes", "due_date", "due_time", "reminder_at", "recurrence",
                               "priority", "is_completed", "completed_at", "notified_at", "created_at", "updated_at"},
                "tasks_taskcompletion": {"id", "task_id", "occurrence_date", "completed_at"},
                "tasks_pomodorosession": {"id", "started_at", "duration_minutes", "completed_at"},
            }
            for table, required_columns in columns.items():
                actual_columns = {row[1] for row in source.execute(f'PRAGMA table_info("{table}")')}
                if not required_columns.issubset(actual_columns):
                    raise ValueError("This file does not contain a compatible Daily backup.")
            if source.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1").fetchone():
                raise ValueError("Backups containing triggers or views are not supported.")
            if source.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("The backup contains invalid task references.")
            connection.ensure_connection()
            rollback_backup = backup_connection_before_migration(
                connection.connection, settings.BACKUP_DIR, prefix="pre-restore"
            )
            source.backup(connection.connection)
            restored = True
        finally:
            source.close()
        connection.close()
        connection.ensure_connection()
        backup_connection_before_migration(connection.connection, settings.BACKUP_DIR)
        call_command("migrate", interactive=False, verbosity=0)
        validate_database_integrity(connection.settings_dict["NAME"])
        messages.success(request, "Backup restored.")
    except (sqlite3.DatabaseError, DatabaseError, ValueError, OSError, RuntimeError) as exc:
        logger.warning("Backup restore rejected: %s", exc)
        if rollback_backup and restored:
            try:
                connection.close()
                connection.ensure_connection()
                with sqlite3.connect(str(rollback_backup), timeout=20) as previous:
                    previous.backup(connection.connection)
                connection.close()
            except (sqlite3.DatabaseError, DatabaseError, OSError) as rollback_error:
                logger.exception("Unable to restore the pre-restore database backup")
                messages.error(
                    request,
                    f"Backup restore failed ({exc}) and the previous database could not be "
                    f"restored ({rollback_error}). The safety copy is at {rollback_backup}.",
                )
            else:
                messages.error(request, f"Backup was not restored; the previous data was recovered: {exc}")
        else:
            messages.error(request, f"Backup was not restored: {exc}")
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
    return redirect("settings")


@require_POST
def pomodoro(request):
    try:
        duration = int(request.POST.get("duration", "25"))
        if duration not in (15, 25, 45, 60):
            raise ValueError
    except ValueError:
        return HttpResponseBadRequest("Choose a supported Pomodoro duration.")
    PomodoroSession.objects.filter(completed_at__isnull=True).update(completed_at=timezone.now())
    session = PomodoroSession.objects.create(duration_minutes=duration)
    return redirect("dashboard")


@require_POST
def finish_pomodoro(request, session_id):
    session = get_object_or_404(PomodoroSession, pk=session_id)
    if session.completed_at is None:
        session.completed_at = timezone.now()
        session.save(update_fields=["completed_at"])
        if session.started_at + timedelta(minutes=session.duration_minutes) <= session.completed_at:
            from .notifications import send_notification
            send_notification("Pomodoro complete", "Your focus session has ended.")
    return redirect("dashboard")


def settings_view(request):
    if request.method == "POST":
        theme = request.POST.get("theme")
        if theme not in ("light", "dark", "system"):
            return HttpResponseBadRequest("Invalid theme.")
        preferences = read_preferences()
        preferences["theme"] = theme
        save_preferences(preferences)
        request.session["theme"] = theme
        messages.success(request, "Theme preference saved.")
        return redirect("settings")
    backup_dir = settings.DATA_DIR / "backups"
    return render(request, "tasks/settings.html", {
        "restore_form": RestoreForm(),
        "backup_directory": backup_dir,
        "backup_count": len(list(backup_dir.glob("*.sqlite3"))) if backup_dir.exists() else 0,
        "saved_theme": read_preferences().get("theme", request.session.get("theme", "light")),
    })


def about(request):
    return render(request, "tasks/about.html", {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "build_date": BUILD_DATE,
        "data_directory": settings.DATA_DIR,
        "release_notes": RELEASE_NOTES,
    })
