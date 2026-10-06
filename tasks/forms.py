from django import forms
from django.utils import timezone
from .models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ("title", "notes", "due_date", "due_time", "reminder_at", "recurrence", "priority")
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "maxlength": 200, "placeholder": "What needs doing?"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Notes (optional)"}),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "due_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "reminder_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "recurrence": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_reminder_at(self):
        value = self.cleaned_data.get("reminder_at")
        if value and timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        if value and value < timezone.now():
            raise forms.ValidationError("Choose a reminder time in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("due_date"):
            cleaned["due_date"] = timezone.localdate()
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
