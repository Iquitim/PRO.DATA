"""Fontes de API e API Loop (spec 021). Nenhum teste sai da máquina: as respostas são simuladas."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import polars as pl
import pytest

from prodata.connectors import api as api_module
from prodata.connectors.api import (
    ApiAuth,
    ApiClient,
    ApiDefinition,
    ApiError,
    ApiPagination,
    ApiParam,
    ApiStore,
    SavedApi,
    read_api,
    rows_to_frame,
    run_loop,
)
from prodata.connectors.secrets import MemorySecretStore
from prodata.domain.workflow import Workflow
from prodata.engine.runner import WorkflowRunner

URL = "https://api.exemplo.com/v1/itens"
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx.Request]]:
    """Troca a rede por uma função. Devolve a lista de pedidos recebidos."""
    monkeypatch.setattr(api_module, "RETRY_BASE_SECONDS", 0)

    def install(handler: Handler) -> list[httpx.Request]:
        calls: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return handler(request)

        monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(record))
        return calls

    return install


def no_secret(_slot: str) -> str | None:
    return None


def read(definition: ApiDefinition, secret: Callable[[str], str | None] = no_secret) -> pl.DataFrame:
    return read_api(definition, secret)[0]


def query_of(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.url.query.decode())


# ------------------------------------------------------------------ leitura da resposta


def test_json_list_becomes_a_table(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, json=[{"id": 1, "nome": "a"}, {"id": 2, "nome": "b"}]))
    df = read(ApiDefinition(url=URL))
    assert df.to_dicts() == [{"id": 1, "nome": "a"}, {"id": 2, "nome": "b"}]
    assert df.schema["id"] == pl.Int64


def test_the_only_list_in_the_answer_is_found_alone(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, json={"total": 2, "data": [{"a": 1}, {"a": 2}]}))
    assert read(ApiDefinition(url=URL))["a"].to_list() == [1, 2]


def test_records_path_and_nested_fields(serve: Any) -> None:
    body = {"data": {"itens": [{"id": 1, "dono": {"nome": "x", "uf": {"sigla": "SP"}}, "tags": ["a", "b"]}]}}
    serve(lambda _r: httpx.Response(200, json=body))
    df = read(ApiDefinition(url=URL, records_path="data.itens"))
    assert df.columns == ["id", "dono.nome", "dono.uf.sigla", "tags"]
    assert df["dono.uf.sigla"][0] == "SP"
    assert json.loads(df["tags"][0]) == ["a", "b"]


def test_wrong_path_says_what_exists(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, json={"data": [], "total": 0}))
    with pytest.raises(ApiError, match="data, total"):
        read(ApiDefinition(url=URL, records_path="itens"))


def test_list_inside_each_record_can_become_rows(serve: Any) -> None:
    body = [
        {"id": 1, "itens": [{"sku": "a"}, {"sku": "b"}]},
        {"id": 2, "itens": []},
        {"id": 3, "itens": ["x"]},
    ]
    serve(lambda _r: httpx.Response(200, json=body))
    df = read(ApiDefinition(url=URL, explode_path="itens"))
    assert df["id"].to_list() == [1, 1, 2, 3]
    assert df["itens.sku"].to_list() == ["a", "b", None, None]
    assert df["itens.valor"].to_list() == [None, None, None, "x"]


def test_flatten_off_keeps_json_text(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, json=[{"id": 1, "dono": {"nome": "x"}}]))
    df = read(ApiDefinition(url=URL, flatten=False))
    assert json.loads(df["dono"][0]) == {"nome": "x"}


def test_mixed_types_do_not_lose_data() -> None:
    df = rows_to_frame([{"a": 1, "b": 1, "c": True}, {"a": "x", "b": 2.5, "c": None}, {"d": 2**70}])
    assert df["a"].to_list() == ["1", "x", None]
    assert df["b"].to_list() == [1.0, 2.5, None]
    assert df["c"].dtype == pl.Boolean
    assert df["d"].to_list() == [None, None, str(2**70)]


def test_csv_answer(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, text="a;b\n1;x\n2;y\n", headers={"content-type": "text/csv"}))
    assert read(ApiDefinition(url=URL))["b"].to_list() == ["x", "y"]


def test_xml_answer(serve: Any) -> None:
    xml = '<r xmlns="urn:x"><meta><n>2</n></meta><itens><i id="1"><v>a</v></i><i id="2"><v>b</v></i></itens></r>'
    serve(lambda _r: httpx.Response(200, text=xml, headers={"content-type": "application/xml"}))
    df = read(ApiDefinition(url=URL, records_path="itens.i"))
    assert df.to_dicts() == [{"@id": "1", "v": "a"}, {"@id": "2", "v": "b"}]


def test_xml_with_entities_is_refused(serve: Any) -> None:
    bomb = '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    serve(lambda _r: httpx.Response(200, text=bomb, headers={"content-type": "application/xml"}))
    with pytest.raises(ApiError, match="DOCTYPE"):
        read(ApiDefinition(url=URL))


def test_html_answer_explains_itself(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}))
    with pytest.raises(ApiError, match="login"):
        read(ApiDefinition(url=URL))


def test_empty_answer_is_an_empty_table(serve: Any) -> None:
    serve(lambda _r: httpx.Response(204))
    assert read(ApiDefinition(url=URL)).height == 0


# ------------------------------------------------------------------ autenticação e segredos


@pytest.mark.parametrize(
    ("auth", "header", "value"),
    [
        (ApiAuth(type="bearer"), "authorization", "Bearer s3nh4"),
        (ApiAuth(type="api_key", key_name="X-Chave"), "x-chave", "s3nh4"),
        (ApiAuth(type="basic", username="ana"), "authorization", "Basic YW5hOnMzbmg0"),
    ],
)
def test_credentials_go_in_the_request(auth: ApiAuth, header: str, value: str, serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(200, json=[]))
    read(ApiDefinition(url=URL, auth=auth), lambda _s: "s3nh4")
    assert calls[0].headers[header] == value


def test_api_key_in_the_query(serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(200, json=[]))
    read(
        ApiDefinition(url=URL, auth=ApiAuth(type="api_key", key_name="k", key_in="query")), lambda _s: "s3nh4"
    )
    assert query_of(calls[0])["k"] == ["s3nh4"]


def oauth_server(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/token":
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    if request.headers.get("authorization") != "Bearer tok-1":
        return httpx.Response(401)
    return httpx.Response(200, json=[{"a": 1}])


def test_oauth_client_credentials(serve: Any) -> None:
    calls = serve(oauth_server)
    auth = ApiAuth(type="oauth2", token_url="https://api.exemplo.com/token", client_id="id", scope="ler")
    assert read(ApiDefinition(url=URL, auth=auth), lambda _s: "segredo").height == 1
    form = parse_qs(calls[0].content.decode())
    assert form["grant_type"] == ["client_credentials"] and form["client_secret"] == ["segredo"]
    assert form["scope"] == ["ler"]


def test_oauth_renews_an_expired_token_once(serve: Any) -> None:
    tokens = iter(["velho", "novo"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 3600})
        return httpx.Response(
            200 if request.headers["authorization"] == "Bearer novo" else 401, json=[{"a": 1}]
        )

    serve(handler)
    auth = ApiAuth(type="oauth2", token_url="https://api.exemplo.com/token", client_id="id")
    assert read(ApiDefinition(url=URL, auth=auth), lambda _s: "x").height == 1


def test_secrets_are_not_in_files_and_errors(serve: Any, tmp_path: Path) -> None:
    vault = MemorySecretStore()
    store = ApiStore(tmp_path / "apis.json", vault)
    source = SavedApi(
        id="a1",
        name="A",
        url=URL,
        auth=ApiAuth(type="bearer"),
        headers=[ApiParam(name="X-Interno", value="digitado-por-engano", secret=True)],
    )
    info = store.save(source, {"token": "tok-secreto", "header:X-Interno": "h-secreto"})
    assert info.missing_secrets == [] and sorted(info.set_secrets) == ["header:X-Interno", "token"]
    text = (tmp_path / "apis.json").read_text(encoding="utf-8")
    for secret in ("tok-secreto", "h-secreto", "digitado-por-engano"):
        assert secret not in text
    assert vault.get("api:a1:token") == "tok-secreto"

    # A API ecoa o token no erro: a mensagem não pode repeti-lo.
    serve(lambda r: httpx.Response(400, text=f"token invalido: {r.headers['authorization']}"))
    with pytest.raises(ApiError) as caught:
        read(store.get("a1"), store.secret_reader("a1"))
    assert "tok-secreto" not in caught.value.message and "***" in caught.value.message

    store.delete("a1")
    assert vault.get("api:a1:token") is None and vault.get("api:a1:header:X-Interno") is None


def test_saving_keeps_the_secret_unless_told(tmp_path: Path) -> None:
    vault = MemorySecretStore()
    store = ApiStore(tmp_path / "apis.json", vault)
    source = SavedApi(id="a1", name="A", url=URL, auth=ApiAuth(type="bearer"))
    store.save(source, {"token": "t"})
    store.save(source)
    assert vault.get("api:a1:token") == "t"
    store.save(source, {"token": ""})
    assert vault.get("api:a1:token") is None
    store.save(source, {"token": "t"})
    store.save(source.model_copy(update={"auth": ApiAuth(type="none")}))
    assert vault.get("api:a1:token") is None  # deixou de usar: não fica esquecido no cofre


def test_query_key_is_not_in_error_or_log(serve: Any, caplog: pytest.LogCaptureFixture) -> None:
    serve(lambda _r: httpx.Response(500, text="falhou"))
    definition = ApiDefinition(url=URL, auth=ApiAuth(type="api_key", key_name="k", key_in="query"), retries=0)
    with caplog.at_level(logging.INFO), pytest.raises(ApiError) as caught:
        read(definition, lambda _s: "chave-secreta")
    assert "chave-secreta" not in caught.value.message
    assert "chave-secreta" not in caplog.text


def test_credentials_in_the_url_are_refused() -> None:
    with pytest.raises(ApiError, match="cofre"):
        ApiDefinition(url="https://ana:senha@api.exemplo.com/x").check()


@pytest.mark.parametrize("url", ["ftp://x/y", "file:///c:/x", "javascript:alert(1)", "api.exemplo.com"])
def test_only_web_addresses(url: str) -> None:
    with pytest.raises(ApiError, match="https://"):
        ApiDefinition(url=url).check()


# ------------------------------------------------------------------ redirecionamentos


def test_credentials_do_not_follow_to_another_server(serve: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exemplo.com":
            return httpx.Response(302, headers={"location": "https://outro.com/x"})
        return httpx.Response(200, json=[{"a": 1}])

    calls = serve(handler)
    definition = ApiDefinition(
        url=URL, auth=ApiAuth(type="api_key"), headers=[ApiParam(name="X-Meu", value="1")]
    )
    read(definition, lambda _s: "s3nh4")
    assert calls[0].headers["x-api-key"] == "s3nh4"
    assert "x-api-key" not in calls[1].headers and "x-meu" not in calls[1].headers


def test_downgrade_to_http_is_refused(serve: Any) -> None:
    serve(lambda _r: httpx.Response(302, headers={"location": "http://api.exemplo.com/x"}))
    with pytest.raises(ApiError, match="sem criptografia"):
        read(ApiDefinition(url=URL))


def test_endless_redirect_stops(serve: Any) -> None:
    serve(lambda _r: httpx.Response(302, headers={"location": URL}))
    with pytest.raises(ApiError, match="vezes demais"):
        read(ApiDefinition(url=URL))


# ------------------------------------------------------------------ paginação


def test_page_number(serve: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(query_of(request)["pagina"][0])
        return httpx.Response(200, json=[{"p": page}] * (2 if page < 3 else 1))

    calls = serve(handler)
    pager = ApiPagination(type="page", page_param="pagina", size_param="n", page_size=2)
    df = read(ApiDefinition(url=URL, pagination=pager))
    assert df["p"].to_list() == [1, 1, 2, 2, 3] and len(calls) == 3
    assert query_of(calls[0])["n"] == ["2"]


def test_page_without_size_stops_on_empty_page(serve: Any) -> None:
    calls = serve(lambda r: httpx.Response(200, json=[{"a": 1}] if query_of(r)["page"][0] == "1" else []))
    assert read(ApiDefinition(url=URL, pagination=ApiPagination(type="page"))).height == 1
    assert len(calls) == 2


def test_offset(serve: Any) -> None:
    data = [{"a": i} for i in range(5)]

    def handler(request: httpx.Request) -> httpx.Response:
        q = query_of(request)
        start, size = int(q["offset"][0]), int(q["limit"][0])
        return httpx.Response(200, json=data[start : start + size])

    serve(handler)
    assert read(ApiDefinition(url=URL, pagination=ApiPagination(type="offset", page_size=2)))[
        "a"
    ].to_list() == [0, 1, 2, 3, 4]


def test_cursor(serve: Any) -> None:
    pages = {"": ([1], "c2"), "c2": ([2], "c3"), "c3": ([3], None)}

    def handler(request: httpx.Request) -> httpx.Response:
        rows, following = pages[query_of(request).get("cursor", [""])[0]]
        return httpx.Response(200, json={"itens": [{"a": r} for r in rows], "next_cursor": following})

    serve(handler)
    assert read(ApiDefinition(url=URL, records_path="itens", pagination=ApiPagination(type="cursor")))[
        "a"
    ].to_list() == [1, 2, 3]


def test_repeated_cursor_stops(serve: Any) -> None:
    n = iter(range(100))
    calls = serve(lambda _r: httpx.Response(200, json={"itens": [{"a": next(n)}], "next_cursor": "mesmo"}))
    read(ApiDefinition(url=URL, records_path="itens", pagination=ApiPagination(type="cursor")))
    assert len(calls) == 2


def test_next_link_in_the_body(serve: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "p=2" in str(request.url):
            return httpx.Response(200, json={"itens": [{"a": 2}], "prox": None})
        return httpx.Response(200, json={"itens": [{"a": 1}], "prox": "/v1/itens?p=2"})

    serve(handler)
    pager = ApiPagination(type="next_link", next_path="prox")
    assert read(ApiDefinition(url=URL, records_path="itens", pagination=pager))["a"].to_list() == [1, 2]


def test_next_link_in_the_header(serve: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "p=2" in str(request.url):
            return httpx.Response(200, json=[{"a": 2}])
        return httpx.Response(
            200, json=[{"a": 1}], headers={"link": f'<{URL}?p=2>; rel="next", <{URL}>; rel="first"'}
        )

    serve(handler)
    assert read(ApiDefinition(url=URL, pagination=ApiPagination(type="next_link")))["a"].to_list() == [1, 2]


def test_next_link_keeps_the_key_in_the_query(serve: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "p=2" in str(request.url):
            return httpx.Response(200, json=[{"a": 2}])
        return httpx.Response(200, json=[{"a": 1}], headers={"link": f'<{URL}?p=2>; rel="next"'})

    calls = serve(handler)
    auth = ApiAuth(type="api_key", key_name="k", key_in="query")
    read(ApiDefinition(url=URL, auth=auth, pagination=ApiPagination(type="next_link")), lambda _s: "s")
    assert query_of(calls[1])["k"] == ["s"]


def test_next_link_to_another_server_is_refused(serve: Any) -> None:
    calls = serve(
        lambda _r: httpx.Response(200, json=[{"a": 1}], headers={"link": '<https://mau.com/x>; rel="next"'})
    )
    with pytest.raises(ApiError, match="outro servidor"):
        read(
            ApiDefinition(url=URL, auth=ApiAuth(type="bearer"), pagination=ApiPagination(type="next_link")),
            lambda _s: "s",
        )
    assert all(c.url.host == "api.exemplo.com" for c in calls)


def test_server_that_ignores_the_page_does_not_duplicate(serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(200, json=[{"a": 1}]))
    assert read(ApiDefinition(url=URL, pagination=ApiPagination(type="page"))).height == 1
    assert len(calls) == 2


def test_page_limit_is_reported(serve: Any) -> None:
    n = iter(range(100))
    serve(lambda _r: httpx.Response(200, json=[{"a": next(n)}]))
    pager = ApiPagination(type="page", max_pages=3)
    df, result = read_api(ApiDefinition(url=URL, pagination=pager), no_secret)
    assert df.height == 3 and result.truncated


# ------------------------------------------------------------------ falhas


def test_retry_after_429_then_works(serve: Any) -> None:
    answers = iter(
        [
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(503),
            httpx.Response(200, json=[{"a": 1}]),
        ]
    )
    calls = serve(lambda _r: next(answers))
    assert read(ApiDefinition(url=URL)).height == 1 and len(calls) == 3


def test_post_does_not_retry_on_server_error(serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(503))
    with pytest.raises(ApiError, match="HTTP 503"):
        read(ApiDefinition(url=URL, method="POST"))
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("status", "text"),
    [(401, "credenciais"), (403, "permissão"), (404, "não encontrou"), (500, "do lado dela")],
)
def test_status_messages_are_clear(status: int, text: str, serve: Any) -> None:
    serve(lambda _r: httpx.Response(status))
    with pytest.raises(ApiError, match=text):
        read(ApiDefinition(url=URL, retries=0))


def test_timeout_and_connection_messages(serve: Any) -> None:
    def timeout(_r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("x")

    serve(timeout)
    with pytest.raises(ApiError, match="não respondeu"):
        read(ApiDefinition(url=URL, retries=0))

    def refused(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    serve(refused)
    with pytest.raises(ApiError, match="Não foi possível conectar"):
        read(ApiDefinition(url=URL, retries=1))


def test_size_limit(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024)))
    with pytest.raises(ApiError, match="limite de 1 MB"):
        read(ApiDefinition(url=URL, max_mb=1))


# ------------------------------------------------------------------ valores das colunas


def test_value_cannot_change_the_path(serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(200, json=[]))
    with ApiClient(ApiDefinition(url="https://api.exemplo.com/c/{id}/x"), no_secret) as client:
        client.fetch({"id": "../admin?a=1"})
    assert calls[0].url.raw_path == b"/c/..%2Fadmin%3Fa%3D1/x"


def test_value_cannot_break_a_header(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, json=[]))
    definition = ApiDefinition(url=URL, headers=[ApiParam(name="X-Id", value="{id}")])
    with ApiClient(definition, no_secret) as client, pytest.raises(ApiError, match="quebra de linha"):
        client.fetch({"id": "a\r\nX-Mau: 1"})


def test_json_body_keeps_types_and_escapes(serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(200, json=[]))
    definition = ApiDefinition(
        url=URL, method="POST", body='{"id": "{id}", "txt": "nome: {nome}", "fixo": 1}'
    )
    with ApiClient(definition, no_secret) as client:
        client.fetch({"id": 7, "nome": 'x", "admin": "true'})
    assert json.loads(calls[0].content) == {"id": 7, "txt": 'nome: x", "admin": "true', "fixo": 1}
    assert calls[0].headers["content-type"] == "application/json"


def test_json_body_must_be_valid() -> None:
    with pytest.raises(ApiError, match="entre aspas"):
        ApiDefinition(url=URL, method="POST", body='{"id": {id}}').check()


def test_placeholder_without_loop_points_to_the_tool() -> None:
    with pytest.raises(ApiError, match="API Loop"):
        read_api(ApiDefinition(url="https://api.exemplo.com/{id}"), no_secret)


# ------------------------------------------------------------------ API Loop


def echo(request: httpx.Request) -> httpx.Response:
    code = request.url.path.rsplit("/", 1)[1]
    if code == "ruim":
        return httpx.Response(404, text="nao achei")
    if code == "vazio":
        return httpx.Response(200, json=[])
    if code == "duplo":
        return httpx.Response(200, json=[{"v": "d1"}, {"v": "d2"}])
    return httpx.Response(200, json=[{"v": f"valor de {code}"}])


LOOP = ApiDefinition(url="https://api.exemplo.com/c/{id}")


def loop(df: pl.DataFrame, source: ApiDefinition = LOOP, **options: Any) -> Any:
    options.setdefault("per_second", 0)
    return run_loop(df, source, no_secret, **options)


def test_loop_joins_answers_to_rows_in_order(serve: Any) -> None:
    serve(echo)
    df = pl.DataFrame({"id": ["b", "a", "c"], "x": [1, 2, 3]})
    out = loop(df)
    assert out.table.to_dicts() == [
        {"id": "b", "x": 1, "v": "valor de b"},
        {"id": "a", "x": 2, "v": "valor de a"},
        {"id": "c", "x": 3, "v": "valor de c"},
    ]
    assert out.errors.height == 0 and out.calls == 3


def test_identical_values_call_once(serve: Any) -> None:
    calls = serve(echo)
    df = pl.DataFrame({"id": ["a", "a", "b", "a"], "x": [1, 2, 3, 4]})
    out = loop(df)
    assert len(calls) == 2
    assert out.table["x"].to_list() == [1, 2, 3, 4]
    assert out.table["v"].to_list() == ["valor de a", "valor de a", "valor de b", "valor de a"]


def test_several_rows_per_answer_and_empty_answer(serve: Any) -> None:
    serve(echo)
    out = loop(pl.DataFrame({"id": ["duplo", "vazio"]}))
    assert out.table.to_dicts() == [
        {"id": "duplo", "v": "d1"},
        {"id": "duplo", "v": "d2"},
        {"id": "vazio", "v": None},
    ]


def test_failures_go_to_the_error_table(serve: Any) -> None:
    serve(echo)
    out = loop(pl.DataFrame({"id": ["a", "ruim", None], "x": [1, 2, 3]}))
    assert out.table["id"].to_list() == ["a"]
    assert out.errors["id"].to_list() == ["ruim", None]
    assert out.errors["status_http"].to_list() == [404, None]
    assert "Valor vazio" in out.errors["erro"][1]
    assert out.failed == 2


def test_stop_on_first_error(serve: Any) -> None:
    serve(echo)
    with pytest.raises(ApiError, match="parou"):
        loop(pl.DataFrame({"id": ["ruim", "a"]}), stop_on_error=True, concurrency=1)


def test_call_limit_stops_before_calling(serve: Any) -> None:
    calls = serve(echo)
    with pytest.raises(ApiError, match="3 chamadas"):
        loop(pl.DataFrame({"id": ["a", "b", "c"]}), max_calls=2)
    assert calls == []


def test_missing_column_is_explained(serve: Any) -> None:
    serve(echo)
    with pytest.raises(ApiError, match="não tem essa coluna"):
        loop(pl.DataFrame({"outra": [1]}))


def test_api_without_placeholder_is_refused(serve: Any) -> None:
    with pytest.raises(ApiError, match="não pede nenhum parâmetro"):
        loop(pl.DataFrame({"id": [1]}), ApiDefinition(url=URL))


def test_parameter_comes_from_the_chosen_column(serve: Any) -> None:
    calls = serve(echo)
    df = pl.DataFrame({"uf": ["a", "b", "a"], "x": [1, 2, 3]})
    out = loop(df, columns={"id": "uf"})
    assert [c.url.path for c in sorted(calls, key=lambda c: c.url.path)] == ["/c/a", "/c/b"]
    assert out.table.to_dicts() == [
        {"uf": "a", "x": 1, "v": "valor de a"},
        {"uf": "b", "x": 2, "v": "valor de b"},
        {"uf": "a", "x": 3, "v": "valor de a"},
    ]


def test_chosen_column_wins_over_the_same_name(serve: Any) -> None:
    calls = serve(echo)
    loop(pl.DataFrame({"id": ["nao"], "uf": ["sim"]}), columns={"id": "uf"})
    assert calls[0].url.path == "/c/sim"


def test_without_a_choice_the_same_name_is_used(serve: Any) -> None:
    calls = serve(echo)
    loop(pl.DataFrame({"id": ["a"]}), columns={})
    assert calls[0].url.path == "/c/a"


def test_two_parameters_can_read_the_same_column(serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(200, json=[{"ok": 1}]))
    source = ApiDefinition(url="https://api.exemplo.com/{a}/{b}")
    out = loop(pl.DataFrame({"c": ["x"]}), source, columns={"a": "c", "b": "c"})
    assert calls[0].url.path == "/x/x" and out.table.to_dicts() == [{"c": "x", "ok": 1}]


def test_chosen_column_that_does_not_exist_calls_nothing(serve: Any) -> None:
    calls = serve(echo)
    with pytest.raises(ApiError, match="Escolha a coluna"):
        loop(pl.DataFrame({"uf": ["a"]}), columns={"id": "sumiu"})
    assert calls == []


def test_empty_value_names_the_chosen_column(serve: Any) -> None:
    serve(echo)
    out = loop(pl.DataFrame({"uf": [None, "a"]}), columns={"id": "uf"})
    assert "[uf]" in out.errors["erro"][0] and out.errors["uf"].to_list() == [None]


def test_tool_uses_the_chosen_column(serve: Any, runner: WorkflowRunner, apis: ApiStore) -> None:
    serve(api_server)
    flow = Workflow.model_validate(
        {
            "id": "wf-map",
            "name": "x",
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "label": "T",
                    "config": {"table": {"columns": ["codigo"], "rows": [["7"]]}},
                },
                {
                    "id": "l",
                    "type": "io.api_loop",
                    "label": "L",
                    "config": {"source": "det", "calls_per_second": 0, "columns": {"id": "codigo"}},
                },
            ],
            "edges": [{"id": "e", "source": "t", "sourceHandle": "out", "target": "l", "targetHandle": "in"}],
        }
    )
    report = runner.run(flow)
    assert report.node_results["l"].status == "executed", report.node_results["l"].error
    assert runner.cache.get(flow.id, "l").tables["out"].to_dicts() == [{"codigo": 7, "det": "d7"}]


def test_name_clash_keeps_both(serve: Any) -> None:
    serve(lambda _r: httpx.Response(200, json=[{"id": "da api", "w": 1}]))
    out = loop(pl.DataFrame({"id": ["a"]}))
    assert out.table.to_dicts() == [{"id": "a", "id_api": "da api", "w": 1}]


def test_only_answer_columns(serve: Any) -> None:
    serve(echo)
    out = loop(pl.DataFrame({"id": ["a"], "x": [1]}), keep_columns=False)
    assert out.table.columns == ["v"]


def test_loop_paginates_each_call(serve: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(query_of(request)["page"][0])
        return httpx.Response(200, json=[{"pag": page}] if page <= 2 else [])

    serve(handler)
    source = LOOP.model_copy(update={"pagination": ApiPagination(type="page")})
    assert loop(pl.DataFrame({"id": ["a"]}), source).table["pag"].to_list() == [1, 2]


def test_many_columns_and_numeric_values(serve: Any) -> None:
    calls = serve(lambda _r: httpx.Response(200, json=[{"ok": 1}]))
    source = ApiDefinition(
        url="https://api.exemplo.com/{id}",
        params=[ApiParam(name="ano", value="{ano}"), ApiParam(name="f", value="1")],
    )
    loop(pl.DataFrame({"id": [7], "ano": [2026]}), source)
    assert calls[0].url.path == "/7" and query_of(calls[0]) == {"ano": ["2026"], "f": ["1"]}


# ------------------------------------------------------------------ no fluxo


def api_flow(*extra_nodes: dict, edges: list[dict] | None = None) -> Workflow:
    return Workflow.model_validate(
        {
            "id": "wf-api",
            "name": "x",
            "nodes": [
                {
                    "id": "fonte",
                    "type": "io.input_data",
                    "label": "Fonte",
                    "config": {"dataset": "api:lista"},
                },
                *extra_nodes,
            ],
            "edges": edges or [],
        }
    )


LOOP_NODE = {
    "id": "l",
    "type": "io.api_loop",
    "label": "L",
    "config": {"source": "det", "calls_per_second": 0},
}
LOOP_EDGE = [{"id": "e", "source": "fonte", "sourceHandle": "out", "target": "l", "targetHandle": "in"}]


def api_server(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/lista":
        return httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    return httpx.Response(200, json={"det": f"d{request.url.path.rsplit('/', 1)[1]}"})


@pytest.fixture
def apis(runner: WorkflowRunner, tmp_path: Path) -> ApiStore:
    store = ApiStore(tmp_path / "apis.json", MemorySecretStore())
    store.save(SavedApi(id="lista", name="Lista", url="https://x.com/lista"))
    store.save(SavedApi(id="det", name="Detalhe", url="https://x.com/d/{id}"))
    runner.apis = store
    return store


def test_table_from_the_output_of_another_api(serve: Any, runner: WorkflowRunner, apis: ApiStore) -> None:
    serve(api_server)
    flow = api_flow(LOOP_NODE, edges=LOOP_EDGE)
    report = runner.run(flow)
    assert report.node_results["l"].status == "executed", report.node_results["l"].error
    table = runner.cache.get(flow.id, "l").tables["out"]
    assert table.to_dicts() == [{"id": 1, "det": "d1"}, {"id": 2, "det": "d2"}]
    assert report.node_results["l"].extra["api_calls"] == 2


def test_get_runs_again_unless_told_to_reuse(serve: Any, runner: WorkflowRunner, apis: ApiStore) -> None:
    calls = serve(api_server)
    flow = api_flow()
    runner.run(flow)
    runner.run(flow)
    assert len(calls) == 2
    apis.save(SavedApi(id="lista", name="Lista", url="https://x.com/lista", cache_results=True))
    runner.run(flow)
    runner.run(flow)
    assert len(calls) == 3


def test_opening_the_flow_does_not_call_the_loop_or_post(
    serve: Any, runner: WorkflowRunner, apis: ApiStore
) -> None:
    calls = serve(api_server)
    flow = api_flow(LOOP_NODE, edges=LOOP_EDGE)
    report = runner.run(flow, hold_exports=True)
    assert report.node_results["l"].status == "skipped"
    assert "Clique em Executar" in report.node_results["l"].error
    assert [c.url.path for c in calls] == ["/lista"]  # só o GET

    apis.save(SavedApi(id="lista", name="Lista", url="https://x.com/lista", method="POST"))
    calls.clear()
    report = runner.run(api_flow(), hold_exports=True)
    assert report.node_results["fonte"].status == "skipped" and calls == []
    assert runner.run(api_flow()).node_results["fonte"].status == "executed" and len(calls) == 1


def test_loop_reuse_avoids_new_calls(serve: Any, runner: WorkflowRunner, apis: ApiStore) -> None:
    apis.save(SavedApi(id="lista", name="Lista", url="https://x.com/lista", cache_results=True))
    calls = serve(api_server)
    node = {**LOOP_NODE, "config": {**LOOP_NODE["config"], "reuse": True}}
    flow = api_flow(node, edges=LOOP_EDGE)
    runner.run(flow)
    first = len(calls)
    report = runner.run(flow)
    assert report.node_results["l"].status == "cached" and len(calls) == first
    assert runner.run(flow, hold_exports=True).node_results["l"].status == "cached"


def test_failures_appear_as_a_warning_and_in_port_e(
    serve: Any, runner: WorkflowRunner, apis: ApiStore
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/lista":
            return httpx.Response(200, json=[{"id": 1}, {"id": 2}])
        return httpx.Response(404 if request.url.path.endswith("2") else 200, json=[{"ok": 1}])

    serve(handler)
    flow = api_flow(LOOP_NODE, edges=LOOP_EDGE)
    report = runner.run(flow)
    assert "1 de 2" in report.node_results["l"].extra["warnings"][0]
    assert runner.cache.get(flow.id, "l").tables["errors"]["id"].to_list() == [2]


# ------------------------------------------------------------------ rotas


def test_routes_never_return_secrets(client: Any, serve: Any) -> None:
    body = {
        "source": {"id": "rota", "name": "Rota", "url": URL, "auth": {"type": "bearer"}},
        "secrets": {"token": "valor-secreto"},
    }
    saved = client.put("/api/apis/rota", json=body)
    assert saved.status_code == 200, saved.text
    assert "valor-secreto" not in saved.text and saved.json()["set_secrets"] == ["token"]
    assert "valor-secreto" not in client.get("/api/apis").text

    calls = serve(lambda _r: httpx.Response(200, json=[{"a": 1}, {"a": 2}]))
    preview = client.post("/api/apis/preview", json={"definition": body["source"], "id": "rota"})
    assert preview.status_code == 200, preview.text
    assert preview.json()["total"] == 2
    assert calls[0].headers["authorization"] == "Bearer valor-secreto"
    assert client.delete("/api/apis/rota").status_code == 204


def test_preview_asks_for_sample_values(client: Any, serve: Any) -> None:
    calls = serve(echo)
    definition = {"url": "https://api.exemplo.com/c/{id}"}
    first = client.post("/api/apis/preview", json={"definition": definition}).json()
    assert first["needs_values"] == ["id"] and calls == []
    second = client.post("/api/apis/preview", json={"definition": definition, "values": {"id": "a"}}).json()
    assert second["rows"] == [{"v": "valor de a"}]


def test_preview_warns_about_plain_http(client: Any, serve: Any) -> None:
    serve(echo)
    res = client.post("/api/apis/preview", json={"definition": {"url": "http://exemplo.com/x"}}).json()
    assert res["insecure"] is True
    assert (
        client.post("/api/apis/preview", json={"definition": {"url": "http://127.0.0.1/x"}}).json()[
            "insecure"
        ]
        is False
    )


def test_bad_definition_is_refused_on_save(client: Any) -> None:
    res = client.put("/api/apis/ruim", json={"source": {"id": "ruim", "name": "x", "url": "ftp://a/b"}})
    assert res.status_code in (400, 422)
