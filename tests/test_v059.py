"""Versão 0.5.9 (spec 026): ordenação, operações por tipo, rótulos e segurança das APIs."""

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import fastexcel
import httpx
import polars as pl
import pytest
from openpyxl import load_workbook

from prodata.connectors import api as api_module
from prodata.connectors import api_policy
from prodata.connectors.api import ApiClient, read_api
from prodata.connectors.api_loop import run_loop
from prodata.connectors.api_model import ApiAuth, ApiDefinition, ApiError, ApiPagination, ApiParam
from prodata.dashboard.filters import filters_for
from prodata.domain.dashboard import Dashboard, DashFilter
from prodata.domain.labels import EXCEL_PROPERTY
from prodata.domain.workflow import Workflow
from prodata.engine import formula, multirow
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.main import build_services
from prodata.nodes import REGISTRY, NodeContext
from prodata.nodes.bi import ChartConfig, KpiConfig
from prodata.nodes.prep import MultiRowConfig
from prodata.nodes.transform import AGG_BY_TYPE
from prodata.services import audit


def secret(_slot: str) -> str:
    return "SEGREDO"


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"a": 1}])

    monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(record))
    monkeypatch.setattr(api_module, "RETRY_BASE_SECONDS", 0)
    return calls


def allow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *hosts: str) -> None:
    path = tmp_path / "politica.json"
    path.write_text(json.dumps({"servidores_internos": list(hosts)}), encoding="utf-8")
    monkeypatch.setenv(api_policy.POLICY_ENV, str(path))


# ------------------------------------------------------------------ destinos


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8765/api/x",
        "http://localhost/x",
        "http://10.0.0.5/x",
        "https://172.16.0.1/x",
        "http://192.168.0.1/x",
        "http://[::1]/x",
        "http://[::ffff:10.0.0.1]/x",
        "http://0.0.0.0/x",
    ],
)
def test_internal_address_needs_the_list(url: str, seen: list[httpx.Request]) -> None:
    with pytest.raises(ApiError, match="rede interna"):
        read_api(ApiDefinition(url=url), secret)
    assert seen == []


def test_error_says_where_the_list_is(seen: list[httpx.Request]) -> None:
    with pytest.raises(ApiError) as caught:
        read_api(ApiDefinition(url="http://10.0.0.5/x"), secret)
    assert "politica.json" in caught.value.message and "públicas não precisam" in caught.value.message


def test_public_api_needs_no_configuration(seen: list[httpx.Request]) -> None:
    assert read_api(ApiDefinition(url="https://servicodados.ibge.gov.br/x"), secret)[0].height == 1


def test_name_that_points_inside_is_internal(
    seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_policy, "resolve", lambda _h: ["10.1.2.3"])
    with pytest.raises(ApiError, match="rede interna"):
        read_api(ApiDefinition(url="https://parece-publico.com/x"), secret)
    assert seen == []


