"""APIs públicas de exemplo (spec 022): sem chave e sem segredo, cada uma mostra um caso."""

from __future__ import annotations

from typing import Any

from prodata.connectors.api import ApiPagination, ApiParam, ApiStore, SavedApi

IBGE = "https://servicodados.ibge.gov.br/api"
IBGE_LOCALIDADES_DOCS = f"{IBGE}/docs/localidades"
IBGE_NOTICIAS_DOCS = f"{IBGE}/docs/noticias?versao=3"
ESTADOS_ID = "exemplo_ibge_estados"
MUNICIPIOS_ID = "exemplo_ibge_municipios"


def _estados() -> SavedApi:
    return SavedApi(
        id=ESTADOS_ID,
        name="Estados do Brasil (IBGE)",
        url=f"{IBGE}/v1/localidades/estados",
        params=[
            ApiParam(name="orderBy", value="nome", note="Ordena pelo nome. Sem ele, a ordem é a da API.")
        ],
        docs_url=IBGE_LOCALIDADES_DOCS,
        hold_on_open=True,
        cache_results=True,  # uma chamada basta: o exemplo não precisa repetir a cada execução
    )


def _municipios() -> SavedApi:
    return SavedApi(
        id=MUNICIPIOS_ID,
        name="Municípios de um estado (IBGE)",
        url=f"{IBGE}/v1/localidades/estados/{{sigla}}/municipios",
        params=[
            ApiParam(name="view", value="nivelado", note="Traz os campos sem aninhar, todos no mesmo nível.")
        ],
        docs_url=IBGE_LOCALIDADES_DOCS,
        hold_on_open=True,
        cache_results=True,  # uma chamada basta: o exemplo não precisa repetir a cada execução
    )


def seed_example_apis(store: ApiStore) -> None:
    """Cadastra as APIs do fluxo de demonstração, sem mexer em nada que já exista."""
    known = {a.id for a in store.list()}
    for source in (_estados(), _municipios()):
        if source.id not in known:
            store.save(source)


def refresh_example_docs(store: ApiStore) -> None:
    """Leva link e anotações às APIs de exemplo já cadastradas, sem mudar a chamada nem o que o usuário escreveu."""
    known = {a.id: a for a in store.list()}
    for example in (_estados(), _municipios()):
        saved = known.get(example.id)
        if saved is None:
            continue
        notes = {p.name: p.note for p in example.params}
        params = [p.model_copy(update={"note": p.note or notes.get(p.name, "")}) for p in saved.params]
        docs = saved.docs_url or example.docs_url
        if docs != saved.docs_url or params != saved.params:
            base = SavedApi.model_validate(saved.model_dump(exclude={"set_secrets", "missing_secrets"}))
            store.save(base.model_copy(update={"docs_url": docs, "params": params}))


def editor_examples() -> list[dict[str, Any]]:
    """Pontos de partida do cadastro de API."""
    noticias = SavedApi(
        id="exemplo_ibge_noticias",
        name="Notícias do IBGE",
        url=f"{IBGE}/v3/noticias/",
        records_path="items",
        docs_url=IBGE_NOTICIAS_DOCS,
        pagination=ApiPagination(type="page", page_param="page", size_param="qtd", page_size=20, max_pages=3),
    )
    feriados = SavedApi(
        id="exemplo_feriados",
        name="Feriados nacionais",
        url="https://brasilapi.com.br/api/feriados/v1/{ano}",
        docs_url="https://brasilapi.com.br/docs",
    )
    cep = SavedApi(
        id="exemplo_cep",
        name="Endereço por CEP",
        url="https://viacep.com.br/ws/{cep}/json/",
        docs_url="https://viacep.com.br/",
    )
    entries: list[tuple[str, str, SavedApi, dict[str, str]]] = [
        ("Lista simples", "A resposta já é uma lista: cada item vira uma linha.", _estados(), {}),
        (
            "Com variável",
            "Pede {sigla}: entra como API Loop, e a sigla vem de uma coluna da tabela.",
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
            "Ano no endereço",
            "Pede {ano}: uma chamada para cada ano da tabela.",
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
