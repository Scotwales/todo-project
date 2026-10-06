# Daily

A private, local-first todo list and daily checklist built with Django, SQLite, Bootstrap 5, APScheduler, Plyer, PyWebView, and Chart.js.

## Features

- Daily checklist with one-off and daily, weekly, or monthly recurring tasks
- Due dates, due times, priorities, and scheduled reminders
- Optional local desktop notifications (when the OS notification backend is available)
- Monthly calendar, quick-add form, and completion analytics
- Excel export, SQLite backup, and validated backup restore
- Dark/light theme preference
- Persistent Pomodoro sessions
- Responsive browser UI and optional PyWebView desktop window

All application data is stored locally in `data/todo.sqlite3`. No account or remote application server is required. The Bootstrap and Chart.js browser assets are loaded from public CDNs, so those visual libraries require an internet connection; core task actions remain available if the CDN is unavailable.
The app uses the computer's local time zone by default. Set `TODO_TIME_ZONE` to an IANA time-zone name (for example, `Europe/London`) to override it.

## Requirements

- Python 3.10 or later (Python 3.14 is supported by current dependencies)
- Optional: a graphical desktop session and PyWebView-supported webview runtime

## Install and run (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\run.bat
```

Then open http://127.0.0.1:8000. To open the desktop window instead, run `.\run-desktop.bat` (PyWebView is included in the default dependencies).

On macOS/Linux, create and activate a virtual environment, install `requirements.txt`, and run `python manage.py migrate` followed by `python manage.py runserver 127.0.0.1:8000`.

## Development and checks

```powershell
python manage.py migrate
python manage.py check
python manage.py test
```

The scheduler runs in the Django server process. For a stable single scheduler, start the server with the provided scripts or use one server worker; avoid running multiple server processes against the same local notification queue.

## Data and privacy

Tasks, preferences, and Pomodoro sessions are stored in the local SQLite file. Back up from **Settings → Backup** or use **Restore** to load an earlier backup. Restore validates the uploaded database before replacing the current database. Keep backups private: they contain all task data.

The app binds to loopback by default and does not implement multi-user authentication; it is intended for one local user, not exposure to a network.
