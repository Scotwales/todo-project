# Daily

A private, local-first todo list and daily checklist built with Django, SQLite, locally bundled Bootstrap and Chart.js, APScheduler, Plyer, PyWebView, and PyInstaller.

## Features

- Daily checklist with one-off tasks and daily, weekday, weekly, monthly, or selected-day recurrence
- Optional deliverable-time estimates used for workload, planning, and productivity analytics
- Bulk creation of up to 100 tasks with shared category, priority, due date/time, reminder, and estimate
- Recurring templates that generate unique, dated child occurrences locally
- Per-task Start/Pause/Stop time tracking and a daily planner that schedules estimated work around fixed due times
- Actionable in-app desktop reminders with Mark done and Extend controls (15/30/60/120 minutes, tomorrow, or custom)
- Extension history, completion rate, estimated/actual hours, and productivity score
- Optional local desktop notifications (when the OS notification backend is available)
- Monthly calendar, quick-add form, and completion analytics
- Excel export, SQLite backup, and validated backup restore
- Dark/light theme preference
- Persistent Pomodoro sessions
- Standalone Windows desktop app using PyWebView and a PyInstaller distribution
- Browser UI for development

All application data is stored locally outside the installation, at `%LOCALAPPDATA%\TodoManager\`. The desktop app does not need an account, hosted backend, or internet access. Application assets ship with the program; its database, backups, preferences, logs, and WebView profile remain in the per-user data folder across upgrades and uninstall.
The app uses the computer's local time zone by default. Set `TODO_TIME_ZONE` to an IANA time-zone name (for example, `Europe/London`) to override it. Reminder actions are available inside the app's desktop window; native Windows notification providers may not support interactive buttons.

## Windows desktop app

The supported packaged experience is a standalone Windows desktop window. Django runs in-process on a randomly assigned loopback-only port; no external server process or Python installation is required on the target computer. APScheduler starts before the window opens and stops cleanly when the app exits. Startup creates the local data folders, validates SQLite integrity, creates a verified backup before any pending migration, runs migrations, then validates the database again. The local reminder scheduler checks reminders and completed focus sessions every minute; recurring tasks are calculated from their rules when the local task views load.

### Build the Windows app

Build on Windows with Python 3.10 or later:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
.\build_exe.ps1
```

`build_exe.ps1` (also available through `build_exe.bat`) uses `Daily.spec` and `version.txt` to create a self-contained folder at `dist\Daily\`. The executable is `dist\Daily\Daily.exe`; Python and the application packages are bundled into that folder. If Inno Setup 6 is installed and `ISCC.exe` is on `PATH` or in its standard Windows install folder, the build script also creates the installer. Otherwise, build the folder first and run `build_installer.bat` after installing Inno Setup 6.

### Create the Windows installer

Install Inno Setup 6 on the build computer, build the PyInstaller distribution, then run:

```powershell
.\build_installer.bat
```

The Inno Setup definition is `installer\Daily.iss`; it creates `dist\installer\Daily-Setup-1.1.0.exe` and installs per-user under `%LOCALAPPDATA%\Programs\Daily`. The installer does not write application data beneath `{app}` and does not remove `%LOCALAPPDATA%\TodoManager` during upgrades or uninstall. The version resource is maintained in `version.txt`; the application About screen displays the version and build date embedded in each build.

### Install and run

1. Run `dist\installer\Daily-Setup-1.1.0.exe`, or copy the complete `dist\Daily` folder to a user-writable installation location.
2. On Windows installations without the Microsoft Edge WebView2 Runtime, install its Evergreen Standalone Runtime once. The desktop window uses this Windows webview runtime.
3. Launch `Daily.exe`. No Python installation, sign-in, network service, or separate database setup is required.
4. To remove the application, uninstall it or delete the installed `Daily` folder. User data is retained in `%LOCALAPPDATA%\TodoManager`; remove that folder separately only if you explicitly want to erase the database, settings, logs, WebView profile, and backups. Existing data from the previous `%LOCALAPPDATA%\Daily\instances\<installation-id>` layout is copied into the new folder at startup and is not deleted.

The source checkout can still be run for development with Python and `.\run.bat` (browser) or `.\run-desktop.bat` (PyWebView). The packaged executable is the standalone, no-Python-required distribution.

On macOS/Linux, create and activate a virtual environment, install `requirements.txt`, and run `python manage.py migrate` followed by `python manage.py runserver 127.0.0.1:8000`.

## Development and checks

```powershell
python manage.py migrate
python manage.py check
python manage.py test
```

`start_app.py` applies database migrations, starts APScheduler (including an immediate notification check and recurring reminder/focus-session checks), starts a threaded Django WSGI server on a free loopback port, and opens the PyWebView window. The scheduler is shut down when the desktop window closes. Recurring child occurrences are generated idempotently through a rolling 30-day horizon; task, calendar, and planner views generate any additional dates they need. Templates remain single rows, while each dated occurrence has its own completion and extension history.

`Daily.spec` collects Django templates, local assets, migrations, PyWebView, notifications, scheduler dependencies, the Windows version resource, and a build-date stamp for PyInstaller. UI assets are shipped in `static\vendor`; the desktop app makes no CDN requests. The stable per-user data layout is `%LOCALAPPDATA%\TodoManager\todo.sqlite3`, `backups\`, `settings\`, `logs\`, and `webview\`. Both requested build scripts and the Inno Setup installer definition are included with the source. Backups remain on the computer and can also be downloaded or restored from Settings. The About screen and release notes are available from the sidebar.

## Product experience

The interface uses a focused desktop workspace and a compact mobile layout:

```text
Desktop (260 px sidebar)                 Mobile
┌────────────┬───────────────────────┐   ┌──────────────────────┐
│ Today      │ Search       Date     │   │ Daily       Search   │
│ Calendar   ├───────────────────────┤   ├──────────────────────┤
│ All tasks  │ Today’s focus         │   │ Today’s focus        │
│ Focus      │ Progress              │   │ Progress             │
│            │ Quick add             │   │ Quick add            │
│ Progress   │ Task cards   Details  │   │ Task cards           │
│ Settings   │ Focus + weekly chart  │   │ Details / Focus      │
└────────────┴───────────────────────┘   ├──────────────────────┤
                                         │ Today Tasks Focus ... │
                                         └──────────────────────┘
