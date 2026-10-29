"""Ferramentas de Machine Learning (scikit-learn)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import polars as pl
from pydantic import Field

from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

if TYPE_CHECKING:
    from sklearn.base import BaseEstimator

# O scikit-learn é importado só quando um nó de ML executa: ele sozinho custa ~0,7 s na
# inicialização do servidor, e a maioria dos fluxos não usa ML.
PARALLEL_MIN_ROWS = 20_000

# ------------------------------------------------------------------ Train/Test Split


class SplitConfig(ToolConfig):
    train_ratio: float = Field(0.8, gt=0, lt=1, title="Proporção de treino", json_schema_extra=ui(step=0.05))
    seed: int = Field(42, title="Semente")


@tool(
    type="ml.train_test_split",
    name="Train/Test Split",
    category="ml",
    icon="split",
    description="Divide os dados aleatoriamente em treino [Tr] e teste [Te], de forma reprodutível.",
    config=SplitConfig,
    outputs=[Port("Tr", "Tr", "Treino"), Port("Te", "Te", "Teste")],
    annotate=lambda c: f"{c.train_ratio:.0%} / {1 - c.train_ratio:.0%}",
)
def split(ctx: NodeContext, cfg: SplitConfig) -> NodeOutput:
    df = ctx.input().sample(fraction=1.0, shuffle=True, seed=cfg.seed)
    cut = round(df.height * cfg.train_ratio)
    return NodeOutput(tables={"Tr": df.head(cut), "Te": df.slice(cut)})


# ------------------------------------------------------------------ AutoML Trainer

Encoders = dict[str, dict[str, int]]


def encode_features(
    df: pl.DataFrame, features: list[str], encoders: Encoders | None = None
) -> tuple[np.ndarray, Encoders]:
    """Codificação ordinal para texto; numéricos e booleanos passam como float."""
    fitted: Encoders = {} if encoders is None else encoders
    arrays: list[np.ndarray] = []
    for col in features:
        if col not in df.columns:
            raise ValueError(f"Coluna de entrada do modelo ausente: {col}")
        s = df[col]
        if s.dtype.is_numeric() or s.dtype == pl.Boolean:
            arrays.append(np.nan_to_num(s.cast(pl.Float64).fill_null(0.0).to_numpy(), nan=0.0))
            continue
        values = s.cast(pl.String).fill_null("<nulo>").to_list()
        if col not in fitted:
            fitted[col] = {v: i for i, v in enumerate(sorted(set(values)))}
        mapping = fitted[col]
        arrays.append(np.array([mapping.get(v, -1) for v in values], dtype=float))
    return np.column_stack(arrays), fitted


def _build_model(task: str, algorithm: str, rows: int = 0) -> BaseEstimator:
    from sklearn.ensemble import (
        GradientBoostingClassifier,
        GradientBoostingRegressor,
        RandomForestClassifier,
        RandomForestRegressor,
    )
    from sklearn.linear_model import LinearRegression, LogisticRegression

    # Paralelismo só compensa com volume: em bases pequenas o custo de coordenar threads
    # supera o ganho (medido: 270 ms com n_jobs=-1 contra 203 ms sem, em 368 linhas).
    jobs = -1 if rows > PARALLEL_MIN_ROWS else None

    if task == "classification":
        return {
            "gradient_boosting": lambda: GradientBoostingClassifier(random_state=42),
            "linear": lambda: LogisticRegression(max_iter=1000),
        }.get(
            algorithm,
            lambda: RandomForestClassifier(n_estimators=150, max_depth=10, random_state=42, n_jobs=jobs),
        )()
    return {
        "gradient_boosting": lambda: GradientBoostingRegressor(random_state=42),
        "linear": LinearRegression,
    }.get(
        algorithm, lambda: RandomForestRegressor(n_estimators=150, max_depth=10, random_state=42, n_jobs=jobs)
    )()


class TrainerConfig(ToolConfig):
    task_type: Literal["classification", "regression"] = Field(
        "classification",
        title="Tarefa",
        json_schema_extra=ui(labels={"classification": "Classificação", "regression": "Regressão"}),
    )
    algorithm: Literal["random_forest", "gradient_boosting", "linear"] = Field(
        "random_forest",
        title="Algoritmo",
        json_schema_extra=ui(
            labels={
                "random_forest": "Random Forest",
                "gradient_boosting": "Gradient Boosting",
                "linear": "Linear / Logística",
            }
        ),
    )
    target_column: str = Field("", title="Coluna alvo", json_schema_extra=ui(widget="column"))
    feature_columns: list[str] = Field(
        default_factory=list,
        title="Variáveis de entrada",
        description="Vazio = todas as colunas exceto o alvo.",
        json_schema_extra=ui(widget="columns"),
    )
    holdout_ratio: float = Field(
        0.25,
        ge=0.1,
        le=0.5,
        title="Validação (holdout)",
        description="Fração reservada para medir as métricas.",
        json_schema_extra=ui(group="Avançado", step=0.05),
    )


@tool(
    type="ml.automl_trainer",
    name="Model Trainer",
    category="ml",
    icon="brain",
    description="Treina classificação ou regressão. Emite o modelo em [M] e a importância das variáveis em [I].",
    config=TrainerConfig,
    inputs=[Port("in", "D", "Dados de treino")],
    outputs=[Port("M", "M", "Modelo", kind="model"), Port("I", "I", "Importância das variáveis")],
    annotate=lambda c: f"{c.algorithm} → {c.target_column}",
)
def trainer(ctx: NodeContext, cfg: TrainerConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.target_column not in df.columns:
        raise ValueError("Escolha a coluna alvo.")
    features = [c for c in (cfg.feature_columns or df.columns) if c != cfg.target_column]
    if not features:
        raise ValueError("Nenhuma variável de entrada disponível.")
    df = df.filter(pl.col(cfg.target_column).is_not_null())
    if df.height < 10:
        raise ValueError("São necessárias ao menos 10 linhas com o alvo preenchido.")

    X, encoders = encode_features(df, features)
    classes: list[str] = []
    if cfg.task_type == "classification":
        labels = df[cfg.target_column].cast(pl.String).to_list()
        classes = sorted(set(labels))
        if len(classes) < 2:
            raise ValueError("A coluna alvo precisa de ao menos duas classes.")
        y = np.array([classes.index(v) for v in labels])
        _, counts = np.unique(y, return_counts=True)
        stratify = y if counts.min() >= 2 else None
    else:
        y = df[cfg.target_column].cast(pl.Float64, strict=False).fill_null(0.0).to_numpy()
        stratify = None

    from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split

    X_tr, X_va, y_tr, y_va = train_test_split(
        X, y, test_size=cfg.holdout_ratio, random_state=42, stratify=stratify
    )
    model: Any = _build_model(cfg.task_type, cfg.algorithm, rows=len(y))
    model.fit(X_tr, y_tr)
    pred = model.predict(X_va)
    if cfg.task_type == "classification":
        metrics: dict[str, Any] = {
            "accuracy_pct": round(float(accuracy_score(y_va, pred)) * 100, 2),
            "f1_pct": round(float(f1_score(y_va, pred, average="weighted", zero_division=0)) * 100, 2),
        }
    else:
        metrics = {
            "r2": round(float(r2_score(y_va, pred)), 4),
            "mae": round(float(mean_absolute_error(y_va, pred)), 4),
        }
    metrics |= {
        "task": cfg.task_type,
        "algorithm": cfg.algorithm,
        "train_rows": len(y_tr),
        "validation_rows": len(y_va),
    }

    model.fit(X, y)  # modelo final usa todos os dados
    raw_imp = getattr(model, "feature_importances_", None)
    if raw_imp is None:
        coef = np.abs(np.atleast_2d(model.coef_))
        raw_imp = coef.mean(axis=0)
    total = float(np.sum(raw_imp)) or 1.0
    importance = pl.DataFrame(
        {"variavel": features, "importancia_pct": [round(float(v) / total * 100, 2) for v in raw_imp]}
    ).sort("importancia_pct", descending=True)

    bundle = {
        "model": model,
        "task_type": cfg.task_type,
        "target_column": cfg.target_column,
        "feature_columns": features,
        "encoders": encoders,
        "classes": classes,
        "metrics": metrics,
    }
    return NodeOutput(tables={"I": importance}, models={"M": bundle}, extra={"ml_metrics": metrics})


# ------------------------------------------------------------------ Predictor


class PredictorConfig(ToolConfig):
    prediction_column: str = Field("predicao", title="Coluna da predição")
    probability_column: str = Field("probabilidade_pct", title="Coluna da probabilidade (classificação)")


@tool(
    type="ml.predictor",
    name="Predictor",
    category="ml",
    icon="wand",
    description="Aplica um modelo treinado [M] aos dados [D], adicionando predição e probabilidade.",
    config=PredictorConfig,
    inputs=[Port("M", "M", "Modelo", kind="model"), Port("D", "D", "Dados")],
    annotate=lambda c: f"→ {c.prediction_column}",
)
def predictor(ctx: NodeContext, cfg: PredictorConfig) -> NodeOutput:
    bundle, df = ctx.model("M"), ctx.input("D")
    X, _ = encode_features(df, bundle["feature_columns"], bundle["encoders"])
    model = bundle["model"]
    raw = model.predict(X)
    if bundle["task_type"] == "classification":
        classes: list[str] = bundle["classes"]
        cols = [pl.Series(cfg.prediction_column, [classes[int(i)] for i in raw])]
        if hasattr(model, "predict_proba"):
            proba = np.max(model.predict_proba(X), axis=1) * 100
            cols.append(pl.Series(cfg.probability_column, np.round(proba, 1)))
    else:
        cols = [pl.Series(cfg.prediction_column, np.round(raw.astype(float), 4))]
    return NodeOutput(tables={"out": df.with_columns(cols)}, extra={"ml_metrics": bundle["metrics"]})
