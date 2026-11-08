"""Cadastro de APIs: definições em JSON e segredos no cofre do sistema (spec 021)."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from prodata.connectors.api_model import ApiInfo, SavedApi
from prodata.connectors.secrets import SecretStore
from prodata.errors import NotFoundError


def secret_key(api_id: str, slot: str) -> str:
    return f"api:{api_id}:{slot}"


class ApiStore:
    def __init__(self, path: Path, secrets: SecretStore) -> None:
        self.path = path
        self.secrets = secrets
        self._lock = threading.Lock()

    def _read(self) -> dict[str, SavedApi]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {item["id"]: SavedApi.model_validate(item) for item in raw}

    def _write(self, items: dict[str, SavedApi]) -> None:
        tmp = self.path.with_suffix(".tmp")
        data = [a.model_dump(mode="json") for a in sorted(items.values(), key=lambda a: a.name.lower())]
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _info(self, api: SavedApi) -> ApiInfo:
        slots = api.secret_slots()
        has = {s for s in slots if self.secrets.get(secret_key(api.id, s))}
        return ApiInfo(
            **api.model_dump(), set_secrets=sorted(has), missing_secrets=[s for s in slots if s not in has]
        )

    def list(self) -> list[ApiInfo]:
        return [self._info(a) for a in self._read().values()]

    def get(self, api_id: str) -> SavedApi:
        api = self._read().get(api_id)
        if api is None:
            raise NotFoundError(f"API não encontrada: {api_id}. Ela foi excluída da vista Dados?")
        return api

    def secret_reader(self, api_id: str, typed: dict[str, str] | None = None) -> Callable[[str], str | None]:
        """Lê o segredo do cofre. ``typed``: digitado agora no editor, ainda não salvo."""

        def read(slot: str) -> str | None:
            if typed and typed.get(slot):
                return typed[slot]
            return self.secrets.get(secret_key(api_id, slot)) if api_id else None

        return read

    def save(self, api: SavedApi, secrets: dict[str, str] | None = None) -> ApiInfo:
        """Salva a definição. Segredo ausente fica como está; vazio remove."""
        api = api.model_copy(
            update={
                "params": [p.model_copy(update={"value": ""}) if p.secret else p for p in api.params],
                "headers": [p.model_copy(update={"value": ""}) if p.secret else p for p in api.headers],
            }
        )
        with self._lock:
            items = self._read()
            before = items.get(api.id)
            items[api.id] = api
            self._write(items)
        slots = api.secret_slots()
        for slot, value in (secrets or {}).items():
            if slot not in slots:
                continue
            if value:
                self.secrets.set(secret_key(api.id, slot), value)
            else:
                self.secrets.delete(secret_key(api.id, slot))
        if before:
            for slot in set(before.secret_slots()) - set(slots):
                self.secrets.delete(secret_key(api.id, slot))
        return self._info(api)

    def delete(self, api_id: str) -> None:
        with self._lock:
            items = self._read()
            api = items.pop(api_id, None)
            if api is None:
                raise NotFoundError(f"API não encontrada: {api_id}")
            self._write(items)
        for slot in api.secret_slots():
            self.secrets.delete(secret_key(api_id, slot))