@pytest.mark.parametrize(
    ("rule", "url"),
    [
        ("erp.empresa.local", "http://erp.empresa.local/x"),
        ("*.empresa.local", "http://erp.empresa.local/x"),
        ("10.1.2.3", "http://10.1.2.3/x"),
        ("10.1.0.0/16", "http://10.1.2.3/x"),
        ("127.0.0.1", "http://127.0.0.1/x"),
    ],
)
def test_the_list_frees_internal_servers(
    rule: str, url: str, seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow(monkeypatch, tmp_path, rule)
    monkeypatch.setattr(api_policy, "resolve", lambda _h: ["10.1.2.3"])
    assert read_api(ApiDefinition(url=url), secret)[0].height == 1


def test_the_list_only_frees_what_it_names(
    seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow(monkeypatch, tmp_path, "10.1.0.0/16")
    with pytest.raises(ApiError, match="rede interna"):
        read_api(ApiDefinition(url="http://10.2.0.1/x"), secret)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/x",
        "http://[fd00:ec2::254]/x",
    ],
)
def test_cloud_metadata_never_even_on_the_list(
    url: str, seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow(monkeypatch, tmp_path, "*", "0.0.0.0/0", "::/0", "169.254.169.254")
    with pytest.raises(ApiError, match="metadados"):
        read_api(ApiDefinition(url=url), secret)
    assert seen == []


def test_unreadable_policy_frees_nothing(
    seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "politica.json"
    path.write_text("{ isto não é json", encoding="utf-8")
    monkeypatch.setenv(api_policy.POLICY_ENV, str(path))
    with pytest.raises(ApiError, match="rede interna"):
        read_api(ApiDefinition(url="http://10.0.0.5/x"), secret)


def test_policy_path_ignores_the_variable_in_the_installed_program(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(api_policy.POLICY_ENV, str(tmp_path / "meu.json"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "pd"))
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert api_policy.policy_path() == tmp_path / "pd" / "PRO.DATA" / "politica.json"


@pytest.mark.parametrize("target", ["https://10.0.0.5/admin", "https://127.0.0.1:8765/api/x"])
def test_public_site_cannot_redirect_inside(target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(302, headers={"location": target})

    monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(handler))
    with pytest.raises(ApiError, match="rede interna"):
        read_api(ApiDefinition(url="https://publico.com/x"), secret)
    assert calls == ["publico.com"]


def test_next_page_is_checked_too(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "publico.com":
            return (
                httpx.Response(302, headers={"location": "https://10.0.0.5/p2"})
                if "p=2" in str(request.url)
                else httpx.Response(
                    200, json=[{"a": 1}], headers={"link": '<https://publico.com/x?p=2>; rel="next"'}
                )
            )
        return httpx.Response(200, json=[{"interno": 1}])

    monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(handler))
    with pytest.raises(ApiError, match="rede interna"):
        read_api(
            ApiDefinition(url="https://publico.com/x", pagination=ApiPagination(type="next_link")), secret
        )


# ------------------------------------------------------------------ credenciais


@pytest.mark.parametrize(
    "definition",
    [
        ApiDefinition(url="http://exemplo.com/x", auth=ApiAuth(type="bearer")),
        ApiDefinition(url="http://exemplo.com/x", auth=ApiAuth(type="basic", username="u")),
        ApiDefinition(url="http://exemplo.com/x", auth=ApiAuth(type="api_key", key_in="query")),
        ApiDefinition(url="http://exemplo.com/x", headers=[ApiParam(name="X-S", secret=True)]),
    ],
)
def test_credentials_do_not_travel_unencrypted(definition: ApiDefinition, seen: list[httpx.Request]) -> None:
    with pytest.raises(ApiError, match="sem criptografia"):
        read_api(definition, secret)
    assert seen == []


def test_oauth_secret_does_not_travel_unencrypted(seen: list[httpx.Request]) -> None:
    auth = ApiAuth(type="oauth2", token_url="http://exemplo.com/token", client_id="i")
    with pytest.raises(ApiError, match="segredo do OAuth"):
        read_api(ApiDefinition(url="https://exemplo.com/x", auth=auth), secret)
    assert seen == []


def test_oauth_token_cannot_go_inside(seen: list[httpx.Request]) -> None:
    auth = ApiAuth(type="oauth2", token_url="https://10.0.0.5/token", client_id="i")
    with pytest.raises(ApiError, match="rede interna"):
        read_api(ApiDefinition(url="https://exemplo.com/x", auth=auth), secret)
    assert seen == []


def test_plain_http_without_credentials_still_works(seen: list[httpx.Request]) -> None:
    assert read_api(ApiDefinition(url="http://exemplo.com/x"), secret)[0].height == 1


def test_listed_internal_server_can_use_http_with_credentials(
    seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow(monkeypatch, tmp_path, "10.0.0.0/8")
    read_api(ApiDefinition(url="http://10.0.0.5/x", auth=ApiAuth(type="bearer")), secret)
    assert seen[0].headers["authorization"] == "Bearer SEGREDO"


@pytest.mark.parametrize(
    ("answer", "auth"),
    [
        (base64.b64encode(b"u:SEGREDO").decode(), ApiAuth(type="basic", username="u")),
        (base64.b64encode(b"SEGREDO").decode(), ApiAuth(type="bearer")),
        ("SEGREDO", ApiAuth(type="bearer")),
    ],
)
def test_error_hides_the_secret_in_any_form(
    answer: str, auth: ApiAuth, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        api_module, "_transport", httpx.MockTransport(lambda _r: httpx.Response(400, text=f"recebi {answer}"))
    )
    with pytest.raises(ApiError) as caught:
        read_api(ApiDefinition(url="https://exemplo.com/x", auth=auth, retries=0), secret)
    assert answer not in caught.value.message and "***" in caught.value.message


def test_url_encoded_secret_is_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def odd(_slot: str) -> str:
        return "a b/c"

    monkeypatch.setattr(
        api_module, "_transport", httpx.MockTransport(lambda _r: httpx.Response(400, text="k=a%20b%2Fc"))
    )
    with pytest.raises(ApiError) as caught:
        read_api(ApiDefinition(url="https://exemplo.com/x", auth=ApiAuth(type="bearer"), retries=0), odd)
    assert "a%20b%2Fc" not in caught.value.message


# ------------------------------------------------------------------ API Loop


def loop_with(
    handler: Any, monkeypatch: pytest.MonkeyPatch, rows: int, **options: Any
) -> tuple[Any, list[str]]:
    calls: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(record))
    monkeypatch.setattr(api_module, "RETRY_BASE_SECONDS", 0)
    df = pl.DataFrame({"id": [str(i) for i in range(rows)]})
    source = options.pop("source", ApiDefinition(url="https://exemplo.com/{id}"))
    options.setdefault("per_second", 0)
    options.setdefault("concurrency", 1)
    return run_loop(df, source, secret, **options), calls


def test_limit_counts_real_requests_with_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    n = {"v": 0}

    def paged(_r: httpx.Request) -> httpx.Response:
        n["v"] += 1
        return httpx.Response(200, json=[{"a": n["v"]}])

    source = ApiDefinition(
        url="https://exemplo.com/{id}", pagination=ApiPagination(type="page", max_pages=100)
    )
    out, calls = loop_with(paged, monkeypatch, 20, source=source, max_calls=20)
    assert len(calls) == 20 and out.requests == 20
    assert "limite de 20 pedidos" in out.stopped
    assert out.errors.height == 20  # nada some: o que não terminou vai para E


def test_limit_counts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    out, calls = loop_with(
        lambda _r: httpx.Response(503), monkeypatch, 20, max_calls=30, stop_after_failures=0
    )
    assert len(calls) == 30 and out.errors.height == 20


def test_stops_after_failures_in_a_row(monkeypatch: pytest.MonkeyPatch) -> None:
    out, calls = loop_with(lambda _r: httpx.Response(401), monkeypatch, 500, stop_after_failures=10)
    assert len(calls) == 10
    assert "10 falhas seguidas" in out.stopped and "credenciais" in out.stopped
    assert out.errors.height == 500
    assert out.errors["status_http"].drop_nulls().len() == 10
    assert "Não foi chamada" in out.errors["erro"][20]


def test_a_success_resets_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    def alternate(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if int(request.url.path[1:]) % 2 else 200, json=[{"a": 1}])

    out, calls = loop_with(alternate, monkeypatch, 40, stop_after_failures=3)
    assert len(calls) == 40 and out.stopped == ""


def test_zero_never_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    _out, calls = loop_with(lambda _r: httpx.Response(401), monkeypatch, 30, stop_after_failures=0)
    assert len(calls) == 30


def test_tool_warns_when_it_stops(runner: WorkflowRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from prodata.connectors.api_model import SavedApi

    assert runner.apis is not None
    runner.apis.save(SavedApi(id="det", name="D", url="https://x.com/{v}"))
    monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(lambda _r: httpx.Response(401)))
    rows = [[str(i)] for i in range(30)]
    flow = Workflow.model_validate(
        {
            "id": "wf-stop",
            "name": "x",
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "label": "T",
                    "config": {"table": {"columns": ["v"], "rows": rows}},
                },
                {
                    "id": "l",
                    "type": "io.api_loop",
                    "label": "L",
                    "config": {
                        "source": "det",
                        "calls_per_second": 0,
                        "concurrency": 1,
                        "stop_after_failures": 5,
                    },
                },
            ],
            "edges": [{"id": "e", "source": "t", "sourceHandle": "out", "target": "l", "targetHandle": "in"}],
        }
    )
    result = runner.run(flow).node_results["l"]
    assert result.status == "executed" and result.extra["api_requests"] == 5
    assert "Parou antes do fim" in result.extra["warnings"][0]


def test_client_limit_is_off_by_default(seen: list[httpx.Request]) -> None:
    with ApiClient(ApiDefinition(url="https://exemplo.com/x"), secret) as client:
        for _ in range(3):
            client.fetch()
    assert client.requests == 3


# ------------------------------------------------------------------ rótulos


def output(store: DatasetStore, tmp_path: Path, inputs: dict[str, pl.DataFrame], **config: Any) -> Any:
    spec = REGISTRY["io.output_data"]
    return spec.run(NodeContext(inputs, {}, store, tmp_path), spec.config.model_validate(config))


TABLE = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})


