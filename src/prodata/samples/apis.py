"""APIs públicas de exemplo (spec 022): sem chave e sem segredo, cada uma mostra um caso."""

from __future__ import annotations

from typing import Any

from prodata.connectors.api import ApiPagination, ApiParam, ApiStore, SavedApi

IBGE = "https://servicodados.ibge.gov.br/api"
ESTADOS_ID = "exemplo_ibge_estados"
MUNICIPIOS_ID = "exemplo_ibge_municipios"


def _estados() -> SavedApi:
    return SavedApi(
        id=ESTADOS_ID,
        name="Estados do Brasil (IBGE)",
        url=f"{IBGE}/v1/localidades/estados",
        params=[ApiParam(name="orderBy", value="nome")],
        hold_on_open=True,
        cache_results=True,  # uma chamada basta: o exemplo não precisa repetir a cada execução
    )


def _municipios() -> SavedApi:
    return SavedApi(
        id=MUNICIPIOS_ID,
        name="Municípios de um estado (IBGE)",
        url=f"{IBGE}/v1/localidades/estados/{{sigla}}/municipios",
        params=[ApiParam(name="view", value="nivelado")],
        hold_on_open=True,
        cache_results=True,  # uma chamada basta: o exemplo não precisa repetir a cada execução
    )


def seed_example_apis(store: ApiStore) -> None:
    """Cadastra as APIs do fluxo de demonstração, sem mexer em nada que já exista."""
    known = {a.id for a in store.list()}
    for source in (_estados(), _municipios()):
        if source.id not in known:
            store.save(source)


def editor_examples() -> list[dict[str, Any]]:
    """Pontos de partida do cadastro de API."""
    noticias = SavedApi(
        id="exemplo_ibge_noticias",
        name="Notícias do IBGE",
        url=f"{IBGE}/v3/noticias/",
        records_path="items",
        pagination=ApiPagination(type="page", page_param="page", size_param="qtd", page_size=20, max_pages=3),
    )
    feriados = SavedApi(
        id="exemplo_feriados", name="Feriados nacionais", url="https://brasilapi.com.br/api/feriados/v1/{ano}"
    )
    cep = SavedApi(id="exemplo_cep", name="Endereço por CEP", url="https://viacep.com.br/ws/{cep}/json/")
    entries: list[tuple[str, str, SavedApi, dict[str, str]]] = [
        ("Lista simples", "A resposta já é uma lista: cada item vira uma linha.", _estados(), {}),
        (
            "Uma chamada por linha",
            "{sigla} recebe o valor de uma coluna: é o caso do API Loop.",
            _municipios(),
            {"sigla": "RR"},
        ),
        (
            "Resposta com paginação",
            'As linhas ficam dentro de "items", e os dados vêm em páginas.',
            noticias,
            {},
        ),
        (
            "Coluna no endereço",
            "{ano} vem de uma coluna; os feriados de cada ano viram linhas.",
            feriados,
            {"ano": "2026"},
        ),
        (
            "Um registro só",
            "A resposta é um objeto: vira uma linha, com um campo em cada coluna.",
            cep,
            {"cep": "01001000"},
        ),
    ]
    return [
        {"title": title, "what": what, "source": source.model_dump(mode="json"), "values": values}
        for title, what, source, values in entries
    ]
