import calendar
from datetime import date
from django.db import models
from django.utils import timezone


class Task(models.Model):
    class Recurrence(models.TextChoices):
        NONE = "none", "Does not repeat"
        DAILY = "daily", "Daily"
        WEEKDAYS = "weekdays", "Weekdays"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        CUSTOM = "custom", "Selected days"

    class Priority(models.IntegerChoices):
        LOW = 1, "Low"
        NORMAL = 2, "Normal"
        HIGH = 3, "High"

    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    due_date = models.DateField(null=True, blank=True)
    due_time = models.TimeField(null=True, blank=True)
    reminder_at = models.DateTimeField(null=True, blank=True)
    reminder_interval_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    deliverable_minutes = models.PositiveIntegerField(null=True, blank=True)
    recurrence = models.CharField(max_length=10, choices=Recurrence.choices, default=Recurrence.NONE)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.NORMAL)
    is_cancelled = models.BooleanField(default=False)
    recurring_template = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="occurrences"
    )
    occurrence_date = models.DateField(null=True, blank=True)
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
            models.Index(fields=("recurring_template", "occurrence_date"), name="task_template_occurrence_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("recurring_template", "occurrence_date"),
                condition=models.Q(recurring_template__isnull=False),
                name="unique_task_template_occurrence",
            )
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
        if self.recurrence == self.Recurrence.WEEKDAYS:
            return day.weekday() < 5
        if self.recurrence == self.Recurrence.WEEKLY:
            return day.weekday() == anchor.weekday()
        if self.recurrence == self.Recurrence.MONTHLY:
            return day.day == min(anchor.day, calendar.monthrange(day.year, day.month)[1])
        if self.recurrence == self.Recurrence.CUSTOM:
            try:
                return day.weekday() in self.recurring_schedule.weekdays
            except RecurringSchedule.DoesNotExist:
                return False
        return False


class RecurringSchedule(models.Model):
    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKDAYS = "weekdays", "Weekdays"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        CUSTOM = "custom", "Selected days"

    template = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="recurring_schedule")
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    weekdays = models.JSONField(default=list, blank=True)
    starts_on = models.DateField()
    last_generated_through = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def occurs_on(self, day: date) -> bool:
        if day < self.starts_on:
            return False
        if self.frequency == self.Frequency.DAILY:
            return True
        if self.frequency == self.Frequency.WEEKDAYS:
            return day.weekday() < 5
        if self.frequency == self.Frequency.WEEKLY:
            return day.weekday() == self.starts_on.weekday()
        if self.frequency == self.Frequency.MONTHLY:
            return day.day == min(self.starts_on.day, calendar.monthrange(day.year, day.month)[1])
        if self.frequency == self.Frequency.CUSTOM:
            return day.weekday() in self.weekdays
        return False

    def __str__(self):
        return f"{self.template.title}: {self.get_frequency_display()}"


class TaskCompletion(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="daily_completions")
    occurrence_date = models.DateField()
    completed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("task", "occurrence_date"), name="unique_task_occurrence_completion")
        ]


class TaskTimeEntry(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="time_entries")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("started_at",)
        indexes = [models.Index(fields=("task", "ended_at"), name="task_time_active_idx")]

    def stop(self, at=None):
        if self.ended_at is None:
            self.ended_at = at or timezone.now()
            self.duration_seconds = max(0, int((self.ended_at - self.started_at).total_seconds()))
            self.save(update_fields=("ended_at", "duration_seconds"))


class TaskExtensionHistory(models.Model):
    class ExtensionType(models.TextChoices):
        DURATION = "duration", "Duration"
        TOMORROW = "tomorrow", "Tomorrow"
        CUSTOM = "custom", "Custom duration"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="extension_history")
    extension_type = models.CharField(max_length=12, choices=ExtensionType.choices)
    minutes = models.PositiveIntegerField()
    previous_due_at = models.DateTimeField(null=True, blank=True)
    extended_due_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at",)


class DesktopNotification(models.Model):
    class Kind(models.TextChoices):
        REMINDER = "reminder", "Task reminder"
        OVERDUE = "overdue", "Task overdue"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="desktop_notifications")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.REMINDER)
    created_at = models.DateTimeField(default=timezone.now)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    actioned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class PomodoroSession(models.Model):
    started_at = models.DateTimeField(default=timezone.now)
    duration_minutes = models.PositiveSmallIntegerField(default=25)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [models.Index(fields=("completed_at",), name="pomo_completed_idx")]
