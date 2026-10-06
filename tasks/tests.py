import io
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from .models import PomodoroSession, Task, TaskCompletion


class TaskModelTests(TestCase):
    def test_recurrence_occurrence_dates(self):
        task = Task.objects.create(title="Weekly", due_date=date(2025, 1, 6), recurrence=Task.Recurrence.WEEKLY)
        self.assertTrue(task.occurs_on(date(2025, 1, 13)))
        self.assertFalse(task.occurs_on(date(2025, 1, 14)))

    def test_weekly_task_without_due_date_uses_creation_weekday(self):
        task = Task.objects.create(title="Weekly", recurrence=Task.Recurrence.WEEKLY)
        created_day = timezone.localtime(task.created_at).date()
        self.assertTrue(task.occurs_on(created_day))
        self.assertFalse(task.occurs_on(created_day + timedelta(days=1)))

    def test_monthly_recurrence_clamps_to_month_end(self):
        task = Task.objects.create(title="Monthly", due_date=date(2025, 1, 31), recurrence=Task.Recurrence.MONTHLY)
        self.assertTrue(task.occurs_on(date(2025, 2, 28)))
        self.assertFalse(task.occurs_on(date(2025, 2, 27)))

    def test_task_completion_is_unique_for_each_day(self):
        task = Task.objects.create(title="Daily", recurrence=Task.Recurrence.DAILY)
        day = date(2025, 1, 1)
        TaskCompletion.objects.create(task=task, occurrence_date=day)
        with self.assertRaises(IntegrityError):
            TaskCompletion.objects.create(task=task, occurrence_date=day)


class TaskViewTests(TransactionTestCase):
    def test_dashboard_shows_today_and_quick_add(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quick add")

    def test_create_and_toggle_task(self):
        today = timezone.localdate().isoformat()
        response = self.client.post(reverse("create_task"), {"title": "Read", "due_date": today, "recurrence": "none", "priority": 2})
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Read")
        self.client.post(reverse("toggle_task", args=[task.id]), {"date": today})
        task.refresh_from_db()
        self.assertTrue(task.is_completed)

    def test_task_redirect_does_not_allow_external_host(self):
        response = self.client.post(reverse("create_task"), {
            "title": "Safe redirect", "due_date": timezone.localdate().isoformat(),
            "recurrence": "none", "priority": 2, "next": "https://example.com",
        })
        self.assertEqual(response["Location"], reverse("dashboard"))
        self.assertTrue(Task.objects.filter(title="Safe redirect").exists())

    def test_cannot_toggle_task_on_non_occurrence_date(self):
        task = Task.objects.create(title="Weekly", due_date=timezone.localdate(), recurrence=Task.Recurrence.WEEKLY)
        non_occurrence = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            reverse("toggle_task", args=[task.id]), {"date": non_occurrence.isoformat()}
        )
        self.assertEqual(response.status_code, 400)

    def test_recurring_toggle_tracks_occurrence_not_entire_task(self):
        task = Task.objects.create(title="Daily", due_date=timezone.localdate(), recurrence=Task.Recurrence.DAILY)
        self.client.post(reverse("toggle_task", args=[task.id]), {"date": timezone.localdate().isoformat()})
        self.assertEqual(TaskCompletion.objects.filter(task=task).count(), 1)
        self.assertFalse(task.is_completed)

    def test_calendar_invalid_month_is_safe(self):
        response = self.client.get(reverse("calendar"), {"year": "9000", "month": "15"})
        self.assertEqual(response.status_code, 200)

    def test_excel_export_contains_task(self):
        Task.objects.create(title="Export me", due_date=timezone.localdate())
        response = self.client.get(reverse("export_excel"))
        workbook = load_workbook(io.BytesIO(response.content))
        self.assertEqual(workbook.active["A2"].value, "Export me")

    def test_excel_export_keeps_formula_like_titles_as_text(self):
        Task.objects.create(title="=1+1", due_date=timezone.localdate())
        response = self.client.get(reverse("export_excel"))
        cell = load_workbook(io.BytesIO(response.content)).active["A2"]
        self.assertEqual(cell.value, "=1+1")
        self.assertEqual(cell.data_type, "s")

    def test_pomodoro_rejects_invalid_duration(self):
        self.assertEqual(self.client.post(reverse("pomodoro"), {"duration": "999"}).status_code, 400)
        self.client.post(reverse("pomodoro"), {"duration": "25"})
        self.assertEqual(PomodoroSession.objects.filter(completed_at__isnull=True).count(), 1)

    def test_dark_mode_preference_is_saved(self):
        self.client.post(reverse("settings"), {"theme": "dark"})
        self.assertEqual(self.client.session["theme"], "dark")

    def test_backup_download_is_valid_sqlite(self):
        Task.objects.create(title="Backup me", due_date=timezone.localdate())
        response = self.client.get(reverse("backup"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.sqlite3"
            path.write_bytes(response.content)
            database = sqlite3.connect(str(path))
            try:
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(database.execute("SELECT title FROM tasks_task").fetchone()[0], "Backup me")
            finally:
                database.close()

    def test_valid_backup_restores_task_data(self):
        Task.objects.create(title="Restore me", due_date=timezone.localdate())
        backup = self.client.get(reverse("backup"))
        Task.objects.all().delete()
        upload = SimpleUploadedFile("daily.sqlite3", backup.content, content_type="application/vnd.sqlite3")
        self.client.post(reverse("restore"), {"backup": upload})
        self.assertTrue(Task.objects.filter(title="Restore me").exists())

    def test_restore_rejects_unrecognized_database(self):
        data = io.BytesIO(b"not a database")
        data.name = "bad.sqlite3"
        response = self.client.post(reverse("restore"), {"backup": data})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(reverse("settings")), "Backup was not restored")


class ReminderSchedulerTests(TransactionTestCase):
    @patch("tasks.notifications.send_notification", return_value=True)
    def test_reminder_is_sent_once_and_expired_focus_is_completed(self, notify):
        now = timezone.now()
        task = Task.objects.create(title="Reminder", reminder_at=now - timedelta(minutes=1))
        session = PomodoroSession.objects.create(
            started_at=now - timedelta(minutes=26), duration_minutes=25
        )

        from .scheduler import check_reminders
        check_reminders()
        task.refresh_from_db()
        session.refresh_from_db()
        self.assertIsNotNone(task.notified_at)
        self.assertIsNotNone(session.completed_at)
        self.assertEqual(notify.call_count, 2)

        check_reminders()
        self.assertEqual(notify.call_count, 2)