def label_of(path: Path) -> str:
    book = load_workbook(path)
    return next(p.value for p in book.custom_doc_props.props if p.name == EXCEL_PROPERTY)


@pytest.mark.parametrize(
    ("level", "name"),
    [
        ("publico", "Público"),
        ("interno", "Interno"),
        ("confidencial", "Confidencial"),
        ("restrito", "Restrito"),
    ],
)
def test_excel_carries_the_label(level: str, name: str, store: DatasetStore, tmp_path: Path) -> None:
    output(
        store,
        tmp_path,
        {"in": TABLE},
        filename="r",
        format="excel",
        confidentiality=level,
        if_exists="replace",
    )
    book = load_workbook(tmp_path / "r.xlsx")
    assert label_of(tmp_path / "r.xlsx") == name
    assert book.properties.category == name
    assert name in book["Dados"].oddHeader.center.text
    assert book["Dados"].sheet_properties.tabColor is not None


def test_label_does_not_touch_the_cells(store: DatasetStore, tmp_path: Path) -> None:
    output(
        store,
        tmp_path,
        {"in": TABLE},
        filename="r",
        format="excel",
        confidentiality="restrito",
        if_exists="replace",
    )
    excel = fastexcel.read_excel(tmp_path / "r.xlsx")
    assert excel.sheet_names == ["Dados"]
    assert excel.load_sheet("Dados").to_polars().equals(TABLE)