```

- **Task journeys:** add a task inline and press Enter/submit; complete it with one tap; select a card to inspect or edit its schedule, priority, recurrence, notes, and reminder; duplicate or delete it from the card. Search filters the visible Today list, and `Ctrl/⌘ K` focuses search.
- **Planning journeys:** quick-add tasks inline or create a batch with shared settings. Use the daily planner to see due-time tasks placed backward by their estimated duration and flexible tasks arranged from 9:00 AM around fixed appointments. Tasks without an estimate use a 30-minute planner block. The monthly calendar shows dated occurrences and priority badges.
- **Measurement:** Today’s remaining workload sums `Deliverable Time` for incomplete tasks. Start/Pause/Stop timers record actual time per task and sessions spanning midnight are attributed to each local day. Productivity analytics count tasks due in the selected period; the score is completion rate multiplied by estimated-to-actual time efficiency, capped at 100. Unestimated work is excluded from estimated hours.
- **Recurring-series edits:** changing a series updates incomplete future occurrences; dates removed from the rule are marked cancelled rather than deleted so extension and time-entry history remains intact. Selecting “Does not repeat” ends the series and cancels its future incomplete children.
- **Appearance journey:** switch light/dark from the sidebar, or choose light, dark, or system appearance in Settings. The theme is saved locally in the browser and by the existing settings preference.
- **Components:** workspace sidebar and mobile navigation, search field, progress indicator, inline task composer, task cards, contextual details panel, priority badges, calendar cells, focus-session widget, weekly chart, and dismissing status toasts. Bootstrap 5 provides form controls and layout utilities; `static/tasks/app.css` owns the product components and tokens.
- **Palette:** page `#F7F8FC`, surface `#FFFFFF`, text `#25263A`, muted text `#6D7184`, divider `#ECECF3`, indigo accent `#655DC9`; high priority uses soft red, medium uses soft amber, and low uses soft green. Dark mode uses `#111827` page, `#1F2937` surfaces, `#F9FAFB` text, and `#3B82F6` accent.
- **Typography:** system sans-serif stack; display heading 29–36 px with tight tracking, section heading 19 px, task title 14 px, and supporting labels 10–13 px. The type scale and color tokens are declared at the top of `static/tasks/app.css`.
- **Responsive and accessibility:** desktop sidebar collapses below tablet width; mobile receives a five-item bottom bar. Layout reflows to one column on narrow screens. Controls have labels, visible keyboard focus, semantic progress values, and reduced-motion support.

The daily checklist and productivity views use the persisted task, occurrence, estimate, extension, and timer records. Drag-and-drop scheduling, checklist collections/subtasks, and a completion heatmap are not included.

## Data and privacy

Tasks, preferences, and Pomodoro sessions are stored in the installation-specific local SQLite file. **Settings → Save & download backup** creates a dated SQLite backup in that installation's local `backups` folder as well as downloading a copy. Use **Restore** to load an earlier backup; restore validates the uploaded database before replacing current data. Keep backups private: they contain all task data. Separate installation folders have distinct data directories and do not share tasks or browser profiles.

The packaged desktop app binds to loopback by default and does not implement multi-user authentication; it is intended for one local user, not exposure to a network. Moving an installation to a different folder creates a separate data directory by design; use a local backup and restore it into the relocated installation if you want to transfer that installation's data.
