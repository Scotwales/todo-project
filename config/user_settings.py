import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.conf import settings


def read_preferences():
    if not settings.PREFERENCES_FILE.exists():
        return {}
    try:
        value = json.loads(settings.PREFERENCES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to read application settings: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("Application settings must contain a JSON object.")
    return value


def save_preferences(preferences):
    settings.PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=settings.PREFERENCES_FILE.parent,
            prefix="preferences-", suffix=".tmp", delete=False,
        ) as temporary:
            json.dump(preferences, temporary, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, settings.PREFERENCES_FILE)
    except OSError as error:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise RuntimeError(f"Unable to save application settings: {error}") from error
