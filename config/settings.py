import hashlib
import os
import secrets
import sys
from pathlib import Path
from tzlocal import get_localzone_name

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
if os.environ.get("TODO_DATA_DIR"):
    DATA_DIR = Path(os.environ["TODO_DATA_DIR"]).expanduser().resolve()
elif os.name == "nt":
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    DATA_DIR = local_app_data / "TodoManager"
else:
    DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"
SETTINGS_DIR = DATA_DIR / "settings"
WEBVIEW_DIR = DATA_DIR / "webview"

if os.name == "nt" and not os.environ.get("TODO_DATA_DIR"):
    install_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    instance_id = hashlib.sha256(os.path.normcase(str(install_root)).encode("utf-8")).hexdigest()[:16]
    LEGACY_DATA_DIR = (
        Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        / "Daily" / "instances" / instance_id
    )
else:
    LEGACY_DATA_DIR = None

for directory in (DATA_DIR, BACKUP_DIR, LOG_DIR, SETTINGS_DIR, WEBVIEW_DIR):
    directory.mkdir(parents=True, exist_ok=True)
PREFERENCES_FILE = SETTINGS_DIR / "preferences.json"

secret_path = SETTINGS_DIR / ".secret_key"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    try:
        SECRET_KEY = secret_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        legacy_secret_path = LEGACY_DATA_DIR / ".secret_key" if LEGACY_DATA_DIR else None
        if legacy_secret_path and not legacy_secret_path.is_file():
            legacy_secret_path = LEGACY_DATA_DIR / "settings" / ".secret_key"
        if legacy_secret_path and legacy_secret_path.is_file():
            SECRET_KEY = legacy_secret_path.read_text(encoding="utf-8")
            try:
                with secret_path.open("x", encoding="utf-8") as secret_file:
                    secret_file.write(SECRET_KEY)
            except FileExistsError:
                pass
        else:
            try:
                with secret_path.open("x", encoding="utf-8") as secret_file:
                    secret_file.write(secrets.token_urlsafe(64))
            except FileExistsError:
                pass
            SECRET_KEY = secret_path.read_text(encoding="utf-8")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tasks.apps.TasksConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.messages.context_processors.messages",
        "config.context_processors.application_context",
    ]},
}]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.environ.get("TODO_DATABASE", DATA_DIR / "todo.sqlite3")),
        "OPTIONS": {"timeout": 20},
    }
}
Path(DATABASES["default"]["NAME"]).parent.mkdir(parents=True, exist_ok=True)
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TODO_TIME_ZONE") or get_localzone_name()
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