def test_every_sheet_gets_the_label(store: DatasetStore, tmp_path: Path) -> None:
    output(
        store,
        tmp_path,
        {"in": TABLE, "in2": TABLE},
        filename="r",
        format="excel",
        confidentiality="confidencial",
        if_exists="replace",
    )
    book = load_workbook(tmp_path / "r.xlsx")
    assert all("Confidencial" in s.oddHeader.center.text for s in book.worksheets)


def test_adding_a_sheet_keeps_the_most_restrictive(store: DatasetStore, tmp_path: Path) -> None:
    output(
        store,
        tmp_path,
        {"in": TABLE},
        filename="r",
        format="excel",
        sheet_name="A",
        confidentiality="restrito",
        if_exists="replace",
    )
    output(
        store,
        tmp_path,
        {"in": TABLE},
        filename="r",
        format="excel",
        sheet_name="B",
        confidentiality="publico",
        if_exists="add_sheet",
    )
    assert label_of(tmp_path / "r.xlsx") == "Restrito"
    output(
        store,
        tmp_path,
        {"in": TABLE},
        filename="s",
        format="excel",
        sheet_name="A",
        confidentiality="publico",
        if_exists="replace",
    )
    output(
        store,
        tmp_path,
        {"in": TABLE},
        filename="s",
        format="excel",
        sheet_name="B",
        confidentiality="confidencial",
        if_exists="add_sheet",
    )
    assert label_of(tmp_path / "s.xlsx") == "Confidencial"
    assert load_workbook(tmp_path / "s.xlsx").sheetnames == ["A", "B"]


def test_adding_to_a_file_without_a_label(store: DatasetStore, tmp_path: Path) -> None:
    TABLE.write_excel(tmp_path / "v.xlsx", worksheet="Velha")
    output(
        store,
        tmp_path,
        {"in": TABLE},
        filename="v",
        format="excel",
        sheet_name="Nova",
        confidentiality="confidencial",
        if_exists="add_sheet",
    )
    assert label_of(tmp_path / "v.xlsx") == "Confidencial"
    assert load_workbook(tmp_path / "v.xlsx").sheetnames == ["Velha", "Nova"]


@pytest.mark.parametrize(
    ("fmt", "level", "name"),
    [
        ("csv", "interno", "r.csv"),
        ("csv", "publico", "r.csv"),
        ("csv", "confidencial", "r_CONFIDENCIAL.csv"),
        ("parquet", "restrito", "r_RESTRITO.parquet"),
        ("json", "restrito", "r_RESTRITO.json"),
        ("arrow", "confidencial", "r_CONFIDENCIAL.arrow"),
        ("excel", "restrito", "r.xlsx"),
    ],
)
def test_other_formats_carry_it_in_the_name(
    fmt: str, level: str, name: str, store: DatasetStore, tmp_path: Path
) -> None:
    out = output(
        store, tmp_path, {"in": TABLE}, filename="r", format=fmt, confidentiality=level, if_exists="replace"
    )
    assert (tmp_path / name).exists(), [p.name for p in tmp_path.iterdir()]
    assert out.extra["exported_file"] == name


