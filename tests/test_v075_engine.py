"""Spec 033: execução sem clique, Compare Runs, subfluxos, modelos com versão, modelo de Excel e memória do cache."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table

from prodata import cli
from prodata.config import Settings
from prodata.connectors.secrets import MemorySecretStore, installation_key
from prodata.domain.workflow import Workflow
from prodata.engine.cache import NodeEntry, ResultCache, StoredTables
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.nodes import control
from prodata.services.workflows import WorkflowRepository


@pytest.fixture
def library(tmp_path: Path) -> WorkflowRepository:
    return WorkflowRepository(tmp_path / "workflows")


@pytest.fixture
def engine(tmp_path: Path, store: DatasetStore, library: WorkflowRepository) -> WorkflowRunner:
    exports = tmp_path / "exports"
    exports.mkdir()
    secrets = MemorySecretStore()
    return WorkflowRunner(
        ResultCache(tmp_path / "cache"),
        store,
        exports,
        state_dir=tmp_path / "estado",
        workflows=library,
        secret_key=lambda: installation_key(secrets),
    )


def table_node(node_id: str, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"id": node_id, "type": "io.text_input", "config": {"table": {"columns": columns, "rows": rows}}}


def flow(flow_id: str, nodes: list[dict[str, Any]], edges: list[tuple[str, str, str, str]]) -> Workflow:
    return Workflow.model_validate(
        {
            "id": flow_id,
            "name": flow_id,
            "nodes": nodes,
            "edges": [
                {"id": f"e{i}", "source": s, "sourceHandle": sh, "target": t, "targetHandle": th}
                for i, (s, sh, t, th) in enumerate(edges)
            ],
        }
    )


def out_table(engine: WorkflowRunner, workflow: Workflow, node: str, port: str = "out") -> pl.DataFrame:
    entry = engine.cache.get(workflow.id, node)
    assert entry is not None
    return entry.tables[port]


# ------------------------------------------------------------------ Compare Runs


def compare_flow(rows: list[list[Any]], **config: Any) -> Workflow:
    return flow(
        "fechamento",
        [
            table_node("dados", ["id", "valor", "status"], rows),
            {"id": "cmp", "type": "control.compare_runs", "config": config},
        ],
        [("dados", "out", "cmp", "in")],
    )


def test_compare_runs_shows_what_changed_since_another_day(
    engine: WorkflowRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 30))
    first = engine.run(compare_flow([[1, 10, "a"], [2, 20, "a"], [3, 30, "a"]], keys=["id"]))
    assert "Primeira execução" in first.node_results["cmp"].extra["warnings"][0]

    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 31))
    wf = compare_flow([[1, 10, "a"], [2, 25, "b"], [4, 40, "a"]], keys=["id"])
    report = engine.run(wf)
    assert report.node_results["cmp"].extra["compare_baseline"] == "2026-10-30"
    diff = out_table(engine, wf, "cmp", "D")
    assert diff.rows() == [
        ("2", "mudou", "valor", "20", "25"),
        ("2", "mudou", "status", "a", "b"),
        ("3", "saiu", None, None, None),
        ("4", "novo", None, None, None),
    ]
    totals = {r["medida"]: r for r in out_table(engine, wf, "cmp", "T").iter_rows(named=True)}
    assert totals["linhas"]["antes"] == 3 and totals["linhas"]["diferenca"] == 0
    assert totals["soma de valor"]["antes"] == 60 and totals["soma de valor"]["agora"] == 75
    assert totals["soma de valor"]["variacao_pct"] == 25.0


def test_same_day_reruns_keep_the_previous_day_as_base(
    engine: WorkflowRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 30))
    engine.run(compare_flow([[1, 10, "a"]], keys=["id"]))
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 31))
    engine.run(compare_flow([[1, 11, "a"]], keys=["id"]))
    wf = compare_flow([[1, 12, "a"]], keys=["id"])
    engine.run(wf)
    assert out_table(engine, wf, "cmp", "D")["antes"].to_list() == ["10"]


def test_month_baseline_and_totals_without_keys(
    engine: WorkflowRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control, "today", lambda: date(2026, 9, 28))
    engine.run(compare_flow([[1, 10, "a"]], baseline="month"))
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 2))
    engine.run(compare_flow([[1, 50, "a"]], baseline="month"))
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 3))
    wf = compare_flow([[1, 70, "a"]], baseline="month")
    report = engine.run(wf)
    assert report.node_results["cmp"].extra["compare_baseline"] == "2026-09-28"
    assert out_table(engine, wf, "cmp", "D").height == 0
    assert out_table(engine, wf, "cmp", "T").filter(pl.col("medida") == "soma de valor")["antes"][0] == 10


def test_compare_runs_refuses_a_key_that_repeats(
    engine: WorkflowRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 30))
    engine.run(compare_flow([[1, 10, "a"]], keys=["id"]))
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 31))
    report = engine.run(compare_flow([[1, 10, "a"], [1, 11, "a"]], keys=["id"]))
    assert "repete" in (report.node_results["cmp"].error or "")


def test_old_snapshots_are_pruned(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    for day in ("2025-01-31", "2026-05-10", "2026-05-31", "2026-09-30", "2026-10-29"):
        (folder / f"{day}.parquet").write_bytes(b"")
    control._prune(folder, date(2026, 10, 30))
    assert sorted(p.stem for p in folder.glob("*.parquet")) == ["2026-05-31", "2026-09-30", "2026-10-29"]


# ------------------------------------------------------------------ subfluxos


def child_flow(expression: str = "[v] * 2") -> Workflow:
    return flow(
        "padroniza",
        [
            {"id": "entra", "type": "flow.input", "config": {"number": 1}},
            {
                "id": "calc",
                "type": "prep.formula",
                "label": "Dobro",
                "config": {"formulas": [{"column": "dobro", "expression": expression}]},
            },
            {"id": "sai", "type": "flow.output", "config": {"number": 1}},
        ],
        [("entra", "out", "calc", "in"), ("calc", "out", "sai", "in")],
    )


def parent_flow(child: str = "padroniza") -> Workflow:
    return flow(
        "principal",
        [
            table_node("dados", ["v"], [[1], [2]]),
            {"id": "sub", "type": "flow.subflow", "config": {"workflow": child}},
        ],
        [("dados", "out", "sub", "in")],
    )


def test_subflow_runs_another_flow_as_a_step(engine: WorkflowRunner, library: WorkflowRepository) -> None:
    library.save(child_flow())
    parent = parent_flow()
    assert engine.run(parent).node_results["sub"].status == "executed"
    assert out_table(engine, parent, "sub")["dobro"].to_list() == [2, 4]
    assert engine.run(parent).node_results["sub"].status == "cached"


def test_changing_the_source_flow_changes_who_uses_it(
    engine: WorkflowRunner, library: WorkflowRepository
) -> None:
    library.save(child_flow())
    parent = parent_flow()
    engine.run(parent)
    library.save(child_flow("[v] * 10"))
    assert engine.run(parent).node_results["sub"].status == "executed"
    assert out_table(engine, parent, "sub")["dobro"].to_list() == [10, 20]


def test_error_inside_the_subflow_names_the_inner_box(
    engine: WorkflowRunner, library: WorkflowRepository
) -> None:
    library.save(child_flow("[nao_existe] + 1"))
    result = engine.run(parent_flow()).node_results["sub"]
    assert result.status == "error"
    assert "Subfluxo 'padroniza': a caixa 'Dobro' falhou" in (result.error or "")


def test_subflow_cannot_call_itself(engine: WorkflowRunner, library: WorkflowRepository) -> None:
    loop = flow(
        "laco",
        [
            {"id": "entra", "type": "flow.input", "config": {}},
            {"id": "sub", "type": "flow.subflow", "config": {"workflow": "laco"}},
            {"id": "sai", "type": "flow.output", "config": {}},
        ],
        [("entra", "out", "sub", "in"), ("sub", "out", "sai", "in")],
    )
    library.save(loop)
    result = engine.run(parent_flow("laco")).node_results["sub"]
    assert "chamando a si mesmo" in (result.error or "")


def test_subflow_problems_are_explained(engine: WorkflowRunner, library: WorkflowRepository) -> None:
    assert "não está na biblioteca" in (engine.run(parent_flow("sumiu")).node_results["sub"].error or "")
    assert "Escolha o fluxo" in (engine.run(parent_flow("")).node_results["sub"].error or "")
    library.save(flow("sem_saida", [{"id": "entra", "type": "flow.input", "config": {}}], []))
    assert "Subflow Output" in (engine.run(parent_flow("sem_saida")).node_results["sub"].error or "")


def test_source_flow_runs_alone_with_a_test_table(engine: WorkflowRunner) -> None:
    alone = child_flow()
    assert "tabela de teste" in (engine.run(alone).node_results["entra"].error or "")
    data = alone.model_dump(mode="json", by_alias=True)
    data["nodes"].append(table_node("teste", ["v"], [[7]]))
    data["edges"].append(
        {"id": "t", "source": "teste", "sourceHandle": "out", "target": "entra", "targetHandle": "in"}
    )
    with_test = Workflow.model_validate(data)
    engine.run(with_test)
    assert out_table(engine, with_test, "sai")["dobro"].to_list() == [14]


# ------------------------------------------------------------------ modelos com versão


def ml_flow(rows: int = 60, **config: Any) -> Workflow:
    data = [[i, i % 7, "sim" if i % 2 else "nao"] for i in range(rows)]
    trainer = {"task_type": "classification", "target_column": "alvo", **config}
    return flow(
        "modelo",
        [
            table_node("dados", ["a", "b", "alvo"], data),
            {"id": "treino", "type": "ml.automl_trainer", "config": trainer},
        ],
        [("dados", "out", "treino", "in")],
    )


def test_fixed_model_is_reused_when_the_data_changes(engine: WorkflowRunner, tmp_path: Path) -> None:
    first = engine.run(ml_flow()).node_results["treino"]
    assert first.extra["ml_model"] == {**first.extra["ml_model"], "version": 1, "reused": False, "rows": 60}
    assert (tmp_path / "estado/modelo/treino/v1.joblib").is_file()

    second = engine.run(ml_flow(rows=80)).node_results["treino"]
    assert second.status == "executed" and second.extra["ml_model"]["reused"] is True
    assert second.extra["ml_model"]["rows"] == 60
    assert "Os dados mudaram desde então" in second.extra["warnings"][0]
    assert second.extra["ml_metrics"] == first.extra["ml_metrics"]


def test_raising_the_version_trains_again_and_keeps_the_old_one(
    engine: WorkflowRunner, tmp_path: Path
) -> None:
    engine.run(ml_flow())
    result = engine.run(ml_flow(rows=80, version=2)).node_results["treino"]
    assert result.extra["ml_model"]["rows"] == 80 and result.extra["ml_model"]["versions"] == [1, 2]
    assert "warnings" not in result.extra
    back = engine.run(ml_flow(rows=80, version=1)).node_results["treino"]
    assert back.extra["ml_model"]["rows"] == 60


def test_fixed_model_refuses_another_setup(engine: WorkflowRunner) -> None:
    engine.run(ml_flow())
    result = engine.run(ml_flow(algorithm="linear")).node_results["treino"]
    assert result.status == "error" and "Aumente a Versão" in (result.error or "")


def test_training_always_creates_versions_and_says_so(engine: WorkflowRunner) -> None:
    engine.run(ml_flow(training="always"))
    again = engine.run(ml_flow(rows=80, training="always")).node_results["treino"]
    assert again.extra["ml_model"]["version"] == 2
    assert "Modelo treinado de novo (v2)" in again.extra["warnings"][0]
    same = engine.run(ml_flow(rows=80, training="always", holdout_ratio=0.25)).node_results["treino"]
    assert same.extra["ml_model"]["version"] == 2


def test_tampered_model_file_is_refused(engine: WorkflowRunner, tmp_path: Path) -> None:
    engine.run(ml_flow())
    (tmp_path / "estado/modelo/treino/v1.joblib").write_bytes(b"outra coisa")
    result = engine.run(ml_flow(rows=80)).node_results["treino"]
    assert result.status == "error" and "mudou fora do programa" in (result.error or "")


# ------------------------------------------------------------------ modelo de Excel


@pytest.fixture
def template(tmp_path: Path) -> Path:
    book = Workbook()
    ws = book.active
    assert ws is not None
    ws.title = "Resumo"
    ws["A1"] = "Fechamento"
    ws["A1"].font = Font(bold=True, size=16)
    for i, name in enumerate(["uf", "valor"], start=1):
        ws.cell(row=3, column=i, value=name).font = Font(bold=True)
    for r in range(4, 9):
        ws.cell(row=r, column=1, value="antigo")
        ws.cell(row=r, column=2, value=1)
    ws["D4"] = "=SUM(B4:B100)"
    ws.column_dimensions["A"].width = 33
    ws.add_table(Table(displayName="Dados", ref="A3:B8"))
    path = tmp_path / "modelo.xlsx"
    book.save(path)
    return path


def excel_flow(model: Path, folder: Path, **config: Any) -> Workflow:
    out = {
        "filename": "saida",
        "folder": str(folder),
        "format": "excel",
        "if_exists": "replace",
        "template": str(model),
        **config,
    }
    return flow(
        "excel",
        [
            table_node("dados", ["uf", "valor"], [["SP", 10], ["RJ", 20]]),
            {"id": "grava", "type": "io.output_data", "config": out},
        ],
        [("dados", "out", "grava", "in")],
    )


def test_output_fills_a_copy_of_the_template(engine: WorkflowRunner, template: Path, tmp_path: Path) -> None:
    before = template.read_bytes()
    result = engine.run(excel_flow(template, tmp_path, template_cell="A3")).node_results["grava"]
    assert result.status == "executed" and result.extra["exported_template"] == "modelo.xlsx"
    assert template.read_bytes() == before
    ws = load_workbook(tmp_path / "saida.xlsx")["Resumo"]
    assert [[c.value for c in row] for row in ws["A3:B8"]] == [
        ["uf", "valor"], ["SP", 10], ["RJ", 20], [None, None], [None, None], [None, None],
    ]  # fmt: skip
    assert ws["A1"].font.bold and ws["A1"].font.size == 16 and ws["A3"].font.bold
    assert ws["D4"].value == "=SUM(B4:B100)" and ws.column_dimensions["A"].width == 33
    assert ws.tables["Dados"].ref == "A3:B5"


def test_template_without_header_or_clearing(engine: WorkflowRunner, template: Path, tmp_path: Path) -> None:
    config = {"template_cell": "A4", "template_header": False, "template_clear": False}
    engine.run(excel_flow(template, tmp_path, **config))
    ws = load_workbook(tmp_path / "saida.xlsx")["Resumo"]
    assert ws["A3"].value == "uf" and ws["A4"].value == "SP" and ws["A6"].value == "antigo"


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"template": "modelo.xlsx"}, "caminho completo"),
        ({"sheet_name": "Outra"}, "não tem a planilha"),
        ({"template_cell": "9Z"}, "não é uma célula"),
        ({"if_exists": "add_sheet"}, "não combina com modelo"),
        ({"filename": "modelo"}, "próprio modelo"),
    ],
)
def test_template_problems_are_explained(
    engine: WorkflowRunner, template: Path, tmp_path: Path, config: dict[str, Any], message: str
) -> None:
    result = engine.run(excel_flow(template, tmp_path, **config)).node_results["grava"]
    assert message in (result.error or ""), result.error


# ------------------------------------------------------------------ memória do cache


def test_cache_moves_old_tables_to_disk_and_brings_them_back(tmp_path: Path) -> None:
    cache = ResultCache(tmp_path / "cache", memory_bytes=1)
    first = pl.DataFrame({"x": list(range(1000))})
    cache.put("wf", "a", NodeEntry("f1", tables={"out": first}))
    cache.put("wf", "b", NodeEntry("f2", tables={"out": pl.DataFrame({"y": [1, 2]})}))
    entry = cache.get("wf", "a")
    assert entry is not None and isinstance(entry.tables, StoredTables)
    assert entry.tables.in_memory() == 0 and list(entry.tables) == ["out"] and "out" in entry.tables
    assert entry.tables["out"].equals(first)


def test_cache_keeps_everything_in_memory_under_the_limit(tmp_path: Path) -> None:
    cache = ResultCache(tmp_path / "cache", memory_bytes=10**9)
    cache.put("wf", "a", NodeEntry("f1", tables={"out": pl.DataFrame({"x": [1]})}))
    cache.put("wf", "b", NodeEntry("f2", tables={"out": pl.DataFrame({"y": [1]})}))
    entry = cache.get("wf", "a")
    assert entry is not None and isinstance(entry.tables, StoredTables) and entry.tables.in_memory() > 0
    assert cache.memory_used() > 0


def test_flow_runs_the_same_with_almost_no_memory(
    tmp_path: Path, store: DatasetStore, demo: Workflow
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    tight = WorkflowRunner(ResultCache(tmp_path / "c1", memory_bytes=1), store, exports)
    roomy = WorkflowRunner(ResultCache(tmp_path / "c2", memory_bytes=10**9), store, exports)
    skip = {"n_api_estados", "n_api_municipios", "n_api_join"}
    a, b = tight.run(demo), roomy.run(demo)
    for node_id, result in b.node_results.items():
        if node_id in skip or result.status != "executed":
            continue
        assert a.node_results[node_id].status == "executed", (node_id, a.node_results[node_id].error)
        assert {p: s.row_count for p, s in a.node_results[node_id].anchors.items()} == {
            p: s.row_count for p, s in result.anchors.items()
        }
    errors = {k: v.error for k, v in tight.run(demo).node_results.items() if v.status == "error"}
    assert {k: e for k, e in errors.items() if k not in skip} == {}


def test_missing_cache_file_asks_to_run_again(tmp_path: Path, store: DatasetStore) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    runner = WorkflowRunner(ResultCache(tmp_path / "cache", memory_bytes=1), store, exports)
    wf = flow(
        "some",
        [
            table_node("a", ["v"], [[1]]),
            table_node("b", ["v"], [[2]]),
            {"id": "s", "type": "prep.sort", "config": {}},
        ],
        [("a", "out", "s", "in")],
    )
    runner.run(wf)
    for path in (tmp_path / "cache" / "some").glob("a__*.arrow"):
        path.unlink()
    wf.node("s").config["sorts"] = [{"column": "v"}]
    result = runner.run(wf).node_results["s"]
    assert result.status == "skipped" and "execute o fluxo de novo" in (result.error or "")
    assert runner.run(wf).node_results["s"].status == "executed"


# ------------------------------------------------------------------ linha de comando


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(storage_dir=tmp_path / "storage", secrets_backend="memory", seed_samples=False)
    for key, value in (
        ("STORAGE_DIR", str(settings.storage_dir)),
        ("SECRETS_BACKEND", "memory"),
        ("SEED_SAMPLES", "false"),
    ):
        monkeypatch.setenv(f"PRODATA_{key}", value)
    return settings


def saved_flow(settings: Settings, workflow: Workflow) -> None:
    from prodata.main import build_services

    services = build_services(settings)
    services.workflows.save(workflow)
    services.trust.created(workflow)


def simple_flow(folder: Path, expression: str = "[v] + 1") -> Workflow:
    out = {"filename": "pronto", "folder": str(folder), "format": "csv", "if_exists": "ask"}
    return flow(
        "noturno",
        [
            table_node("dados", ["v"], [[1], [2]]),
            {
                "id": "calc",
                "type": "prep.formula",
                "label": "Soma um",
                "config": {"formulas": [{"column": "w", "expression": expression}]},
            },
            {"id": "grava", "type": "io.output_data", "config": out},
        ],
        [("dados", "out", "calc", "in"), ("calc", "out", "grava", "in")],
    )


def test_run_executes_a_library_flow_and_exits_zero(
    cli_env: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    saved_flow(cli_env, simple_flow(tmp_path))
    assert cli.main(["run", "noturno", "--relatorio", str(tmp_path / "r.json")]) == cli.OK
    printed = capsys.readouterr().out
    assert "Concluído" in printed and "pronto.csv" in printed
    assert (tmp_path / "pronto.csv").read_text(encoding="utf-8").splitlines() == ["v;w", "1;2", "2;3"]
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["node_results"]["grava"]["status"] == "executed"
    assert len(list((cli_env.storage_dir / "logs" / "execucoes").glob("noturno_*.json"))) == 1


def test_run_never_overwrites_an_export_set_to_ask(cli_env: Settings, tmp_path: Path) -> None:
    saved_flow(cli_env, simple_flow(tmp_path))
    assert cli.main(["run", "noturno"]) == cli.OK
    assert cli.main(["run", "noturno", "--silencioso"]) == cli.OK
    assert len(list(tmp_path.glob("pronto*.csv"))) == 2


def test_run_exits_one_when_a_box_fails(
    cli_env: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    saved_flow(cli_env, simple_flow(tmp_path, "[nao_existe] + 1"))
    assert cli.main(["run", "noturno"]) == cli.FAILED
    printed = capsys.readouterr().out
    assert "[ERRO] Soma um" in printed and "FALHOU" in printed
    assert not list(tmp_path.glob("pronto*.csv"))


def test_run_refuses_a_file_nobody_checked(
    cli_env: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    saved_flow(
        cli_env, simple_flow(tmp_path)
    )  # só para a pasta de dados já existir com o registro de confiança
    outside = tmp_path / "recebido.prodata.json"
    stranger = simple_flow(tmp_path, "[v] * 100").model_copy(update={"id": "de_fora", "name": "De fora"})
    outside.write_text(stranger.model_dump_json(by_alias=True), encoding="utf-8")
    assert cli.main(["run", str(outside)]) == cli.REFUSED
    assert "ainda não foi conferido" in capsys.readouterr().err
    assert len(list(tmp_path.glob("pronto*.csv"))) == 0


def test_run_reports_a_flow_that_does_not_exist(
    cli_env: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["run", "nao_tem"]) == cli.REFUSED
    assert "Fluxo não encontrado" in capsys.readouterr().err


def test_no_command_means_open_the_server() -> None:
    assert cli.main([]) is None and cli.main(["serve"]) is None


# ------------------------------------------------------------------ biblioteca de modelos


def predict_flow(flow_id: str, model: str) -> Workflow:
    return flow(
        flow_id,
        [
            table_node("novos", ["a", "b"], [[1, 1], [2, 2], [3, 3]]),
            {"id": "modelo", "type": "ml.model_input", "config": {"model": model}},
            {"id": "aplica", "type": "ml.predictor", "config": {}},
        ],
        [("modelo", "M", "aplica", "M"), ("novos", "out", "aplica", "D")],
    )


def test_trained_model_is_used_in_another_flow(engine: WorkflowRunner, tmp_path: Path) -> None:
    trained = engine.run(ml_flow(publish_as="Churn clientes")).node_results["treino"]
    assert trained.extra["ml_published"] == "Churn_clientes"
    assert (tmp_path / "modelos" / "Churn_clientes.modelo").is_file()

    other = predict_flow("outro_fluxo", "Churn_clientes")
    report = engine.run(other)
    assert report.node_results["modelo"].status == "executed", report.node_results["modelo"].error
    card = report.node_results["modelo"].extra["ml_card"]
    assert card["target_column"] == "alvo" and card["feature_columns"] == ["a", "b"] and card["rows"] == 60
    assert card["origin"] == "modelo/treino" and card["version"] == 1
    predictions = out_table(engine, other, "aplica")
    assert predictions["predicao"].to_list() == [
        "true",
        "false",
        "true",
    ]  # o Text Input lê sim e nao como booleano
    assert out_table(engine, other, "modelo", "I").columns == ["variavel", "importancia_pct"]


def test_model_file_travels_between_computers(engine: WorkflowRunner, client: TestClient) -> None:
    from prodata.nodes import ml_library

    engine.run(ml_flow(publish_as="churn"))
    assert engine.state_dir is not None
    data = ml_library.file_bytes(ml_library.folder_of(engine.state_dir), "churn")
    files = {"file": ("churn.modelo", data, "application/octet-stream")}
    saved = client.post("/api/models/import", files=files, data={"name": "Churn importado"}).json()
    assert saved["name"] == "Churn_importado" and saved["algorithm"] == "random_forest"
    assert [m["name"] for m in client.get("/api/models").json()] == ["Churn_importado"]
    exported = client.get("/api/models/Churn_importado/export")
    assert exported.content == data and ".modelo" in exported.headers["content-disposition"]
    assert client.delete("/api/models/Churn_importado").status_code == 204
    assert client.get("/api/models").json() == []


def test_a_pickle_is_never_opened_as_a_model(client: TestClient, tmp_path: Path) -> None:
    import pickle

    class Danger:
        def __reduce__(self) -> tuple[Any, tuple[str, str]]:
            return (Path.write_text, (str(tmp_path / "executou.txt"), "x"))  # type: ignore[return-value]

    for name, data in (("x.modelo", pickle.dumps(Danger())), ("x.modelo", b"qualquer coisa"), ("x.pkl", b"")):
        res = client.post("/api/models/import", files={"file": (name, data, "application/octet-stream")})
        assert res.status_code == 400, res.text
    assert not (tmp_path / "executou.txt").exists()
    assert client.get("/api/models").json() == []


def test_model_file_with_something_else_inside_is_refused(tmp_path: Path) -> None:
    from skops.io import dumps

    from prodata.errors import InvalidInputError
    from prodata.nodes import ml_library

    class Stranger:
        pass

    with pytest.raises(InvalidInputError, match="não é um modelo do PRO"):
        ml_library.from_bytes(dumps({"model": Stranger()}))
    with pytest.raises(InvalidInputError, match="não é um modelo do PRO"):
        ml_library.from_bytes(dumps({"model": 1, "task_type": "x"}))


def test_model_input_explains_a_missing_model(engine: WorkflowRunner) -> None:
    result = engine.run(predict_flow("sem", "nao_tem")).node_results
    assert "não está na biblioteca" in (result["modelo"].error or "")
    assert result["aplica"].status == "skipped"


def test_saved_versions_are_listed_and_deleted_but_not_the_one_in_use(
    engine: WorkflowRunner, tmp_path: Path
) -> None:
    from prodata.errors import InvalidInputError
    from prodata.nodes import ml_store

    engine.run(ml_flow())
    engine.run(ml_flow(rows=80, version=2))
    folder = ml_store.node_folder(tmp_path / "estado", "modelo", "treino")
    listed = ml_store.listing(folder)
    assert [v["version"] for v in listed] == [2, 1] and listed[0]["rows"] == 80
    assert listed[1]["metrics"]["task"] == "classification" and listed[1]["trained_at"]
    with pytest.raises(InvalidInputError, match="está usando"):
        ml_store.delete(folder, 2, in_use=2)
    ml_store.delete(folder, 1, in_use=2)
    assert [v["version"] for v in ml_store.listing(folder)] == [2]
    assert not (folder / "v1.joblib").exists() and not (folder / "v1.json").exists()
    with pytest.raises(InvalidInputError, match="não está guardada"):
        ml_store.delete(folder, 1, in_use=2)
    assert engine.run(ml_flow(rows=80, version=2)).node_results["treino"].status in ("executed", "cached")


def test_versions_api(client: TestClient) -> None:
    assert client.get("/api/models/versions/fluxo/caixa").json() == []
    assert client.delete("/api/models/versions/fluxo/caixa/1?in_use=2").status_code == 400
    assert client.get("/api/models/versions/..%2Fx/caixa").status_code in (
        404,
        405,
        422,
    )  # nunca chega à pasta


def test_training_always_keeps_only_the_last_versions(
    engine: WorkflowRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prodata.nodes import ml_store

    monkeypatch.setattr(ml_store, "KEEP_ALWAYS", 3)
    for rows in (60, 64, 68, 72, 76):
        result = engine.run(ml_flow(rows=rows, training="always")).node_results["treino"]
    folder = ml_store.node_folder(tmp_path / "estado", "modelo", "treino")
    assert [v["version"] for v in ml_store.listing(folder)] == [5, 4, 3]
    assert result.extra["ml_model"]["version"] == 5 and result.extra["ml_model"]["rows"] == 76
