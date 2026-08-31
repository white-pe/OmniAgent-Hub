"""Consistent SQLite/data backup and offline restore commands."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from pawteam_api.config import Settings, get_settings

ARCHIVE_ROOT = "pawteam-backup"


def database_path(settings: Settings) -> Path:
    url = make_url(settings.database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        raise RuntimeError(
            "Backup currently supports only a file-based SQLite database"
        )
    return Path(url.database).resolve()


def create_backup(settings: Settings, output: Path) -> Path:
    source_db = database_path(settings)
    if not source_db.is_file():
        raise RuntimeError(f"Database does not exist: {source_db}")
    output_path = _archive_path(output, "pawteam")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pawteam-backup-") as temp_name:
        root = Path(temp_name) / ARCHIVE_ROOT
        root.mkdir()
        _snapshot_sqlite(source_db, root / "app.db")
        _copy_optional_tree(settings.workspaces_dir, root / "workspaces")
        _copy_optional_tree(settings.secrets_dir, root / "secrets")
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "app_version": settings.version,
            "contents": ["app.db", "workspaces", "secrets"],
            "note": "PAWTEAM_SECRET_KEY is external and is never stored here.",
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_archive = output_path.with_suffix(output_path.suffix + ".tmp")
        with tarfile.open(temporary_archive, "w:gz") as archive:
            archive.add(root, arcname=ARCHIVE_ROOT)
        temporary_archive.replace(output_path)

    verify_backup(output_path)
    return output_path


def verify_backup(archive_path: Path) -> dict[str, object]:
    with tarfile.open(archive_path, "r:gz") as archive:
        names = set(archive.getnames())
        required = {
            f"{ARCHIVE_ROOT}/manifest.json",
            f"{ARCHIVE_ROOT}/app.db",
        }
        if not required.issubset(names):
            raise RuntimeError("Archive is missing its manifest or SQLite snapshot")
        _validate_members(archive)
        manifest_file = archive.extractfile(f"{ARCHIVE_ROOT}/manifest.json")
        if manifest_file is None:
            raise RuntimeError("Cannot read backup manifest")
        return json.loads(manifest_file.read())


def restore_backup(settings: Settings, archive_path: Path, force: bool) -> Path:
    if not force:
        raise RuntimeError(
            "Restore is destructive; repeat with --force while services are down"
        )
    manifest = verify_backup(archive_path)
    output_dir = archive_path.resolve().parent
    safety_backup = create_backup(settings, output_dir / "pre-restore")

    with tempfile.TemporaryDirectory(prefix="pawteam-restore-") as temp_name:
        temp = Path(temp_name)
        with tarfile.open(archive_path, "r:gz") as archive:
            _validate_members(archive)
            archive.extractall(temp)
        restored = temp / ARCHIVE_ROOT
        source_db = restored / "app.db"
        target_db = database_path(settings)
        target_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_db, target_db)
        _replace_tree(restored / "workspaces", settings.workspaces_dir)
        _replace_tree(restored / "secrets", settings.secrets_dir)

    print(f"Restored backup format {manifest['format']}; safety copy: {safety_backup}")
    return safety_backup


def _snapshot_sqlite(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(target) as target_connection:
            source_connection.backup(target_connection)


def _copy_optional_tree(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copytree(source, target)
    else:
        target.mkdir()


def _replace_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _validate_members(archive: tarfile.TarFile) -> None:
    root = Path(ARCHIVE_ROOT)
    for member in archive.getmembers():
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts or root not in path.parents:
            if path != root:
                raise RuntimeError(f"Unsafe archive member: {member.name}")
        if member.issym() or member.islnk():
            raise RuntimeError(f"Archive links are not allowed: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(f"Unsupported archive member: {member.name}")


def _archive_path(output: Path, prefix: str) -> Path:
    if (output.exists() and output.is_dir()) or not output.suffix:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return output / f"{prefix}-{timestamp}.tar.gz"
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="PawTeam backup utility")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--force", action="store_true")
    arguments = parser.parse_args()
    settings = get_settings()

    if arguments.command == "create":
        print(create_backup(settings, arguments.output))
    elif arguments.command == "verify":
        print(
            json.dumps(
                verify_backup(arguments.archive), ensure_ascii=False, indent=2
            )
        )
    else:
        restore_backup(settings, arguments.archive, arguments.force)


if __name__ == "__main__":
    main()
