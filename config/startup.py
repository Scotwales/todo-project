import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


def _copy_missing_files(source, destination):
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        target = destination / path.name
        if path.is_dir():
            _copy_missing_files(path, target)
        elif path.name in ("todo.sqlite3-wal", "todo.sqlite3-shm"):
            continue
        elif path.name == "todo.sqlite3" and not target.exists():
            temporary = target.with_name(f"{target.name}.migration.tmp")
            try:
                with closing(sqlite3.connect(str(path), timeout=20)) as source_database:
                    with closing(sqlite3.connect(str(temporary), timeout=20)) as target_database:
                        source_database.backup(target_database)
                        result = target_database.execute("PRAGMA integrity_check").fetchone()
                        if not result or result[0] != "ok":
                            raise RuntimeError(
                                f"Legacy database copy failed integrity validation: {result!r}"
                            )
                temporary.replace(target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        elif not target.exists():
            shutil.copy2(path, target)


def initialize_data_directories(data_dir, legacy_data_dir=None):
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("backups", "logs", "settings", "webview"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)

    if legacy_data_dir and legacy_data_dir != data_dir:
        _copy_missing_files(legacy_data_dir, data_dir)

    preferences_file = data_dir / "settings" / "preferences.json"
    if not preferences_file.exists():
        preferences_file.write_text("{}\n", encoding="utf-8")
    try:
        preferences = json.loads(preferences_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to read application settings at {preferences_file}: {error}") from error
    if not isinstance(preferences, dict):
        raise RuntimeError(f"Application settings at {preferences_file} must contain a JSON object.")


def validate_database_integrity(database_path):
    database_path = Path(database_path)
    if not database_path.exists() or database_path.stat().st_size == 0:
        return
    try:
        with closing(sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro", uri=True, timeout=20
        )) as database:
            result = database.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(f"SQLite integrity check failed for {database_path}: {result!r}")
            foreign_key_errors = database.execute("PRAGMA foreign_key_check").fetchone()
            if foreign_key_errors:
                raise RuntimeError(
                    f"SQLite foreign-key check failed for {database_path}: {foreign_key_errors!r}"
                )
    except sqlite3.DatabaseError as error:
        raise RuntimeError(f"Unable to validate the application database at {database_path}: {error}") from error


def backup_database_before_migration(database_path, backup_dir):
    database_path = Path(database_path)
    if not database_path.exists() or database_path.stat().st_size == 0:
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_dir / f"pre-migration-{stamp}.sqlite3"
    temporary = destination.with_suffix(".sqlite3.tmp")
    try:
        with closing(sqlite3.connect(str(database_path), timeout=20)) as source:
            with closing(sqlite3.connect(str(temporary), timeout=20)) as backup:
                source.backup(backup)
                result = backup.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError(f"Pre-migration backup failed integrity validation: {result!r}")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def run_startup_migrations(data_dir, backup_dir, legacy_data_dir=None):
    initialize_data_directories(Path(data_dir), legacy_data_dir)
    database_path = Path(connection.settings_dict["NAME"])
    existed_before_connection = database_path.exists() and database_path.stat().st_size > 0
    validate_database_integrity(database_path)

    executor = MigrationExecutor(connection)
    migration_plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if migration_plan and existed_before_connection:
        backup_database_before_migration(database_path, backup_dir)

    call_command("migrate", interactive=False, verbosity=0)
    validate_database_integrity(database_path)
    return bool(migration_plan)
