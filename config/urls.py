from django.urls import path
from tasks import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("tasks/create/", views.create_task, name="create_task"),
    path("tasks/<int:task_id>/toggle/", views.toggle_task, name="toggle_task"),
    path("tasks/<int:task_id>/delete/", views.delete_task, name="delete_task"),
    path("export/", views.export_excel, name="export_excel"),
    path("backup/", views.backup_database, name="backup"),
    path("restore/", views.restore_database, name="restore"),
    path("pomodoro/", views.pomodoro, name="pomodoro"),
    path("pomodoro/<int:session_id>/finish/", views.finish_pomodoro, name="finish_pomodoro"),
    path("settings/", views.settings_view, name="settings"),
]
