"""Fluxo de demonstração usado na primeira execução e pelos testes."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from prodata.dashboard.layouts import LayoutItem, Rect, VisualHint, arrange
from prodata.domain.dashboard import DashPage

DEMO_WORKFLOW_ID = "demo_pipeline_360"
# Caixas criadas na v0.3 (spec 014): sem elas, a demonstração salva é de uma versão anterior.
DEMO_V3_NODES = ("n_pareto", "n_venn")
LOGO = Path(__file__).resolve().parents[1] / "web" / "brand" / "protege-escudo.svg"

# Colunas do canvas para cartões de 188 px com 60 px de folga (spec 004, RF-403).
COL = [40 + 248 * i for i in range(9)]


def _node(node_id: str, type_: str, label: str, col: int, y: int, **config: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "label": label, "x": COL[col], "y": y, "config": config}


def _edge(
    eid: str, source: str, source_handle: str, target: str, target_handle: str = "in"
) -> dict[str, str]:
    return {
        "id": eid,
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


def _container(cid: str, title: str, color: str, x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {"id": cid, "title": title, "color": color, "x": x, "y": y, "width": width, "height": height}


def demo_workflow() -> dict[str, Any]:
    return {
        "id": DEMO_WORKFLOW_ID,
        "name": "Pipeline 360° de clientes",
        "description": "Limpeza, filtro, junção L/J/R, metas regionais (CSV ';' em CP1252), BI e modelo de inadimplência.",
        "containers": [
            _container("c_prep", "1 · Ingestão e preparação", "#3b82f6", 20, 20, 972, 260),
            _container("c_bi", "2 · Junção, metas e indicadores", "#8b5cf6", 1010, 20, 1222, 420),
            _container("c_ml", "3 · Modelo de inadimplência", "#06b6d4", 1010, 460, 1222, 140),
            _container("c_vendas", "4 · Vendas no dashboard", "#f59e0b", 20, 300, 972, 300),
        ],
        "nodes": [
            _node("n_clientes", "io.input_data", "Clientes", 0, 70, dataset="clientes_enterprise.csv"),
            _node("n_vendas", "io.input_data", "Transações", 0, 190, dataset="transacoes_vendas.csv"),
            _node(
                "n_cleanse",
                "prep.cleanse",
                "Limpeza",
                1,
                70,
                columns=["setor"],
                replace_null_string=True,
                string_default="Não informado",
            ),
            _node(
                "n_formula",
                "prep.formula",
                "ARR e tier",
                2,
                70,
                formulas=[
                    {
                        "column": "receita_anual",
                        "type": "Float64",
                        "expression": "Round([mrr_mensal] * 12, 2)",
                    },
                    {
                        "column": "tier",
                        "type": "String",
                        "expression": "IF [mrr_mensal] >= 6000 THEN 'Diamond' ELSEIF [mrr_mensal] >= 3000 "
                        "THEN 'Gold' ELSE 'Silver' ENDIF",
                    },
                ],
            ),
            _node(
                "n_filter",
                "prep.filter",
                "Ativos",
                3,
                70,
                mode="expression",
                expression="[status] != 'INATIVO' AND [mrr_mensal] >= 1000",
            ),
            _node(
                "n_sum_vendas",
                "transform.summarize",
                "Vendas por cliente",
                2,
                190,
                group_by=["id_cliente"],
                aggregations=[
                    {"column": "valor_bruto", "agg": "sum", "alias": "total_compras"},
                    {"column": "quantidade_licencas", "agg": "sum", "alias": "total_licencas"},
                    {"column": "id_transacao", "agg": "count", "alias": "qtd_pedidos"},
                ],
            ),
            _node(
                "n_join",
                "transform.join",
                "Clientes × vendas",
                4,
                125,
                right_prefix="v_",
                keys=[{"left": "id_cliente", "right": "id_cliente"}],
            ),
            _node(
                "n_sum_uf",
                "transform.summarize",
                "MRR por UF",
                5,
                65,
                group_by=["uf"],
                aggregations=[
                    {"column": "mrr_mensal", "agg": "sum", "alias": "total_mrr"},
                    {"column": "id_cliente", "agg": "count", "alias": "clientes"},
                ],
            ),
            _node("n_metas", "io.input_data", "Metas regionais", 5, 165, dataset="metas_regionais_br.csv"),
            _node(
                "n_join_metas", "transform.join", "UF × metas", 6, 100, keys=[{"left": "uf", "right": "uf"}]
            ),
            _node(
                "n_atingimento",
                "prep.formula",
                "Atingimento",
                7,
                108,
                formulas=[
                    {
                        "column": "atingimento_pct",
                        "type": "Float64",
                        "expression": "Round([total_mrr] / [meta_mrr] * 100, 1)",
                    },
                ],
            ),
            _node(
                "n_chart_uf",
                "bi.chart",
                "Gráfico por UF",
                8,
                108,
                title="Atingimento da meta de MRR por UF (%)",
                chart_type="bar",
                x_column="uf",
                y_column="atingimento_pct",
                agg="max",
                sort="value_desc",
            ),
            _node(
                "n_kpi",
                "bi.kpi_card",
                "ARR ativo",
                5,
                270,
                title="ARR dos clientes ativos",
                column="receita_anual",
                metric="sum",
                prefix="R$ ",
            ),
            _node(
                "n_chart_seg",
                "bi.chart",
                "MRR por segmento",
                5,
                360,
                title="MRR por segmento",
                chart_type="donut",
                x_column="segmento",
                y_column="mrr_mensal",
                agg="sum",
            ),
            _node(
                "n_pareto",
                "bi.chart",
                "Pareto por UF",
                6,
                300,
                title="Pareto do MRR por UF",
                chart_type="pareto",
                x_column="uf",
                y_column="mrr_mensal",
                agg="sum",
            ),
            _node(
                "n_kpi_mes",
                "bi.kpi_card",
                "Faturamento do mês",
                1,
                350,
                title="Faturamento do mês",
                column="valor_bruto",
                metric="sum",
                prefix="R$ ",
                compare="previous",
                date_column="competencia",
                period="month",
                sparkline=True,
            ),
            _node(
                "n_stacked",
                "bi.chart",
                "Vendas por mês",
                2,
                350,
                title="Faturamento mensal por produto",
                chart_type="stacked",
                x_column="competencia",
                y_column="valor_bruto",
                series_column="produto",
                agg="sum",
                sort="label",
            ),
            _node(
                "n_venn",
                "bi.venn",
                "Produtos por cliente",
                1,
                480,
                title="Clientes por produto contratado",
                key_column="id_cliente",
                group_column="produto",
                groups=["Cloud", "AutoML", "BI Pro"],
            ),
            _node(
                "n_trainer",
                "ml.automl_trainer",
                "Treino",
                5,
                510,
                target_column="inadimplente",
                feature_columns=[
                    "mrr_mensal",
                    "meses_contrato",
                    "nps",
                    "total_compras",
                    "total_licencas",
                    "segmento",
                    "uf",
                ],
            ),
            _node(
                "n_predictor",
                "ml.predictor",
                "Score de risco",
                6,
                510,
                prediction_column="risco_inadimplencia",
                probability_column="confianca_pct",
            ),
            _node(
                "n_output",
                "io.output_data",
                "Exportar",
                7,
                510,
                filename="clientes_pontuados",
                format="parquet",
            ),
        ],
        "edges": [
            _edge("e1", "n_clientes", "out", "n_cleanse"),
            _edge("e2", "n_cleanse", "out", "n_formula"),
            _edge("e3", "n_formula", "out", "n_filter"),
            _edge("e4", "n_vendas", "out", "n_sum_vendas"),
            _edge("e5", "n_filter", "T", "n_join", "L"),
            _edge("e6", "n_sum_vendas", "out", "n_join", "R"),
            _edge("e7", "n_join", "J", "n_sum_uf"),
            _edge("e8", "n_sum_uf", "out", "n_join_metas", "L"),
            _edge("e9", "n_metas", "out", "n_join_metas", "R"),
            _edge("e10", "n_join_metas", "J", "n_atingimento"),
            _edge("e11", "n_atingimento", "out", "n_chart_uf"),
            _edge("e12", "n_join", "J", "n_kpi"),
            _edge("e13", "n_join", "J", "n_chart_seg"),
            _edge("e14", "n_join", "J", "n_trainer"),
            _edge("e15", "n_trainer", "M", "n_predictor", "M"),
            _edge("e16", "n_join", "J", "n_predictor", "D"),
            _edge("e17", "n_predictor", "out", "n_output"),
            _edge("e18", "n_join", "J", "n_pareto"),
            _edge("e19", "n_vendas", "out", "n_kpi_mes"),
            _edge("e20", "n_vendas", "out", "n_stacked"),
            _edge("e21", "n_vendas", "out", "n_venn"),
        ],
        "dashboard": demo_dashboard(),
    }


def demo_dashboard() -> dict[str, Any]:
    """Dashboard já montado: título, logo, big numbers no topo e gráficos em três colunas."""
    visuals = [
        ("n_kpi", VisualHint(kind="kpi")),
        ("n_kpi_mes", VisualHint(kind="kpi")),
        ("n_stacked", VisualHint(chart_type="stacked")),
        ("n_pareto", VisualHint(chart_type="pareto")),
        ("n_chart_uf", VisualHint(chart_type="bar")),
        ("n_chart_seg", VisualHint(chart_type="donut")),
        ("n_venn", VisualHint(chart_type="venn")),
    ]
    title = Rect(x=40, y=32, w=1200, h=56)
    logo = Rect(x=1488, y=24, w=72, h=88)
    page = DashPage(size="a4-landscape")
    items = [LayoutItem(id=n, hint=hint, rect=Rect(y=i)) for i, (n, hint) in enumerate(visuals)]
    result = arrange(items, page, "kpis-top-3", [title, logo])
    logo_uri = "data:image/svg+xml;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    return {
        "page": result.page.model_dump(),
        "items": [
            {
                "id": "d_title",
                "kind": "text",
                **title.model_dump(),
                "content": "Pipeline 360° de clientes",
                "format": {"size": 30, "bold": True, "vertical": "middle"},
            },
            {"id": "d_logo", "kind": "image", **logo.model_dump(), "content": logo_uri, "format": {}},
            *(
                {
                    "id": f"d_{n}",
                    "kind": "visual",
                    "node_id": n,
                    **result.positions[n].model_dump(),
                    "format": {},
                }
                for n, _ in visuals
            ),
        ],
        "hidden": [],
    }
