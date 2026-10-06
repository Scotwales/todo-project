import calendar
from datetime import date
from django.db import models
from django.utils import timezone


class Task(models.Model):
    class Recurrence(models.TextChoices):
        NONE = "none", "Does not repeat"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    class Priority(models.IntegerChoices):
        LOW = 1, "Low"
        NORMAL = 2, "Normal"
        HIGH = 3, "High"

    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    due_time = models.TimeField(null=True, blank=True)
    reminder_at = models.DateTimeField(null=True, blank=True)
    recurrence = models.CharField(max_length=10, choices=Recurrence.choices, default=Recurrence.NONE)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.NORMAL)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("is_completed", "due_date", "due_time", "-priority", "created_at")
        indexes = [
            models.Index(fields=("due_date", "due_time"), name="task_due_date_time_idx"),
            models.Index(fields=("reminder_at",), name="task_reminder_at_idx"),
        ]

    def __str__(self):
        return self.title

    def occurs_on(self, day: date) -> bool:
        anchor = self.due_date or timezone.localtime(self.created_at).date()
        if day < anchor:
            return False
        if self.recurrence == self.Recurrence.NONE:
            return self.due_date == day
        if self.recurrence == self.Recurrence.DAILY:
            return True
        if self.recurrence == self.Recurrence.WEEKLY:
            return day.weekday() == anchor.weekday()
        if self.recurrence == self.Recurrence.MONTHLY:
            return day.day == min(anchor.day, calendar.monthrange(day.year, day.month)[1])
        return False


class TaskCompletion(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="daily_completions")
    occurrence_date = models.DateField()
    completed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("task", "occurrence_date"), name="unique_task_occurrence_completion")
        ]


class PomodoroSession(models.Model):
    started_at = models.DateTimeField(default=timezone.now)
    duration_minutes = models.PositiveSmallIntegerField(default=25)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [models.Index(fields=("completed_at",), name="pomo_completed_idx")]
