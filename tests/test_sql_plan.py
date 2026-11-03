"""Plano, código e conferência da aba SQL sobre fluxos inteiros (spec 020)."""

import json
import re
from pathlib import Path

import duckdb
import polars as pl
import pytest
from fastapi.testclient import TestClient

from prodata.domain.workflow import Workflow
from prodata.engine.runner import WorkflowRunner
from prodata.engine.sql.fragment import slug
from prodata.engine.sql.plan import NO_SQL, OK, Env, build_plan, temporary_output
from prodata.engine.sql.render import render, to_text
from prodata.engine.sql.verify import DIFFERENT, MISMATCH, PARTIAL, READY, SAME, compare, output_state, verify
from prodata.ingestion import DatasetStore

DATA = Path(__file__).parent / "data"


def env_for(runner: WorkflowRunner, store: DatasetStore, workflow: Workflow) -> Env:
    return Env(runner.cache, store, None, lambda node: runner.is_fresh(workflow, node))


def flow_with_outputs(demo: Workflow) -> Workflow:
    """Demonstração com duas tabelas a mais, antes do modelo, para testar a unificação."""
    raw = demo.model_dump(mode="json", by_alias=True)
    for node_id, source, port, name in (
        ("out_a", "n_join", "J", "clientes_ativos"),
        ("out_b", "n_atingimento", "out", "atingimento"),
    ):
        raw["nodes"].append(
            {
                "id": node_id,
                "type": "io.output_data",
                "label": name,
                "x": 0,
                "y": 0,
                "config": {"filename": name, "format": "csv", "if_exists": "replace"},
            }
        )
        raw["edges"].append(
            {
                "id": f"e_{node_id}",
                "source": source,
                "sourceHandle": port,
                "target": node_id,
                "targetHandle": "in",
            }
        )
    return Workflow.model_validate(raw)


