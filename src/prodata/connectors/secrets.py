"""Armazenamento de senhas. Em produção: cofre do sistema (Windows Credential Manager,
macOS Keychain, Secret Service). Em testes: memória."""

from __future__ import annotations

import contextlib
import secrets
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "PRODATA"


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


INSTALLATION_KEY = "instalacao:mask"


def installation_key(store: SecretStore) -> bytes:
    """Chave deste computador para o código estável do Mask (spec 033). Nasce no primeiro uso e fica no cofre."""
    saved = store.get(INSTALLATION_KEY)
    if not saved:
        saved = secrets.token_hex(32)
        store.set(INSTALLATION_KEY, saved)
    return bytes.fromhex(saved)


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
