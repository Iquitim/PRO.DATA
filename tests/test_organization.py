"""Spec 034: organização da vista Dados (pastas, nome de exibição, descrição, fixadas)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prodata.errors import InvalidInputError, NotFoundError
from prodata.services.organization import OrganizationStore, SourceChanges


@pytest.fixture
def store(tmp_path: Path) -> OrganizationStore:
    return OrganizationStore(tmp_path / "organizacao.json")


def test_folder_groups_sources_of_any_kind(store: OrganizationStore) -> None:
    org = store.add_folder("Numerário", "verde")
    fid = org.folders[0].id
    keys = ["file:extrato.xlsx", "query:abc", "api:x1"]
    org = store.change_sources(keys, SourceChanges(folder=fid))
    assert {k for k, v in org.sources.items() if v.folder == fid} == set(keys)
    # O arquivo sobrevive a um novo store (é o que o app lê na próxima abertura).
    assert OrganizationStore(store.path).get() == org


def test_folder_names_are_unique_and_cleaned(store: OrganizationStore) -> None:
    store.add_folder("  Vendas \n  2026 ")
    assert store.get().folders[0].name == "Vendas 2026"
    with pytest.raises(InvalidInputError):
        store.add_folder("vendas 2026")
    with pytest.raises(Exception, match="nome"):
        store.add_folder("   ")


def test_deleting_a_folder_keeps_the_sources(store: OrganizationStore) -> None:
    fid = store.add_folder("Temporária").folders[0].id
    store.change_sources(["file:a.csv"], SourceChanges(folder=fid, label="Base A"))
    org = store.delete_folder(fid)
    assert org.folders == []
    assert org.sources["file:a.csv"].folder == ""
    assert org.sources["file:a.csv"].label == "Base A"


def test_empty_entries_disappear_and_partial_change_keeps_the_rest(store: OrganizationStore) -> None:
    store.change_sources(["file:a.csv"], SourceChanges(label="Base A", description="Linha 1\nLinha 2"))
    org = store.change_sources(["file:a.csv"], SourceChanges(pinned=True))
    info = org.sources["file:a.csv"]
    assert (info.label, info.description, info.pinned) == ("Base A", "Linha 1\nLinha 2", True)
    org = store.change_sources(["file:a.csv"], SourceChanges(label="", description="", pinned=False))
    assert "file:a.csv" not in org.sources


def test_unknown_keys_and_folders_are_refused(store: OrganizationStore) -> None:
    with pytest.raises(InvalidInputError):
        store.change_sources(["outra:coisa"], SourceChanges(pinned=True))
    with pytest.raises(NotFoundError):
        store.change_sources(["file:a.csv"], SourceChanges(folder="naoexiste"))


def test_forget_and_move_folder(store: OrganizationStore) -> None:
    store.add_folder("A")
    store.add_folder("B")
    b = store.get().folders[1].id
    assert [f.name for f in store.move_folder(b, 0).folders] == ["B", "A"]
    store.change_sources(["const:taxa"], SourceChanges(owner="Ana"))
    assert store.forget(["const:taxa"]).sources == {}


def test_broken_file_starts_empty(store: OrganizationStore) -> None:
    store.path.write_text("{ quebrado", encoding="utf-8")
    assert store.get().folders == []


def test_control_characters_never_reach_the_screen(store: OrganizationStore) -> None:
    org = store.change_sources(["file:a.csv"], SourceChanges(label="Base\x00\x1b[31m A", owner="Ana\tLima"))
    assert org.sources["file:a.csv"].label == "Base[31m A"
    assert org.sources["file:a.csv"].owner == "Ana Lima"


def test_routes(client: TestClient) -> None:
    assert client.get("/api/organization").json() == {"folders": [], "sources": {}}
    org = client.post("/api/organization/folders", json={"name": "Numerário", "color": "ambar"}).json()
    fid = org["folders"][0]["id"]
    org = client.put(
        "/api/organization/sources",
        json={"keys": ["file:extrato.xlsx"], "changes": {"folder": fid, "label": "Extrato"}},
    ).json()
    assert org["sources"]["file:extrato.xlsx"]["label"] == "Extrato"
    org = client.put(f"/api/organization/folders/{fid}", json={"name": "Caixa", "color": "roxo"}).json()
    assert org["folders"][0] == {"id": fid, "name": "Caixa", "color": "roxo"}
    assert client.post("/api/organization/folders", json={"name": "X", "color": "rosa"}).status_code == 422
    assert client.delete("/api/organization/folders/naoexiste").status_code == 404
    org = client.post("/api/organization/sources/forget", json={"keys": ["file:extrato.xlsx"]}).json()
    assert org["sources"] == {}
    assert client.delete(f"/api/organization/folders/{fid}").json()["folders"] == []