def clean_duckdb(datasets: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(f"SET file_search_path = '{datasets.as_posix()}'")
    return con


def standalone(text: str, datasets: Path) -> pl.DataFrame:
    """Roda o código copiado como um usuário faria: DuckDB limpo, na pasta dos arquivos."""
    con = clean_duckdb(datasets)
    statements = con.extract_statements(text)
    for statement in statements[:-1]:
        con.execute(statement)
    return con.sql(statements[-1].query).pl()


def test_path_follows_ports_not_boxes(runner: WorkflowRunner, store: DatasetStore, demo: Workflow) -> None:
    flow = flow_with_outputs(demo)
    runner.run(flow)
    plan = build_plan(flow, env_for(runner, store, flow))
    output = plan.output("out_a|out")
    assert output is not None
    assert "n_join|J" in output.steps
    assert "n_join|L" not in output.steps and "n_join|R" not in output.steps
    assert "n_filter|T" in output.steps and "n_filter|F" not in output.steps
    assert not any(s.startswith("n_trainer") or s.startswith("n_metas") for s in output.steps)


def test_outputs_are_tables_visuals_and_loose_boxes(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    runner.run(demo)
    plan = build_plan(demo, env_for(runner, store, demo))
    kinds = {o.id: o.kind for o in plan.outputs}
    assert kinds["n_output|out"] == "table"
    assert kinds["n_pareto|out"] == "visual"
    # L e R do Join ficam soltas, mas a caixa tem outra saída conectada: não entram.
    assert not any(o.startswith("n_join") for o in kinds)


def test_model_boxes_have_no_translation_and_stop_the_path(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    runner.run(demo)
    plan = build_plan(demo, env_for(runner, store, demo))
    assert plan.blocks["n_trainer|M"].status == NO_SQL
    assert plan.blocks["n_predictor|out"].status == NO_SQL
    output = plan.output("n_output|out")
    assert output is not None and output.stop is not None and plan.blocks[output.stop].node_id == "n_trainer"
    assert output_state(plan, output, None)["state"] == PARTIAL
    text = to_text(render(plan, [output]))
    assert "Sem tradução" in text and text.rstrip().endswith(f"SELECT * FROM {plan.blocks['n_join|J'].name};")


def test_single_output_runs_alone_in_clean_duckdb(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow, tmp_path: Path
) -> None:
    flow = flow_with_outputs(demo)
    runner.run(flow)
    plan = build_plan(flow, env_for(runner, store, flow))
    for output_id in ("out_a|out", "out_b|out"):
        output = plan.output(output_id)
        assert output is not None
        text = to_text(render(plan, [output]))
        result = standalone(text, tmp_path / "datasets")
        expected = runner.cache.table(flow.id, output.node_id, output.port)
        assert compare(result, expected).state == SAME, output_id


def test_unified_code_repeats_nothing_and_matches_each_output(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow, tmp_path: Path
) -> None:
    flow = flow_with_outputs(demo)
    runner.run(flow)
    plan = build_plan(flow, env_for(runner, store, flow))
    outputs = [plan.output("out_a|out"), plan.output("out_b|out"), plan.output("n_output|out")]
    parts = render(plan, outputs)  # type: ignore[arg-type]
    text = to_text(parts)
    created = re.findall(r"CREATE OR REPLACE TEMP VIEW (\S+) AS", text)
    assert len(created) == len(set(created)), "etapa repetida"
    assert "Etapas compartilhadas" in text and "Só de atingimento" in text
    con = clean_duckdb(tmp_path / "datasets")
    con.execute("\n".join(p.text for p in parts if "VIEW" in p.text or "MACRO" in p.text))
    for output_id in ("out_a|out", "out_b|out"):
        output = plan.output(output_id)
        tail = plan.tail(output)
        assert (
            compare(
                con.sql(f"SELECT * FROM {tail.name}").pl(),
                runner.cache.table(flow.id, tail.node_id, tail.port),
            ).state
            == SAME
        )


def test_same_block_has_same_name_and_sql_everywhere(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    flow = flow_with_outputs(demo)
    runner.run(flow)
    plan = build_plan(flow, env_for(runner, store, flow))
    single = to_text(render(plan, [plan.output("out_a|out")]))  # type: ignore[list-item]
    unified = to_text(render(plan, [plan.output("out_a|out"), plan.output("out_b|out")]))  # type: ignore[list-item]
    block = plan.blocks["n_filter|T"]
    assert block.name in single and block.name in unified
    assert all(line.strip() in single and line.strip() in unified for line in block.sql.split("\n"))


def test_editing_a_box_does_not_rename_the_others(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    before = build_plan(demo, env_for(runner, store, demo))
    raw = demo.model_dump(mode="json", by_alias=True)
    next(n for n in raw["nodes"] if n["id"] == "n_cleanse")["label"] = "Outro nome"
    edited = Workflow.model_validate(raw)
    after = build_plan(edited, env_for(runner, store, edited))
    changed = {b for b in before.blocks if before.blocks[b].name != after.blocks[b].name}
    assert changed == {"n_cleanse|out"}


def test_reading_order_follows_each_chain(demo: Workflow) -> None:
    from prodata.engine import graph

    order = graph.reading_order(demo)
    assert order[:4] == ["n_clientes", "n_cleanse", "n_formula", "n_filter"]
    assert order.index("n_vendas") + 1 == order.index("n_sum_vendas")
    assert order.index("n_sum_vendas") + 1 == order.index("n_join")
    assert order.index("n_trainer") + 1 == order.index("n_predictor")
    position = {n: i for i, n in enumerate(order)}
    assert all(position[e.source] < position[e.target] for e in demo.edges)


def test_generating_does_not_execute(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow, tmp_path: Path
) -> None:
    plan = build_plan(demo, env_for(runner, store, demo))
    assert plan.blocks["n_join|J"].status == OK and plan.blocks["n_join|J"].columns
    assert plan.blocks["n_join|J"].rows is None
    assert not any((tmp_path / "exports").iterdir())


def test_verification_is_ready_for_translated_outputs(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    flow = flow_with_outputs(demo)
    runner.run(flow)
    env = env_for(runner, store, flow)
    plan = build_plan(flow, env)
    result = verify(plan, env)
    for block_id, check in result.blocks.items():
        assert check.state != DIFFERENT, (block_id, check.detail, check.examples)
    state = output_state(plan, plan.output("out_b|out"), result)  # type: ignore[arg-type]
    assert state["state"] == READY, state
    assert state["checked"] == state["total"] > 0
    assert output_state(plan, plan.output("n_output|out"), result)["state"] == PARTIAL  # type: ignore[arg-type]


def test_visual_never_claims_its_query_was_compared(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    runner.run(demo)
    env = env_for(runner, store, demo)
    plan = build_plan(demo, env)
    state = output_state(plan, plan.output("n_pareto|out"), verify(plan, env))  # type: ignore[arg-type]
    assert state["state"] == "ready_notes"
    assert any("não é comparada" in note for note in state["notes"])


def test_wrong_sql_is_reported_as_mismatch(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    """O teste de honestidade: um SQL errado de propósito não pode passar."""
    flow = flow_with_outputs(demo)
    runner.run(flow)
    env = env_for(runner, store, flow)
    plan = build_plan(flow, env)
    fragment = plan.blocks["n_atingimento|out"].fragment
    assert fragment is not None
    fragment.sql = fragment.sql.replace("* 100", "* 101")
    result = verify(plan, env)
    assert result.blocks["n_atingimento|out"].state == DIFFERENT
    assert output_state(plan, plan.output("out_b|out"), result)["state"] == MISMATCH  # type: ignore[arg-type]


def test_stale_results_are_not_called_checked(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    flow = flow_with_outputs(demo)
    runner.run(flow)
    raw = flow.model_dump(mode="json", by_alias=True)
    next(n for n in raw["nodes"] if n["id"] == "n_filter")["config"]["expression"] = "[mrr_mensal] >= 5000"
    edited = Workflow.model_validate(raw)
    env = env_for(runner, store, edited)
    plan = build_plan(edited, env)
    result = verify(plan, env)
    assert result.blocks["n_filter|T"].state == "unchecked"
    assert result.blocks["n_join|J"].state == "unchecked"
    assert result.blocks["n_cleanse|out"].state == SAME  # antes da mudança continua valendo
    assert output_state(plan, plan.output("out_a|out"), result)["state"] == "pending"  # type: ignore[arg-type]


def test_workflow_from_038_generates_sql(runner: WorkflowRunner, store: DatasetStore) -> None:
    raw = json.loads((DATA / "fluxo_0_3_8.prodata.json").read_text(encoding="utf-8"))
    flow = Workflow.model_validate(raw)
    plan = build_plan(flow, env_for(runner, store, flow))
    assert plan.outputs and plan.blocks["n_join|J"].status == OK


def test_temporary_output_goes_until_the_box(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    plan = build_plan(demo, env_for(runner, store, demo))
    output = temporary_output(plan, "n_filter")
    assert output is not None and output.id == "n_filter|T" and output.temporary
    assert to_text(render(plan, [output])).rstrip().endswith("SELECT * FROM ativos__t;")


def test_generated_text_has_no_secret_or_absolute_path(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow, tmp_path: Path
) -> None:
    runner.run(demo)
    plan = build_plan(demo, env_for(runner, store, demo))
    text = to_text(render(plan, plan.outputs))
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text
    assert "password" not in text.lower() and "senha" not in text.lower()


def test_text_input_warns_that_data_goes_along(runner: WorkflowRunner, store: DatasetStore) -> None:
    flow = Workflow.model_validate(
        {
            "id": "wf-texto",
            "name": "t",
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "label": "Metas",
                    "config": {"table": {"columns": ["a"], "rows": [["1"]]}},
                }
            ],
            "edges": [],
        }
    )
    plan = build_plan(flow, env_for(runner, store, flow))
    assert "dados digitados" in to_text(render(plan, plan.outputs))


def test_user_sql_that_writes_is_not_translated(runner: WorkflowRunner, store: DatasetStore) -> None:
    table = {"table": {"columns": ["a"], "rows": [["1"]]}}
    for sql in ("COPY input_1 TO 'x.csv'", "SELECT 1; COPY input_1 TO 'x.csv'"):
        flow = Workflow.model_validate(
            {
                "id": "wf-sql",
                "name": "t",
                "nodes": [
                    {"id": "t", "type": "io.text_input", "label": "T", "config": table},
                    {"id": "s", "type": "transform.sql_query", "label": "S", "config": {"sql": sql}},
                ],
                "edges": [
                    {"id": "e", "source": "t", "sourceHandle": "out", "target": "s", "targetHandle": "in"}
                ],
            }
        )
        plan = build_plan(flow, env_for(runner, store, flow))
        assert plan.blocks["s|out"].status == NO_SQL


def test_verification_cannot_write_files(tmp_path: Path) -> None:
    from prodata.engine.sql.verify import _connection

    con = _connection()
    target = tmp_path / "gravou.csv"
    with pytest.raises(duckdb.Error):
        con.execute(f"COPY (SELECT 1) TO '{target.as_posix()}'")
    assert not target.exists()
    with pytest.raises(duckdb.Error):
        con.execute("SET enable_external_access = true")


def test_broken_formula_shows_on_the_block(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    raw = demo.model_dump(mode="json", by_alias=True)
    next(n for n in raw["nodes"] if n["id"] == "n_formula")["config"]["formulas"][0]["expression"] = (
        "[nao_existe] + 1"
    )
    flow = Workflow.model_validate(raw)
    plan = build_plan(flow, env_for(runner, store, flow))
    assert plan.blocks["n_formula|out"].status == "error"
    assert "nao_existe" in plan.blocks["n_formula|out"].reason
    assert plan.blocks["n_join|J"].status == "blocked"


CSV_CASES = {
    "datas_iso": ("id,data,mes\n1,2026-05-01,2026-05\n2,2026-06-15,2026-06\n", {}),
    "datas_br": ("id;data\n1;29/10/2026\n2;31/12/2025\n", {}),
    "zeros_a_esquerda": ("cod,v\n007,1\n010,2\n", {}),
    "mistura": ("a,b\n1,x\nabc,y\n", {}),
    "t_e_f": ("a,b\ntrue,T\nfalse,F\n", {}),
    "vazios": ("a,b\n1,\n,x\n", {}),
    "sem_cabecalho": ("1,x\n2,y\n", {"has_header": False}),
    "sem_cabecalho_pula_coluna": ("1,x,z\n2,y,w\n", {"has_header": False, "skip_columns": 1}),
    "pula_linhas": ("titulo\nsub\na,b\n1,2\n", {"skip_rows": 2}),
    "pula_coluna": ("a,b,c\n1,2,3\n", {"skip_columns": 1}),
    "nulos": ("a,b\nNA,1\nx,-\n", {"null_values": "NA,-"}),
    "limite": ("a\n1\n2\n3\n", {"limit": 2}),
    "nomes_com_espaco": ("coluna um,valor (R$)\n a ,1\n", {}),
    "decimal_virgula": ("a;b\n1,5;x\n2,25;y\n", {}),
    "aspas": ('a,b\n"x,y","linha\nquebra"\n', {}),
    "inteiro_gigante": ("a\n12345678901234567890\n", {}),
    "data_e_hora": ("a\n2026-01-01 10:00:00\n", {"parse_dates": True}),
    "notacao": ("a\n1e5\n2.5\n", {}),
}


def source_flow(name: str, config: dict) -> Workflow:
    return Workflow.model_validate(
        {
            "id": f"wf-{name}",
            "name": "t",
            "nodes": [
                {
                    "id": "s",
                    "type": "io.input_data",
                    "label": "F",
                    "config": {"dataset": f"{name}.csv", **config},
                }
            ],
            "edges": [],
        }
    )


@pytest.mark.parametrize("name", CSV_CASES)
def test_csv_read_matches_engine_end_to_end(
    name: str, runner: WorkflowRunner, store: DatasetStore, tmp_path: Path
) -> None:
    body, config = CSV_CASES[name]
    (tmp_path / "datasets" / f"{name}.csv").write_text(body, encoding="utf-8")
    flow = source_flow(name, config)
    runner.run(flow)
    env = env_for(runner, store, flow)
    plan = build_plan(flow, env)
    result = verify(plan, env)
    assert result.outputs["s|out"].state == SAME, (
        result.outputs["s|out"].detail,
        plan.blocks["s|out"].sql,
        plan.blocks["s|out"].reason,
    )
    assert output_state(plan, plan.outputs[0], result)["state"] == READY


def test_cp1252_stays_exact_with_and_without_euro(
    runner: WorkflowRunner, store: DatasetStore, tmp_path: Path
) -> None:
    folder = tmp_path / "datasets"
    (folder / "sem.csv").write_bytes("nome;preco\nCafé;1,5\n".encode("cp1252"))
    (folder / "com.csv").write_bytes("nome;preco\nCafé €;1,5\n".encode("cp1252"))
    plain = source_flow("sem", {})
    assert "latin-1" in build_plan(plain, env_for(runner, store, plain)).blocks["s|out"].sql
    euro = source_flow("com", {})
    assert "cp1252" in build_plan(euro, env_for(runner, store, euro)).blocks["s|out"].sql


def test_columns_differing_only_by_case_are_flagged(
    runner: WorkflowRunner, store: DatasetStore, tmp_path: Path
) -> None:
    (tmp_path / "datasets" / "caixa.csv").write_text("Nome,nome\na,b\n", encoding="utf-8")
    flow = source_flow("caixa", {})
    plan = build_plan(flow, env_for(runner, store, flow))
    assert any("maiúsculas" in n for n in plan.blocks["s|out"].fragment.notes)


def test_generating_never_runs_a_second_command(
    runner: WorkflowRunner, store: DatasetStore, tmp_path: Path
) -> None:
    """Gerar o código não executa: uma fórmula com "; COPY" não pode gravar nada (RF-2002, RF-2032)."""
    target = tmp_path / "gravou.csv"
    expression = f"1 AS x FROM base; COPY (SELECT 1) TO '{target.as_posix()}'; SELECT 1"
    flow = Workflow.model_validate(
        {
            "id": "wf-inj",
            "name": "t",
            "nodes": [
                {
                    "id": "s",
                    "type": "io.text_input",
                    "label": "Base",
                    "config": {"table": {"columns": ["a"], "rows": [["1"]]}},
                },
                {
                    "id": "g",
                    "type": "prep.formula",
                    "label": "G",
                    "config": {"formulas": [{"column": "c", "expression": expression}]},
                },
            ],
            "edges": [{"id": "e", "source": "s", "sourceHandle": "out", "target": "g", "targetHandle": "in"}],
        }
    )
    plan = build_plan(flow, env_for(runner, store, flow))
    assert plan.blocks["g|out"].status == "error"
    assert not target.exists()
    assert expression not in to_text(render(plan, plan.outputs))


def test_engine_refuses_a_second_command_in_a_formula(tmp_path: Path) -> None:
    from prodata.engine import formula

    target = tmp_path / "gravou.csv"
    expression = f"1 AS x FROM t; COPY (SELECT 1) TO '{target.as_posix()}'; SELECT 1"
    df = pl.DataFrame({"a": [1]})
    with pytest.raises(formula.FormulaError):
        formula.evaluate_columns(df, [{"column": "c", "expression": expression}])
    with pytest.raises(formula.FormulaError):
        formula.evaluate_mask(df, expression)
    assert not formula.validate(expression, [{"name": "a", "type": "Int64"}])["valid"]
    assert not target.exists()
    # Ponto e vírgula dentro de um texto continua valendo.
    assert formula.evaluate_columns(df, [{"column": "c", "expression": "'a;b'"}])["c"].to_list() == ["a;b"]


def test_line_breaks_in_names_stay_inside_comments(runner: WorkflowRunner, store: DatasetStore) -> None:
    evil = "nome\nDROP TABLE x; --"
    flow = Workflow.model_validate(
        {
            "id": "wf-c",
            "name": evil,
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "label": evil,
                    "config": {"table": {"columns": ["a"], "rows": [["1"]]}},
                },
                {
                    "id": "o",
                    "type": "io.output_data",
                    "label": evil,
                    "config": {"filename": "saida", "format": "csv"},
                },
                {"id": "u", "type": "ml.train_test_split", "label": evil, "config": {}},
            ],
            "edges": [
                {"id": "e", "source": "t", "sourceHandle": "out", "target": "o", "targetHandle": "in"},
                {"id": "f", "source": "t", "sourceHandle": "out", "target": "u", "targetHandle": "in"},
            ],
        }
    )
    plan = build_plan(flow, env_for(runner, store, flow))
    text = to_text(render(plan, plan.outputs))
    assert not [line for line in text.split("\n") if "DROP" in line and not line.startswith("--")]


def test_header_has_date_and_dialect(runner: WorkflowRunner, store: DatasetStore, demo: Workflow) -> None:
    from datetime import date

    plan = build_plan(demo, env_for(runner, store, demo))
    text = to_text(render(plan, [plan.outputs[0]]))
    assert f"{date.today():%d/%m/%Y}" in text and "Dialeto: DuckDB" in text and "Fabric" in text


def test_stop_comment_says_the_real_reason(runner: WorkflowRunner, store: DatasetStore) -> None:
    flow = Workflow.model_validate(
        {
            "id": "wf-d",
            "name": "t",
            "nodes": [
                {
                    "id": "s",
                    "type": "io.text_input",
                    "label": "Base",
                    "disabled": True,
                    "config": {"table": {"columns": ["a"], "rows": [["1"]]}},
                },
                {"id": "f", "type": "io.browse", "label": "B", "config": {}},
                {"id": "x", "type": "io.input_data", "label": "Sem fonte", "config": {"dataset": ""}},
            ],
            "edges": [{"id": "e", "source": "s", "sourceHandle": "out", "target": "f", "targetHandle": "in"}],
        }
    )
    plan = build_plan(flow, env_for(runner, store, flow))
    assert "Caixa desligada" in to_text(render(plan, [plan.output("f|out")]))  # type: ignore[list-item]
    empty = to_text(render(plan, [plan.output("x|out")]))  # type: ignore[list-item]
    assert "Etapa a revisar" in empty and "Sem tradução" not in empty


def test_stop_is_the_first_real_cause_in_the_path(
    runner: WorkflowRunner, store: DatasetStore, demo: Workflow
) -> None:
    raw = demo.model_dump(mode="json", by_alias=True)
    next(n for n in raw["nodes"] if n["id"] == "n_cleanse")["disabled"] = True
    flow = Workflow.model_validate(raw)
    plan = build_plan(flow, env_for(runner, store, flow))
    output = plan.output("n_output|out")
    assert output is not None and plan.blocks[output.stop].node_id == "n_cleanse"
    assert "Caixa desligada" in to_text(render(plan, [output]))


def test_old_database_input_is_a_source_not_a_dead_end(runner: WorkflowRunner, store: DatasetStore) -> None:
    flow = Workflow.model_validate(
        {
            "id": "wf-db",
            "name": "t",
            "nodes": [
                {
                    "id": "d",
                    "type": "io.database_input",
                    "label": "Banco",
                    "config": {"connection": "c", "mode": "table", "table": "dbo.vendas"},
                }
            ],
            "edges": [],
        }
    )
    plan = build_plan(flow, env_for(runner, store, flow))
    assert plan.blocks["d|out"].status != NO_SQL


def test_visual_without_columns_is_a_clear_error(runner: WorkflowRunner, store: DatasetStore) -> None:
    flow = Workflow.model_validate(
        {
            "id": "wf-v",
            "name": "t",
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "label": "T",
                    "config": {"table": {"columns": ["a"], "rows": [["1"]]}},
                },
                {"id": "c", "type": "bi.chart", "label": "C", "config": {}},
            ],
            "edges": [{"id": "e", "source": "t", "sourceHandle": "out", "target": "c", "targetHandle": "in"}],
        }
    )
    plan = build_plan(flow, env_for(runner, store, flow))
    assert plan.blocks["c|out"].status == "error" and "Escolha" in plan.blocks["c|out"].reason


def test_user_query_reading_files_is_unchecked_not_mismatch(
    runner: WorkflowRunner, store: DatasetStore, tmp_path: Path
) -> None:
    (tmp_path / "datasets" / "fora.csv").write_text("a\n1\n", encoding="utf-8")
    sql = f"SELECT * FROM read_csv('{(tmp_path / 'datasets' / 'fora.csv').as_posix()}')"
    flow = Workflow.model_validate(
        {
            "id": "wf-f",
            "name": "t",
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "label": "T",
                    "config": {"table": {"columns": ["a"], "rows": [["1"]]}},
                },
                {"id": "s", "type": "transform.sql_query", "label": "S", "config": {"sql": sql}},
            ],
            "edges": [{"id": "e", "source": "t", "sourceHandle": "out", "target": "s", "targetHandle": "in"}],
        }
    )
    runner.run(flow)
    env = env_for(runner, store, flow)
    plan = build_plan(flow, env)
    result = verify(plan, env)
    assert result.blocks["s|out"].state == "unchecked"
    assert output_state(plan, plan.output("s|out"), result)["state"] == "pending"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "sql",
    [
        "COPY input_1 TO '{target}'",
        "SELECT 1; COPY input_1 TO '{target}'",
        "CREATE TABLE t AS SELECT 1",
        "DROP TABLE input_1",
    ],
)
def test_sql_box_only_runs_one_query(sql: str, tmp_path: Path) -> None:
    from prodata.nodes import REGISTRY, NodeContext

    target = tmp_path / "gravou.csv"
    spec = REGISTRY["transform.sql_query"]
    cfg = spec.config.model_validate({"sql": sql.format(target=target.as_posix())})
    with pytest.raises(ValueError, match="só uma consulta"):
        spec.run(NodeContext({"in": pl.DataFrame({"a": [1]})}, {}, None, tmp_path), cfg)
    assert not target.exists()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM input_1",
        "SELECT * FROM input_1;",
        "WITH x AS (SELECT a FROM input_1) SELECT * FROM x",
        "SELECT ';' AS texto FROM input_1",
    ],
)
def test_sql_box_still_runs_queries(sql: str, tmp_path: Path) -> None:
    from prodata.nodes import REGISTRY, NodeContext

    spec = REGISTRY["transform.sql_query"]
    out = spec.run(
        NodeContext({"in": pl.DataFrame({"a": [1]})}, {}, None, tmp_path),
        spec.config.model_validate({"sql": sql}),
    )
    assert out.tables["out"].height == 1


