from pathlib import Path

from django.conf import settings

APP_NAME = "Daily"
APP_VERSION = "1.1.0"

_build_date_file = Path(settings.BASE_DIR) / "build_date.txt"
BUILD_DATE = (
    _build_date_file.read_text(encoding="utf-8").strip()
    if _build_date_file.is_file()
    else "Development build"
)

RELEASE_NOTES = (
    {
        "version": APP_VERSION,
        "title": "Planning and desktop release improvements",
        "changes": (
            "Plan multiple tasks with shared settings and deliverable-time estimates.",
            "Schedule recurring tasks and track actual time, extensions, and productivity.",
            "Keep application data in the per-user TodoManager folder and back it up before migrations.",
        ),
    },
)
