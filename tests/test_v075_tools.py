"""Spec 033: ferramentas novas e avisos (Input Folder, Join, Data Quality, Reconcile, texto, Fuzzy Match)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from prodata.errors import InvalidInputError, ProdataError
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext
from prodata.nodes.base import NodeOutput


def run(
    tool: str, inputs: dict[str, pl.DataFrame], store: DatasetStore, tmp_path: Path, **config: Any
) -> NodeOutput:
    spec = REGISTRY[tool]
    ctx = NodeContext(inputs, {}, store, tmp_path, secret_key=lambda: b"k" * 32)
    return spec.run(ctx, spec.config.model_validate(config))


def warnings(out: NodeOutput) -> list[str]:
    return list(out.extra.get("warnings") or [])


# ------------------------------------------------------------------ Input Folder


@pytest.fixture
def month(tmp_path: Path) -> Path:
    folder = tmp_path / "fechamento"
    folder.mkdir()
    pl.DataFrame({"uf": ["SP", "RJ"], "valor": [10.0, 20.0]}).write_csv(folder / "vendas_01.csv")
    pl.DataFrame({"uf": ["MG"], "valor": [5.0]}).write_csv(folder / "vendas_02.csv")
    pl.DataFrame({"x": [1]}).write_csv(folder / "outro.csv")
    (folder / "leia.md").write_text("não é dado", encoding="utf-8")
    return folder


def test_folder_stacks_files_that_match(store: DatasetStore, tmp_path: Path, month: Path) -> None:
    out = run("io.input_folder", {}, store, tmp_path, folder=str(month), pattern="vendas_*.csv")
    table = out.tables["out"]
    assert table["uf"].to_list() == ["SP", "RJ", "MG"]
    assert table["arquivo"].to_list() == ["vendas_01.csv", "vendas_01.csv", "vendas_02.csv"]
    assert out.extra["folder_files"] == ["vendas_01.csv", "vendas_02.csv"]


def test_folder_warns_when_columns_differ(store: DatasetStore, tmp_path: Path, month: Path) -> None:
    out = run("io.input_folder", {}, store, tmp_path, folder=str(month), pattern="*.csv", file_column="")
    assert out.tables["out"].columns == ["x", "uf", "valor"] and "arquivo" not in out.tables["out"].columns
    assert "colunas diferentes" in warnings(out)[0]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"folder": ""}, "Escolha a pasta"),
        ({"folder": "relativa"}, "caminho completo"),
        ({"pattern": "../*.csv"}, "barras"),
        ({"pattern": "nada_*.csv"}, "Nenhum arquivo"),
    ],
)
def test_folder_refuses_bad_input(
    store: DatasetStore, tmp_path: Path, month: Path, config: dict[str, str], message: str
) -> None:
    with pytest.raises(ProdataError, match=message):
        run("io.input_folder", {}, store, tmp_path, **{"folder": str(month), "pattern": "*.csv", **config})


def test_folder_signature_changes_with_the_files(store: DatasetStore, tmp_path: Path, month: Path) -> None:
    spec = REGISTRY["io.input_folder"]
    cfg = spec.config.model_validate({"folder": str(month), "pattern": "vendas_*.csv"})
    ctx = NodeContext({}, {}, store, tmp_path)
    assert spec.fingerprint is not None
    before = spec.fingerprint(ctx, cfg)
    pl.DataFrame({"uf": ["BA"], "valor": [1.0]}).write_csv(month / "vendas_03.csv")
    assert spec.fingerprint(ctx, cfg) != before


def test_folder_ignores_what_is_not_a_data_file(store: DatasetStore, tmp_path: Path, month: Path) -> None:
    out = run("io.input_folder", {}, store, tmp_path, folder=str(month), pattern="*")
    assert "leia.md" not in out.extra["folder_files"]


# ------------------------------------------------------------------ Generate Rows


def test_calendar_between_two_dates(store: DatasetStore, tmp_path: Path) -> None:
    out = run("io.generate_rows", {}, store, tmp_path, start_date="2026-01-30", end_date="01/02/2026")
    table = out.tables["out"]
    assert table["data"].to_list() == [date(2026, 1, 30), date(2026, 1, 31), date(2026, 2, 1)]
    assert table["ultimo_dia_do_mes"].to_list() == [False, True, False]
    assert table["fim_de_semana"].to_list() == [False, True, True]
    assert table["nome_dia"][0] == "sexta-feira" and table["ano_mes"][2] == "2026-02"


def test_one_row_per_month_and_plain_sequence(store: DatasetStore, tmp_path: Path) -> None:
    months = run(
        "io.generate_rows",
        {},
        store,
        tmp_path,
        start_date="2026-01",
        end_date="2026-04-01",
        every="month",
        calendar=False,
    )
    assert months.tables["out"].height == 4 and months.tables["out"].columns == ["data"]
    numbers = run(
        "io.generate_rows", {}, store, tmp_path, mode="numbers", column="n", start=2, end=10, step=4
    )
    assert numbers.tables["out"]["n"].to_list() == [2, 6, 10]


def test_generate_rows_refuses_nonsense(store: DatasetStore, tmp_path: Path) -> None:
    with pytest.raises(ProdataError, match="anterior"):
        run("io.generate_rows", {}, store, tmp_path, start_date="2026-02-01", end_date="2026-01-01")
    with pytest.raises(ProdataError, match="zero"):
        run("io.generate_rows", {}, store, tmp_path, mode="numbers", step=0)
    with pytest.raises(ProdataError, match="não é uma data"):
        run("io.generate_rows", {}, store, tmp_path, start_date="ontem")


# ------------------------------------------------------------------ Join que multiplica

LEFT = pl.DataFrame({"id": [1, 2, 3], "valor": [100, 200, 300]})


def join(right: pl.DataFrame, store: DatasetStore, tmp_path: Path, **config: Any) -> NodeOutput:
    keys = [{"left": "id", "right": "id"}]
    return run("transform.join", {"L": LEFT, "R": right}, store, tmp_path, keys=keys, **config)


def test_join_warns_when_the_lookup_repeats(store: DatasetStore, tmp_path: Path) -> None:
    out = join(pl.DataFrame({"id": [1, 1, 2], "nome": ["a", "b", "c"]}), store, tmp_path)
    assert out.tables["J"].height == 3
    assert "2 linhas de [L] viraram 3 no J" in warnings(out)[0]
    assert out.extra["join_multiplied"]["repeated_keys"] == 1


def test_join_is_quiet_when_keys_are_unique_on_the_right(store: DatasetStore, tmp_path: Path) -> None:
    many_left = pl.DataFrame({"id": [1, 1, 2]})
    out = run(
        "transform.join",
        {"L": many_left, "R": pl.DataFrame({"id": [1, 2], "nome": ["a", "b"]})},
        store,
        tmp_path,
        keys=[{"left": "id", "right": "id"}],
    )
    assert not warnings(out) and "join_multiplied" not in out.extra


def test_join_says_when_both_sides_repeat(store: DatasetStore, tmp_path: Path) -> None:
    out = run(
        "transform.join",
        {"L": pl.DataFrame({"id": [1, 1]}), "R": pl.DataFrame({"id": [1, 1]})},
        store,
        tmp_path,
        keys=[{"left": "id", "right": "id"}],
    )
    assert out.tables["J"].height == 4 and "dos dois lados" in warnings(out)[0]


def test_expected_repetition_is_not_a_warning(store: DatasetStore, tmp_path: Path) -> None:
    out = join(pl.DataFrame({"id": [1, 1]}), store, tmp_path, allow_multiply=True)
    assert not warnings(out) and out.extra["join_multiplied"]["joined_rows"] == 2


def test_repeated_key_that_matches_nothing_is_quiet(store: DatasetStore, tmp_path: Path) -> None:
    assert not warnings(join(pl.DataFrame({"id": [9, 9, 1]}), store, tmp_path))


# ------------------------------------------------------------------ Data Quality que interrompe

PEOPLE = pl.DataFrame({"nome": ["a", None, "c", "d"]})
RULE = [{"kind": "not_empty", "column": "nome"}]


def test_quality_does_not_stop_by_default(store: DatasetStore, tmp_path: Path) -> None:
    out = run("prep.data_quality", {"in": PEOPLE}, store, tmp_path, rules=RULE)
    assert out.tables["F"].height == 1


def test_quality_stops_on_any_failure(store: DatasetStore, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="1 de 4 linhas falharam, 25,0%"):
        run("prep.data_quality", {"in": PEOPLE}, store, tmp_path, rules=RULE, stop="any")


def test_quality_stops_only_above_the_accepted_share(store: DatasetStore, tmp_path: Path) -> None:
    out = run("prep.data_quality", {"in": PEOPLE}, store, tmp_path, rules=RULE, stop="pct", stop_pct=25)
    assert out.tables["P"].height == 3
    with pytest.raises(ValueError, match="aceito: 10%"):
        run("prep.data_quality", {"in": PEOPLE}, store, tmp_path, rules=RULE, stop="pct", stop_pct=10)


# ------------------------------------------------------------------ Reconcile

BEFORE = pl.DataFrame({"id": [1, 2, 3], "valor": [10.0, 20.0, 30.0]})
AFTER = pl.DataFrame({"id": [1, 2], "total": [10.0, 20.0]})
CONTROLS = [{"measure": "count"}, {"measure": "sum", "column_a": "valor", "column_b": "total"}]


def test_reconcile_stops_and_says_what_did_not_close(store: DatasetStore, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError) as exc:
        run("control.reconcile", {"A": BEFORE, "B": AFTER}, store, tmp_path, controls=CONTROLS)
    assert "Linhas: A 3, B 2 (diferença -1)" in exc.value.message
    assert "Soma de valor × total: A 60, B 30" in exc.value.message


def test_reconcile_can_just_warn(store: DatasetStore, tmp_path: Path) -> None:
    out = run(
        "control.reconcile", {"A": BEFORE, "B": AFTER}, store, tmp_path, controls=CONTROLS, on_fail="warn"
    )
    assert out.tables["out"].equals(AFTER)
    assert out.tables["check"]["situacao"].to_list() == ["não fecha", "não fecha"]
    assert len(warnings(out)) == 2


def test_reconcile_accepts_a_tolerance(store: DatasetStore, tmp_path: Path) -> None:
    b = pl.DataFrame({"id": [1, 2, 3], "valor": [10.0, 20.0, 30.004]})
    controls = [{"measure": "sum", "column_a": "valor"}, {"measure": "n_unique", "column_a": "id"}]
    out = run("control.reconcile", {"A": BEFORE, "B": b}, store, tmp_path, controls=controls)
    assert out.tables["check"]["situacao"].to_list() == ["fecha", "fecha"]
    assert "warnings" not in out.extra


# ------------------------------------------------------------------ Regex, Multi-Field Formula e Mask

TEXT = pl.DataFrame(
    {
        "ref": ["NF 10/2026", "nf 03/2025", None, "sem data"],
        "a": [" x ", "y", None, " z"],
        "b": ["m ", " n", "o", None],
    }
)


def test_regex_extracts_groups_to_columns(store: DatasetStore, tmp_path: Path) -> None:
    out = run(
        "prep.regex", {"in": TEXT}, store, tmp_path, column="ref", pattern=r"(\d{2})/(\d{4})", names=["mes"]
    )
    assert out.tables["out"]["mes"].to_list() == ["10", "03", None, None]
    assert out.tables["out"]["grupo_2"].to_list() == ["2026", "2025", None, None]


def test_regex_replaces_and_marks(store: DatasetStore, tmp_path: Path) -> None:
    replaced = run(
        "prep.regex",
        {"in": TEXT},
        store,
        tmp_path,
        column="ref",
        pattern=r"nf\s+",
        mode="replace",
        ignore_case=True,
    )
    assert replaced.tables["out"]["ref"].to_list() == ["10/2026", "03/2025", None, "sem data"]
    marked = run("prep.regex", {"in": TEXT}, store, tmp_path, column="ref", pattern=r"\d{4}$", mode="match")
    assert marked.tables["out"]["casou"].to_list() == [True, True, False, False]


def test_regex_without_groups_and_with_bad_pattern(store: DatasetStore, tmp_path: Path) -> None:
    out = run("prep.regex", {"in": TEXT}, store, tmp_path, column="ref", pattern=r"\d{4}")
    assert out.tables["out"]["grupo_1"].to_list() == ["2026", "2025", None, None]
    with pytest.raises(InvalidInputError, match="Padrão inválido"):
        run("prep.regex", {"in": TEXT}, store, tmp_path, column="ref", pattern="(")


def test_multi_field_replaces_or_creates(store: DatasetStore, tmp_path: Path) -> None:
    same = run(
        "prep.multi_field", {"in": TEXT}, store, tmp_path, columns=["a", "b"], expression="Trim([_Atual_])"
    )
    assert (
        same.tables["out"]["a"].to_list() == ["x", "y", None, "z"]
        and same.tables["out"].columns == TEXT.columns
    )
    new = run(
        "prep.multi_field",
        {"in": TEXT},
        store,
        tmp_path,
        columns=["a", "b"],
        expression="Uppercase(Trim([_atual_]))",
        target="new",
        suffix="_m",
    )
    assert new.tables["out"]["b_m"].to_list() == ["M", "N", "O", None] and new.tables["out"]["b"][0] == "m "


def test_multi_field_needs_the_placeholder(store: DatasetStore, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match=r"\[_Atual_\]"):
        run("prep.multi_field", {"in": TEXT}, store, tmp_path, columns=["a"], expression="Trim([a])")


DOCS = pl.DataFrame(
    {
        "cpf": ["123.456.789-09", "12345678909", "123", None],
        "cnpj": ["12.345.678/0001-95", "12345678000195", "x", None],
        "email": ["ana@empresa.com.br", "sem-arroba", "b@x.io", None],
    }
)


def test_mask_cpf_cnpj_and_email(store: DatasetStore, tmp_path: Path) -> None:
    cpf = run("prep.mask", {"in": DOCS}, store, tmp_path, columns=["cpf"], method="cpf").tables["out"]
    assert cpf["cpf"].to_list() == ["***.456.789-**", "***.456.789-**", "***", None]
    assert cpf["cnpj"].to_list() == DOCS["cnpj"].to_list()
    cnpj = run("prep.mask", {"in": DOCS}, store, tmp_path, columns=["cnpj"], method="cnpj").tables["out"]
    assert cnpj["cnpj"].to_list() == ["**.345.678/****-**", "**.345.678/****-**", "***", None]
    email = run("prep.mask", {"in": DOCS}, store, tmp_path, columns=["email"], method="email").tables["out"]
    assert email["email"].to_list() == ["a***@empresa.com.br", "***", "b***@x.io", None]


def test_mask_keeps_part_or_swaps_for_a_stable_code(store: DatasetStore, tmp_path: Path) -> None:
    last = run("prep.mask", {"in": DOCS}, store, tmp_path, columns=["cpf"], method="keep_last", keep=2)
    assert last.tables["out"]["cpf"][1] == "*********09"
    code = run("prep.mask", {"in": DOCS}, store, tmp_path, columns=["cpf", "cnpj"], method="code").tables[
        "out"
    ]
    again = run("prep.mask", {"in": DOCS}, store, tmp_path, columns=["cpf"], method="code").tables["out"]
    assert code["cpf"].to_list() == again["cpf"].to_list() and code["cpf"][3] is None
    assert len(code["cpf"][0]) == 16 and "123" not in code["cpf"][0] and code["cpf"][0] != code["cpf"][1]


def test_stable_code_needs_the_vault(store: DatasetStore, tmp_path: Path) -> None:
    spec = REGISTRY["prep.mask"]
    ctx = NodeContext({"in": DOCS}, {}, store, tmp_path)
    with pytest.raises(InvalidInputError, match="cofre"):
        spec.run(ctx, spec.config.model_validate({"columns": ["cpf"], "method": "code"}))


# ------------------------------------------------------------------ Fuzzy Match

CRM = pl.DataFrame(
    {
        "razao": ["Padaria Pão Quente LTDA", "Mercado Bom Preço S.A.", "Oficina do Zé ME", None],
        "uf": ["SP", "RJ", "SP", "SP"],
    }
)
ERP = pl.DataFrame(
    {
        "nome": ["PADARIA PAO QUENTE", "Mercado Bom Preco", "Farmácia Central", "Padaria Pao Quente Ltda."],
        "uf": ["SP", "RJ", "SP", "MG"],
        "codigo": [1, 2, 3, 4],
    }
)


def test_fuzzy_matches_despite_accents_case_and_suffix(store: DatasetStore, tmp_path: Path) -> None:
    out = run("transform.fuzzy_match", {"L": CRM, "R": ERP}, store, tmp_path, left="razao", right="nome")
    joined = out.tables["J"]
    pairs = dict(zip(joined["razao"].to_list(), joined["codigo"].to_list(), strict=True))
    assert pairs["Mercado Bom Preço S.A."] == 2 and joined["nota"].min() == 100
    # A padaria casa com as duas linhas de [R] que viram o mesmo texto depois de limpar.
    assert sorted(joined.filter(pl.col("razao").str.starts_with("Padaria"))["codigo"].to_list()) == [1, 4]
    assert out.tables["L"]["razao"].to_list() == ["Oficina do Zé ME", None]
    assert out.tables["R"]["nome"].to_list() == ["Farmácia Central"]
    assert "r_uf" in joined.columns


def test_fuzzy_block_limits_the_comparison(store: DatasetStore, tmp_path: Path) -> None:
    out = run(
        "transform.fuzzy_match",
        {"L": CRM, "R": ERP},
        store,
        tmp_path,
        left="razao",
        right="nome",
        block_left="uf",
        block_right="uf",
    )
    assert sorted(out.tables["J"]["codigo"].to_list()) == [1, 2]
    assert out.extra["fuzzy_pairs"] < 3 * 4


def test_fuzzy_tolerates_typos_and_word_order(store: DatasetStore, tmp_path: Path) -> None:
    left = pl.DataFrame({"n": ["Transportadora Rapido Sul", "Silva Joao"]})
    right = pl.DataFrame({"m": ["Transportadora Rapdio Sul", "Joao Silva"]})
    letters = run("transform.fuzzy_match", {"L": left, "R": right}, store, tmp_path, left="n", right="m")
    assert letters.tables["J"]["n"].to_list() == ["Transportadora Rapido Sul"]
    assert 88 <= letters.tables["J"]["nota"][0] < 100
    words = run(
        "transform.fuzzy_match", {"L": left, "R": right}, store, tmp_path, left="n", right="m", method="words"
    )
    assert "Silva Joao" in words.tables["J"]["n"].to_list()


def test_fuzzy_asks_for_a_block_when_there_are_too_many_pairs(
    store: DatasetStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prodata.nodes import fuzzy

    monkeypatch.setattr(fuzzy, "MAX_PAIRS", 5)
    with pytest.raises(InvalidInputError, match="coluna de bloco"):
        run("transform.fuzzy_match", {"L": CRM, "R": ERP}, store, tmp_path, left="razao", right="nome")
