import sqlite3
from pathlib import Path

from pawteam_api.backup import create_backup, restore_backup, verify_backup
from pawteam_api.config import Settings


def test_backup_verify_and_offline_restore(tmp_path: Path) -> None:
    data = tmp_path / "data"
    database = data / "app.db"
    workspace = data / "workspaces" / "agent-1"
    secrets = data / "secrets"
    workspace.mkdir(parents=True)
    secrets.mkdir(parents=True)
    (workspace / "PROFILE.md").write_text("original", encoding="utf-8")
    (secrets / "provider.secret").write_text("encrypted", encoding="utf-8")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('original')")

    settings = Settings(
        environment="test",
        data_dir=data,
        workspaces_dir=data / "workspaces",
        secrets_dir=data / "secrets",
        database_url=f"sqlite+aiosqlite:///{database}",
    )
    archive = create_backup(settings, tmp_path / "backups")
    assert verify_backup(archive)["app_version"] == "1.0.0"

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sample SET value = 'changed'")
    (workspace / "PROFILE.md").write_text("changed", encoding="utf-8")

    safety_backup = restore_backup(settings, archive, force=True)
    assert safety_backup.is_file()
    with sqlite3.connect(database) as connection:
        value = connection.execute("SELECT value FROM sample").fetchone()[0]
    assert value == "original"
    assert (workspace / "PROFILE.md").read_text(encoding="utf-8") == "original"
