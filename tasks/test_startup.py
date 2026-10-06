import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from config.startup import (
    backup_database_before_migration,
    initialize_data_directories,
    run_startup_migrations,
    validate_database_integrity,
)


class StartupDataTests(SimpleTestCase):
    def test_data_directories_are_created_and_legacy_files_are_copied_not_moved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "legacy"
            legacy.mkdir()
            legacy_database_path = legacy / "todo.sqlite3"
            database = sqlite3.connect(legacy_database_path)
            database.execute("PRAGMA journal_mode=WAL")
            database.execute("PRAGMA wal_autocheckpoint=0")
            database.execute("CREATE TABLE saved_data (value TEXT)")
            database.execute("INSERT INTO saved_data VALUES ('old-database')")
            database.commit()
            (legacy / "backups").mkdir()
            (legacy / "backups" / "old.sqlite3").write_bytes(b"old-backup")
            current = root / "TodoManager"

            try:
                initialize_data_directories(current, legacy)
            finally:
                database.close()

            with closing(sqlite3.connect(current / "todo.sqlite3")) as database:
                self.assertEqual(
                    database.execute("SELECT value FROM saved_data").fetchone()[0], "old-database"
                )
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertTrue(legacy_database_path.exists())
            self.assertTrue((current / "backups" / "old.sqlite3").exists())
            self.assertTrue((current / "settings" / "preferences.json").exists())
            self.assertTrue((current / "logs").is_dir())
            self.assertTrue((current / "webview").is_dir())

    def test_pre_migration_backup_is_a_valid_sqlite_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "todo.sqlite3"
            with closing(sqlite3.connect(source_path)) as source:
                source.execute("CREATE TABLE sample (value TEXT)")
                source.execute("INSERT INTO sample VALUES ('preserved')")
                source.commit()
            backup = backup_database_before_migration(source_path, root / "backups")

            self.assertIsNotNone(backup)
            with closing(sqlite3.connect(backup)) as database:
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "preserved")

    def test_integrity_validation_rejects_non_sqlite_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            invalid_database = Path(temporary) / "todo.sqlite3"
            invalid_database.write_text("not a sqlite database", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Unable to validate"):
                validate_database_integrity(invalid_database)

    def test_startup_creates_verified_backup_before_applying_pending_migrations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "todo.sqlite3"
            with closing(sqlite3.connect(database_path)) as database:
                database.execute("CREATE TABLE previous_data (value TEXT)")
                database.execute("INSERT INTO previous_data VALUES ('keep')")
                database.commit()

            executor = SimpleNamespace(
                loader=SimpleNamespace(graph=SimpleNamespace(leaf_nodes=lambda: ["leaf"])),
                migration_plan=lambda targets: [("pending", False)],
            )
            migration_observed_backup = []

            def apply_migrations(*args, **kwargs):
                backups = list((root / "backups").glob("pre-migration-*.sqlite3"))
                migration_observed_backup.append(bool(backups))
                with closing(sqlite3.connect(backups[0])) as backup:
                    self.assertEqual(
                        backup.execute("SELECT value FROM previous_data").fetchone()[0], "keep"
                    )

            with (
                patch("config.startup.connection", SimpleNamespace(
                    settings_dict={"NAME": str(database_path)}
                )),
                patch("config.startup.MigrationExecutor", return_value=executor),
                patch("config.startup.call_command", side_effect=apply_migrations),
            ):
                run_startup_migrations(root / "data", root / "backups")

            self.assertEqual(migration_observed_backup, [True])