def test_old_flows_default_to_internal() -> None:
    cfg = REGISTRY["io.output_data"].config.model_validate({"filename": "x"})
    assert cfg.confidentiality == "interno"
    assert Dashboard.model_validate({"items": []}).confidentiality == "interno"


def test_unknown_label_is_refused() -> None:
    with pytest.raises(ValueError):
        REGISTRY["io.output_data"].config.model_validate({"confidentiality": "secreto"})


# ------------------------------------------------------------------ registro das exportações


def read_audit(settings: Any) -> list[dict[str, Any]]:
    path = Path(settings.storage_dir) / "logs" / audit.LOG_NAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_export_is_logged_without_the_data(settings: Any, store: DatasetStore, tmp_path: Path) -> None:
    build_services(settings)
    secret_row = pl.DataFrame({"cpf": ["111.222.333-44"]})
    output(
        store,
        tmp_path,
        {"in": secret_row},
        filename="r",
        format="csv",
        confidentiality="restrito",
        if_exists="replace",
    )
    entry = read_audit(settings)[-1]
    assert entry["arquivo"] == "r_RESTRITO.csv" and entry["rotulo"] == "Restrito"
    assert entry["linhas"] == 1 and entry["colunas"] == 1 and entry["usuario"]
    text = (Path(settings.storage_dir) / "logs" / audit.LOG_NAME).read_text(encoding="utf-8")
    assert "111.222" not in text and "cpf" not in text


def test_dashboard_export_is_logged(client: Any, settings: Any) -> None:
    res = client.post(
        "/api/dashboard/export-log",
        json={
            "kind": "HTML",
            "file": "p.html",
            "label": "confidencial",
            "rows": 3,
            "columns": 2,
            "password": True,
        },
    )
    assert res.status_code == 204
    entry = read_audit(settings)[-1]
    assert (
        entry["tipo"] == "Dashboard (HTML)" and entry["rotulo"] == "Confidencial" and entry["senha"] is True
    )


def test_export_log_refuses_bad_kind(client: Any) -> None:
    res = client.post("/api/dashboard/export-log", json={"kind": "EXE", "file": "x", "label": "interno"})
    assert res.status_code in (400, 422)


# ------------------------------------------------------------------ Summarize


DF = pl.DataFrame(
    {"t": ["a", "b"], "n": [1, 2], "d": [date(2026, 1, 1), date(2026, 1, 2)], "b": [True, False]}
)


def summarize(store: DatasetStore, tmp_path: Path, column: str, agg: str) -> pl.DataFrame:
    spec = REGISTRY["transform.summarize"]
    cfg = spec.config.model_validate({"aggregations": [{"column": column, "agg": agg, "alias": "x"}]})
    return spec.run(NodeContext({"in": DF}, {}, store, tmp_path), cfg).tables["out"]


@pytest.mark.parametrize(
    ("column", "agg", "word"),
    [
        ("t", "sum", "texto"),
        ("t", "mean", "texto"),
        ("t", "median", "texto"),
        ("t", "std", "texto"),
        ("d", "sum", "data"),
        ("d", "std", "data"),
    ],
)
def test_impossible_operation_explains_itself(
    column: str, agg: str, word: str, store: DatasetStore, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match=f"que é de {word}"):
        summarize(store, tmp_path, column, agg)


@pytest.mark.parametrize(("kind", "column"), [("String", "t"), ("Date", "d"), ("Boolean", "b")])
def test_every_offered_operation_works(kind: str, column: str, store: DatasetStore, tmp_path: Path) -> None:
    for agg in AGG_BY_TYPE[kind]:
        assert summarize(store, tmp_path, column, agg).height == 1, agg


def test_numbers_are_not_restricted(store: DatasetStore, tmp_path: Path) -> None:
    for agg in ("sum", "mean", "median", "std", "min", "max", "mode", "count", "n_unique", "first", "last"):
        assert summarize(store, tmp_path, "n", agg).height == 1


