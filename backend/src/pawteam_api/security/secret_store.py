"""Encrypted, file-backed storage for provider credentials."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from pawteam_api.config import Settings


class SecretNotFoundError(KeyError):
    """Raised when a requested secret reference does not exist."""


class SecretStoreError(RuntimeError):
    """Raised when encrypted secret material cannot be read safely."""


class SecretStore:
    """Keep plaintext API keys out of SQLite and ordinary API responses.

    For local development, a generated master key is stored beside the encrypted
    secret files with restrictive permissions. Production deployments should pass
    ``PAWTEAM_SECRET_KEY`` so the encryption key is managed outside the data volume.
    """

    def __init__(self, settings: Settings) -> None:
        self.directory = settings.secrets_dir.resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._harden_permissions(self.directory, 0o700)
        self._fernet = Fernet(self._load_or_create_key(settings))

    def set(self, reference: str, plaintext: str) -> None:
        if not plaintext:
            raise ValueError("Secret value cannot be empty")
        path = self._path_for(reference)
        path.write_bytes(self._fernet.encrypt(plaintext.encode("utf-8")))
        self._harden_permissions(path, 0o600)

    def get(self, reference: str) -> str:
        path = self._path_for(reference)
        if not path.exists():
            raise SecretNotFoundError(reference)
        try:
            return self._fernet.decrypt(path.read_bytes()).decode("utf-8")
        except InvalidToken as exc:
            raise SecretStoreError(
                "Secret cannot be decrypted with the active key"
            ) from exc

    def delete(self, reference: str) -> None:
        path = self._path_for(reference)
        path.unlink(missing_ok=True)

    def exists(self, reference: str) -> bool:
        return self._path_for(reference).is_file()

    def _load_or_create_key(self, settings: Settings) -> bytes:
        if settings.secret_key is not None:
            return settings.secret_key.get_secret_value().encode("ascii")

        key_path = self.directory / ".master.key"
        if key_path.exists():
            return key_path.read_bytes().strip()

        key = Fernet.generate_key()
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return key_path.read_bytes().strip()
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(key)
        return key

    def _path_for(self, reference: str) -> Path:
        valid_reference = reference and all(
            character.isalnum() or character in "-_" for character in reference
        )
        if not valid_reference:
            raise ValueError("Invalid secret reference")
        return self.directory / f"{reference}.secret"

    @staticmethod
    def _harden_permissions(path: Path, mode: int) -> None:
        if os.name == "posix":
            path.chmod(mode)
