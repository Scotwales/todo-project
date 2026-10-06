from datetime import datetime, timedelta
from django import forms
from django.utils import timezone
from .models import RecurringSchedule, Task


class TaskForm(forms.ModelForm):
    reminder_interval_minutes = forms.TypedChoiceField(
        required=False,
        coerce=int,
        empty_value=None,
        choices=(("", "No reminder"), (5, "5 minutes before"), (10, "10 minutes before"),
                 (15, "15 minutes before"), (30, "30 minutes before"), (60, "1 hour before")),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    weekdays = forms.MultipleChoiceField(
        required=False,
        choices=((0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
                 (4, "Friday"), (5, "Saturday"), (6, "Sunday")),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Task
        fields = (
            "title", "notes", "category", "due_date", "due_time", "reminder_at",
            "reminder_interval_minutes", "deliverable_minutes", "recurrence", "priority",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "maxlength": 200, "placeholder": "What needs doing?"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Notes (optional)"}),
            "category": forms.TextInput(attrs={"class": "form-control", "maxlength": 80, "placeholder": "e.g. Work"}),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "due_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "reminder_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "deliverable_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 1440, "placeholder": "Minutes"}),
            "recurrence": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["reminder_interval_minutes"].initial = self.instance.reminder_interval_minutes
            if hasattr(self.instance, "recurring_schedule"):
                self.fields["weekdays"].initial = [str(day) for day in self.instance.recurring_schedule.weekdays]
        else:
            self.fields["weekdays"].initial = [str(timezone.localdate().weekday())]

    def clean_reminder_at(self):
        value = self.cleaned_data.get("reminder_at")
        if value and timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        unchanged_existing_reminder = self.instance.pk and value == self.instance.reminder_at
        if (value and value < timezone.now() and not unchanged_existing_reminder
                and not self.cleaned_data.get("reminder_interval_minutes")):
            raise forms.ValidationError("Choose a reminder time in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("due_date") and self.instance._state.adding:
            cleaned["due_date"] = timezone.localdate()
        if cleaned.get("deliverable_minutes") is not None and not 1 <= cleaned["deliverable_minutes"] <= 1440:
            self.add_error("deliverable_minutes", "Enter a duration between 1 and 1,440 minutes.")
        if cleaned.get("recurrence") == Task.Recurrence.CUSTOM and not cleaned.get("weekdays"):
            self.add_error("weekdays", "Select at least one day for a custom schedule.")
        if cleaned.get("reminder_interval_minutes") and not cleaned.get("due_time"):
            self.add_error("reminder_interval_minutes", "Add a due time to schedule an interval reminder.")
        if self.instance.recurring_template_id:
            cleaned["recurrence"] = Task.Recurrence.NONE
        return cleaned

    def save(self, commit=True):
        if self.instance.recurring_template_id:
            self.instance.recurrence = Task.Recurrence.NONE
        previous_interval = self.instance.reminder_interval_minutes
        task = super().save(commit=commit)
        task.reminder_interval_minutes = self.cleaned_data.get("reminder_interval_minutes")
        interval = task.reminder_interval_minutes
        if interval and task.due_date and task.due_time:
            due_at = timezone.make_aware(
                datetime.combine(task.due_date, task.due_time), timezone.get_current_timezone()
            )
            task.reminder_at = due_at - timedelta(minutes=interval)
        elif previous_interval:
            task.reminder_at = None
        if commit:
            task.save(update_fields=("reminder_interval_minutes", "reminder_at", "notified_at", "updated_at"))
            if not task.recurring_template_id and task.recurrence == Task.Recurrence.NONE:
                RecurringSchedule.objects.filter(template=task).delete()
            elif not task.recurring_template_id:
                RecurringSchedule.objects.update_or_create(
                    template=task,
                    defaults={
                        "frequency": task.recurrence,
                        "weekdays": [int(day) for day in self.cleaned_data.get("weekdays", [])],
                        "starts_on": task.due_date or timezone.localdate(),
                    },
                )
        return task


class BulkTaskForm(forms.Form):
    titles = forms.CharField(
        label="Tasks",
        widget=forms.Textarea(attrs={"class": "form-control bulk-task-input", "rows": 7,
                                     "placeholder": "One task per line"}),
    )
    category = forms.CharField(required=False, max_length=80, widget=forms.TextInput(
        attrs={"class": "form-control", "placeholder": "e.g. Work"}
    ))
    priority = forms.ChoiceField(choices=Task.Priority.choices, initial=Task.Priority.NORMAL,
                                 widget=forms.Select(attrs={"class": "form-select"}))
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    due_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}))
    reminder_interval_minutes = forms.TypedChoiceField(
        required=False,
        coerce=int,
        empty_value=None,
        choices=(("", "No reminder"), (5, "5 minutes before"), (10, "10 minutes before"),
                 (15, "15 minutes before"), (30, "30 minutes before"), (60, "1 hour before")),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    deliverable_minutes = forms.IntegerField(
        required=False, min_value=1, max_value=1440,
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Minutes", "min": 1, "max": 1440}),
    )

    def clean_titles(self):
        titles = [line.strip() for line in self.cleaned_data["titles"].splitlines() if line.strip()]
        if not titles:
            raise forms.ValidationError("Enter at least one task.")
        if len(titles) > 100:
            raise forms.ValidationError("Add no more than 100 tasks at a time.")
        if any(len(title) > 200 for title in titles):
            raise forms.ValidationError("Each task title must be 200 characters or fewer.")
        return titles

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("reminder_interval_minutes") and not cleaned.get("due_time"):
            self.add_error("reminder_interval_minutes", "Add a due time to schedule an interval reminder.")
        return cleaned


class RestoreForm(forms.Form):
    backup = forms.FileField()

    def clean_backup(self):
        backup = self.cleaned_data["backup"]
        if backup.size > 50 * 1024 * 1024:
            raise forms.ValidationError("Backup files must be 50 MB or smaller.")
        if not backup.name.lower().endswith((".sqlite3", ".db")):
            raise forms.ValidationError("Choose a SQLite backup file (.sqlite3 or .db).")
        return backup