def test_catalog_describes_the_rule(client: Any) -> None:
    tools = client.get("/api/catalog").json()["tools"]
    spec = next(t for t in tools if t["type"] == "transform.summarize")
    field = next(f for f in spec["config_fields"] if f["name"] == "aggregations")
    agg = next(f for f in field["item_fields"] if f["name"] == "agg")
    assert "sum" not in agg["options_by_type"]["String"] and agg["source"] == "column"


# ------------------------------------------------------------------ Multi-Row com ordem

UNSORTED = pl.DataFrame(
    {
        "g": ["a", "b", "a", "b", "a"],
        "dia": [3, 2, 1, 1, 2],
        "v": [30, 20, 10, 5, 20],
        "s": [None, "y", "x", None, None],
    }
)


def multi(store: DatasetStore, tmp_path: Path, **config: Any) -> pl.DataFrame:
    spec = REGISTRY["prep.multirow"]
    cfg = spec.config.model_validate(config)
    return spec.run(NodeContext({"in": UNSORTED}, {}, store, tmp_path), cfg).tables["out"]


def test_order_by_defines_the_previous_row(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(
        store, tmp_path, column="p", expression="[Row-1:v]", order_by=[{"column": "dia"}], group_by=["g"]
    )
    rows = {(r["g"], r["dia"]): r["p"] for r in out.to_dicts()}
    assert rows == {("a", 1): None, ("a", 2): 10, ("a", 3): 20, ("b", 1): None, ("b", 2): 5}
    assert out["dia"].to_list() == [1, 1, 2, 2, 3]


def test_order_by_several_columns_and_direction(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(
        store,
        tmp_path,
        column="p",
        expression="[Row-1:v]",
        order_by=[{"column": "g"}, {"column": "dia", "descending": True}],
    )
    assert out.select("g", "dia").rows() == [("a", 3), ("a", 2), ("a", 1), ("b", 2), ("b", 1)]
    assert out["p"].to_list() == [None, 30, 20, 10, 20]


def test_fill_down_follows_the_order(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(
        store,
        tmp_path,
        target="existing",
        existing="s",
        expression="IF IsNull([s]) THEN [Row-1:s] ELSE [s] ENDIF",
        order_by=[{"column": "dia"}],
        group_by=["g"],
    )
    assert {(r["g"], r["dia"]): r["s"] for r in out.to_dicts()}[("a", 3)] == "x"


def test_empty_order_keeps_arrival(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(store, tmp_path, column="p", expression="[Row-1:v]", order_by=[{"column": ""}])
    assert out["dia"].to_list() == UNSORTED["dia"].to_list()


def test_order_by_unknown_column_explains(store: DatasetStore, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ordenação inexistente"):
        multi(store, tmp_path, column="p", expression="[Row-1:v]", order_by=[{"column": "sumiu"}])


def test_sort_is_found_by_order_by(client: Any) -> None:
    tools = client.get("/api/catalog").json()["tools"]
    assert "order by" in next(t for t in tools if t["type"] == "prep.sort")["description"]


# ------------------------------------------------------------------ Multi-Row: receitas e filtro por clique

RECIPE_FORMULAS = {
    "diff": "[v] - [Row-1:v]",
    "pct": "IF IsNull([Row-1:v]) OR [Row-1:v] = 0 THEN Null ELSE ([v] - [Row-1:v]) / [Row-1:v] * 100 ENDIF",
    "prev": "[Row-1:v]",
    "next": "[Row+1:v]",
    "changed": "IF IsNull([Row-1:v]) THEN 'Início' ELSEIF [v] == [Row-1:v] THEN 'Igual' ELSE 'Mudou' ENDIF",
}


@pytest.mark.parametrize(
    ("recipe", "expected"),
    [
        ("diff", [None, 10.0, -20.0, 0.0]),
        ("pct", [None, 100 * 10 / 10, -100 * 20 / 20, None]),
        ("prev", [None, 10.0, 20.0, 0.0]),
        ("next", [20.0, 0.0, 0.0, None]),
        ("changed", ["Início", "Mudou", "Mudou", "Igual"]),
    ],
)
def test_recipe_formulas_on_the_engine(recipe: str, expected: list[Any]) -> None:
    df = pl.DataFrame({"v": [10.0, 20.0, 0.0, 0.0]})
    rule = {
        "target": "new",
        "column": "r",
        "existing": "",
        "type": "Auto",
        "expression": RECIPE_FORMULAS[recipe],
    }
    assert multirow.evaluate(df, rule, [], "null")["r"].to_list() == expected


def test_fill_down_into_a_new_column_covers_consecutive_blanks() -> None:
    df = pl.DataFrame({"v": [1.0, None, None, 4.0]})
    rule = {
        "target": "new",
        "column": "cheio",
        "existing": "",
        "type": "Auto",
        "expression": "IF IsNull([v]) THEN [Row-1:cheio] ELSE [v] ENDIF",
    }
    assert multirow.evaluate(df, rule, [], "null")["cheio"].to_list() == [1.0, 1.0, 1.0, 4.0]


def test_old_multirow_config_stays_free_formula() -> None:
    cfg = MultiRowConfig.model_validate({"column": "a", "expression": "[Row-1:v]"})
    assert (cfg.recipe, cfg.base, cfg.distance, cfg.expression) == ("custom", "", 1, "[Row-1:v]")


@pytest.mark.parametrize("chart", ["bar", "hbar", "donut", "pareto"])
def test_chart_keeps_its_own_categories_under_a_filter(chart: str) -> None:
    own = DashFilter(id="a", column="uf", kind="list", selected=["SP"])
    other = DashFilter(id="b", column="setor", kind="list", selected=["TI"])
    config = ChartConfig(chart_type=chart, x_column="uf")  # type: ignore[arg-type]
    assert filters_for(config, [own, other]) == [other]


def test_other_visuals_still_follow_the_filter() -> None:
    own = DashFilter(id="a", column="uf", kind="list", selected=["SP"])
    assert filters_for(ChartConfig(chart_type="line", x_column="uf"), [own]) == [own]
    assert filters_for(KpiConfig(), [own]) == [own]
    # Faixa numérica na coluna da categoria continua filtrando: não há categoria para apagar.
    band = DashFilter(id="c", column="uf", kind="number", min=1)
    assert filters_for(ChartConfig(chart_type="bar", x_column="uf"), [band]) == [band]


# ------------------------------------------------------------------ fórmula e SQL sem acesso externo (spec 027)

FILE_READS = [
    "(SELECT content FROM read_text('{path}'))",
    "(SELECT count(*) FROM read_csv('{path}', header=false))",
    "(SELECT count(*) FROM glob('{folder}/*'))",
    "(SELECT count(*) FROM read_csv('https://example.invalid/x.csv'))",
]


@pytest.mark.parametrize("template", FILE_READS)
def test_formula_cannot_reach_files_or_the_internet(template: str, tmp_path: Path) -> None:
    secret = tmp_path / "segredo.txt"
    secret.write_text("SEGREDO", encoding="utf-8")
    expression = template.format(path=secret.as_posix(), folder=tmp_path.as_posix())
    rule = {"target": "new", "column": "x", "type": "Auto", "expression": expression}
    with pytest.raises(formula.FormulaError, match="não acessam arquivos"):
        formula.evaluate_columns(pl.DataFrame({"v": [1]}), [rule])


def test_formula_cannot_turn_external_access_back_on() -> None:
    with formula.connect() as con, pytest.raises(duckdb.Error):
        con.execute("SET enable_external_access = true")


@pytest.mark.parametrize("template", FILE_READS)
def test_sql_box_cannot_reach_files_or_the_internet(
    template: str, store: DatasetStore, tmp_path: Path
) -> None:
    secret = tmp_path / "segredo.txt"
    secret.write_text("SEGREDO", encoding="utf-8")
    sql = "SELECT " + template.format(path=secret.as_posix(), folder=tmp_path.as_posix())
    spec = REGISTRY["transform.sql_query"]
    ctx = NodeContext({"in": pl.DataFrame({"v": [1]})}, {}, store, tmp_path)
    with pytest.raises(ValueError, match="não acessam arquivos"):
        spec.run(ctx, spec.config.model_validate({"sql": sql}))


def test_sql_box_still_reads_its_inputs(store: DatasetStore, tmp_path: Path) -> None:
    spec = REGISTRY["transform.sql_query"]
    ctx = NodeContext({"in": pl.DataFrame({"v": [1, 2]})}, {}, store, tmp_path)
    out = spec.run(ctx, spec.config.model_validate({"sql": "SELECT sum(v) AS t FROM input_1"}))
    assert out.tables["out"]["t"].to_list() == [3]


def test_interface_has_a_content_policy(client: Any) -> None:
    res = client.get("/")
    policy = res.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "unsafe-eval" not in policy
    assert "connect-src 'self'" in policy
    assert res.headers["x-content-type-options"] == "nosniff"
