"""Gera os datasets de demonstração (determinísticos, semente fixa)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

UFS = ["SP", "RJ", "MG", "PR", "SC", "RS", "BA", "DF", "PE", "GO"]
SEGMENTOS = ["Enterprise", "Mid-Market", "SMB", "Corporate", "Startup"]


def _clientes(rng: np.random.Generator) -> pl.DataFrame:
    n = 500
    setores = ["Varejo", "Fintech", "Saúde", "Indústria", "Agronegócio", "Logística", "Educação"]
    status = rng.choice(["ATIVO", "ATIVO", "ATIVO", "ATIVO", "RISCO", "INATIVO"], size=n).tolist()
    setor: list[str | None] = rng.choice(setores, size=n).tolist()
    for i in range(0, n, 29):  # nulos propositais para a barra de qualidade e o Cleansing
        setor[i] = None
    prefixos = ["Grupo", "Rede", "Tech", "Alfa", "Nova", "Brasil", "Prime", "Vértice", "Horizonte", "Atlas"]
    sufixos = ["Soluções", "Comércio", "Logística", "Sistemas", "Capital", "Indústria", "Digital", "Labs"]
    return pl.DataFrame(
        {
            "id_cliente": [f"CLI-{1000 + i}" for i in range(n)],
            "nome_empresa": [f"{rng.choice(prefixos)} {rng.choice(sufixos)} #{100 + i}" for i in range(n)],
            "uf": rng.choice(
                UFS, size=n, p=[0.34, 0.14, 0.12, 0.09, 0.08, 0.07, 0.05, 0.04, 0.04, 0.03]
            ).tolist(),
            "segmento": rng.choice(SEGMENTOS, size=n, p=[0.20, 0.30, 0.25, 0.15, 0.10]).tolist(),
            "setor": setor,
            "status": status,
            "mrr_mensal": np.round(rng.lognormal(mean=8.2, sigma=0.75, size=n), 2).tolist(),
            "meses_contrato": rng.integers(1, 72, size=n).tolist(),
            "nps": rng.integers(1, 11, size=n).tolist(),
            "inadimplente": [bool(rng.random() < (0.35 if s == "RISCO" else 0.06)) for s in status],
        }
    )


def _vendas(rng: np.random.Generator) -> pl.DataFrame:
    n = 1800
    # ~9% das transações referenciam clientes inexistentes, para exercitar a saída [R] do Join.
    ids = [
        f"CLI-{rng.integers(1000, 1460)}" if rng.random() < 0.91 else f"CLI-{rng.integers(9000, 9060)}"
        for _ in range(n)
    ]
    produtos = ["Cloud", "Add-on Analytics", "AutoML", "Conectores", "BI Pro"]
    return pl.DataFrame(
        {
            "id_transacao": [f"TX-{50000 + i}" for i in range(n)],
            "id_cliente": ids,
            "produto": rng.choice(produtos, size=n, p=[0.32, 0.24, 0.18, 0.14, 0.12]).tolist(),
            "canal_venda": rng.choice(
                ["Venda direta", "Parceiro", "Self-service", "Upsell"], size=n
            ).tolist(),
            "competencia": rng.choice(
                ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"], size=n
            ).tolist(),
            "quantidade_licencas": rng.integers(1, 50, size=n).tolist(),
            "valor_bruto": np.round(rng.uniform(1200.0, 48000.0, size=n), 2).tolist(),
            "desconto_aplicado": rng.choice(
                [0.0, 0.05, 0.10, 0.15, 0.20], size=n, p=[0.45, 0.25, 0.15, 0.10, 0.05]
            ).tolist(),
        }
    )


def _metas_regionais(path: Path) -> None:
    """CSV no padrão de planilhas brasileiras: ';', vírgula decimal e Windows-1252."""
    linhas = ["uf;região;meta_mrr;margem_alvo;gerente"]
    regioes = {
        "SP": "Sudeste",
        "RJ": "Sudeste",
        "MG": "Sudeste",
        "PR": "Sul",
        "SC": "Sul",
        "RS": "Sul",
        "BA": "Nordeste",
        "PE": "Nordeste",
        "DF": "Centro-Oeste",
        "GO": "Centro-Oeste",
    }
    gerentes = [
        "Ana Beatriz",
        "Carlos Eduardo",
        "Fernanda Lima",
        "Rafael Souza",
        "Juliana Costa",
        "João Gonçalves",
        "Márcia Araújo",
        "Otávio Brandão",
        "Lúcia Fagundes",
        "Sérgio Assunção",
    ]
    # Metas calibradas para atingimentos entre ~65% e ~115% no fluxo de demonstração.
    metas = [
        583_000.0,
        192_800.5,
        245_000.0,
        135_250.75,
        155_000.0,
        138_000.0,
        111_500.5,
        109_750.0,
        63_700.0,
        89_900.25,
    ]
    for i, uf in enumerate(UFS):
        meta = metas[i]
        margem = 0.35 - i * 0.012
        linhas.append(f"{uf};{regioes[uf]};{meta:.2f};{margem:.3f};{gerentes[i]}".replace(".", ","))
    path.write_bytes(("\r\n".join(linhas) + "\r\n").encode("cp1252"))


def ensure_sample_datasets(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    builders = {
        "clientes_enterprise.csv": _clientes,
        "transacoes_vendas.csv": _vendas,
    }
    for name, build in builders.items():
        df = build(rng)  # sempre consome o gerador, para manter os dados estáveis
        path = data_dir / name
        if not path.exists():
            df.write_csv(path)
    metas = data_dir / "metas_regionais_br.csv"
    if not metas.exists():
        _metas_regionais(metas)
