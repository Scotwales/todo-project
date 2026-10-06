import calendar
import logging
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path
from django.contrib import messages
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from openpyxl import Workbook
from .forms import RestoreForm, TaskForm
from .models import PomodoroSession, Task, TaskCompletion

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
    recurring = Task.objects.filter(Q(due_date__lte=day) | Q(due_date__isnull=True)).exclude(recurrence=Task.Recurrence.NONE)
    one_offs = Task.objects.filter(recurrence=Task.Recurrence.NONE, due_date=day)
    tasks = list(recurring) + list(one_offs)
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
    tasks = _day_tasks(today)
    recurring_ids = [task.id for task in tasks if task.recurrence != Task.Recurrence.NONE]
    completed_recurring = set(TaskCompletion.objects.filter(task_id__in=recurring_ids, occurrence_date=today).values_list("task_id", flat=True))
    completed = sum(task.id in completed_recurring if task.recurrence != Task.Recurrence.NONE else task.is_completed for task in tasks)
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
        "completed_count": completed, "task_count": len(tasks),
        "upcoming": Task.objects.filter(is_completed=False, due_date__gt=today, recurrence=Task.Recurrence.NONE).order_by("due_date")[:5],
        "chart_labels": labels, "chart_completed": completed_counts, "chart_created": created_counts,
        "form": TaskForm(initial={"due_date": today}),
        "active_pomodoro": PomodoroSession.objects.filter(completed_at__isnull=True).first(),
    }
    return render(request, "tasks/dashboard.html", context)


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
    recurring_filter = (
        ~Q(recurrence=Task.Recurrence.NONE)
        & (Q(due_date__lte=grid_end) | Q(due_date__isnull=True))
    )
    one_off_filter = Q(recurrence=Task.Recurrence.NONE, due_date__range=(grid_start, grid_end))
    calendar_tasks = list(Task.objects.filter(recurring_filter | one_off_filter))
    recurring_ids = [task.id for task in calendar_tasks if task.recurrence != Task.Recurrence.NONE]
    completion_map = {}
    for occurrence_date, task_id in TaskCompletion.objects.filter(
        task_id__in=recurring_ids, occurrence_date__range=(grid_start, grid_end)
    ).values_list("occurrence_date", "task_id"):
        completion_map.setdefault(occurrence_date, set()).add(task_id)
    days = []
    for offset in range((grid_end - grid_start).days + 1):
        day = grid_start + timedelta(days=offset)
        completed = completion_map.get(day, set())
        tasks = _ordered_day_tasks(calendar_tasks, day, completed)
        days.append({"date": day, "tasks": tasks, "completed_recurring": completed, "in_month": day.month == month})
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
    else:
        completion, created = TaskCompletion.objects.get_or_create(task=task, occurrence_date=occurrence)
        if not created:
            completion.delete()
    return redirect(_safe_next(request))


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
    temporary = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    temporary.close()
    try:
        connection.ensure_connection()
        destination = sqlite3.connect(temporary.name)
        try:
            connection.connection.backup(destination)
        finally:
            destination.close()
        with open(temporary.name, "rb") as backup:
            response = HttpResponse(backup.read(), content_type="application/vnd.sqlite3")
        response["Content-Disposition"] = 'attachment; filename="daily-backup.sqlite3"'
        return response
    finally:
        Path(temporary.name).unlink(missing_ok=True)


@require_POST
def restore_database(request):
    form = RestoreForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
        return redirect("settings")
    upload = form.cleaned_data["backup"]
    temp_path = None
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
            source.backup(connection.connection)
        finally:
            source.close()
        messages.success(request, "Backup restored.")
    except (sqlite3.DatabaseError, ValueError, OSError) as exc:
        logger.warning("Backup restore rejected: %s", exc)
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
        request.session["theme"] = theme
        messages.success(request, "Theme preference saved.")
        return redirect("settings")
    return render(request, "tasks/settings.html", {"restore_form": RestoreForm()})
