"""Armazenamento de senhas. Em produção: cofre do sistema (Windows Credential Manager,
macOS Keychain, Secret Service). Em testes: memória."""

from __future__ import annotations

import contextlib
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "PRODATA"


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class KeyringSecretStore:
    def get(self, key: str) -> str | None:
        return keyring.get_password(SERVICE, key)

    def set(self, key: str, value: str) -> None:
        keyring.set_password(SERVICE, key, value)

    def delete(self, key: str) -> None:
        # Se já não existia, o estado desejado (sem segredo) foi atingido.
        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(SERVICE, key)


class MemorySecretStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