def test_examples_are_safe_for_json() -> None:
    a = pl.DataFrame({"v": [float("nan"), 1.0], "t": ["x", None]})
    b = pl.DataFrame({"v": [2.0, 1.0], "t": ["y", None]})
    check = compare(a, b)
    assert check.state == DIFFERENT
    json.dumps(check.examples, allow_nan=False)


def test_changed_file_invalidates_a_finished_verification(client: TestClient, settings) -> None:
    import time

    workflows = client.get("/api/workflows").json()
    demo = client.get(f"/api/workflows/{workflows[0]['id']}").json()
    client.post("/api/execute", json={"workflow": demo, "hold_exports": True})
    client.post("/api/sql/verify", json={"workflow": demo})
    for _ in range(200):
        if client.get(f"/api/sql/verify/{demo['id']}").json()["done"]:
            break
        time.sleep(0.1)
    first = client.post("/api/sql/generate", json={"workflow": demo}).json()
    assert first["verified"] is True
    file = settings.storage_dir / "datasets" / "metas_regionais_br.csv"
    file.write_bytes(file.read_bytes() + b"\n")
    second = client.post("/api/sql/generate", json={"workflow": demo}).json()
    assert second["verified"] is False


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("Clientes × vendas", "clientes_x_vendas"),
        ("Ação 1", "acao_1"),
        ("2024", "etapa_2024"),
        ("select", "select_"),
        ("", "etapa"),
    ],
)
def test_block_names_are_readable(label: str, name: str) -> None:
    assert slug(label) == name


def test_api_generate_and_verify(client: TestClient) -> None:
    workflow = client.get("/api/workflows").json()
    demo = client.get(f"/api/workflows/{workflow[0]['id']}").json() if workflow else None
    assert demo is not None
    client.post("/api/execute", json={"workflow": demo, "hold_exports": True})
    response = client.post("/api/sql/generate", json={"workflow": demo})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outputs"] and body["parts"] and body["blocks"]
    assert any(p["kind"] == "header" for p in body["parts"])
