from django.urls import path
from django.views.static import serve
from django.conf import settings
from tasks import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("tasks/create/", views.create_task, name="create_task"),
    path("tasks/<int:task_id>/update/", views.update_task, name="update_task"),
    path("tasks/<int:task_id>/duplicate/", views.duplicate_task, name="duplicate_task"),
    path("tasks/<int:task_id>/timer/<str:action>/", views.task_timer, name="task_timer"),
    path("tasks/<int:task_id>/extend/", views.extend_task, name="extend_task"),
    path("notifications/pending/", views.pending_notifications, name="pending_notifications"),
    path("notifications/<int:notification_id>/<str:action>/", views.notification_action, name="notification_action"),
    path("notifications/<int:notification_id>/dismiss/", views.dismiss_notification, name="dismiss_notification"),
    path("bulk-create/", views.bulk_create, name="bulk_create"),
    path("planner/", views.daily_planner, name="planner"),
    path("analytics/", views.analytics, name="analytics"),
    path("about/", views.about, name="about"),
    path("tasks/<int:task_id>/toggle/", views.toggle_task, name="toggle_task"),
    path("tasks/<int:task_id>/delete/", views.delete_task, name="delete_task"),
    path("export/", views.export_excel, name="export_excel"),
    path("backup/", views.backup_database, name="backup"),
    path("restore/", views.restore_database, name="restore"),
    path("pomodoro/", views.pomodoro, name="pomodoro"),
    path("pomodoro/<int:session_id>/finish/", views.finish_pomodoro, name="finish_pomodoro"),
    path("settings/", views.settings_view, name="settings"),
    path("static/<path:path>", serve, {"document_root": settings.BASE_DIR / "static"}),
]
