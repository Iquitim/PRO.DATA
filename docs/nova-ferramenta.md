# Como adicionar uma ferramenta

Uma ferramenta é um modelo de configuração Pydantic + uma função decorada com
`@tool`. Catálogo da API, formulário do Inspector, validação, cache e paleta
vêm daí — não há código de frontend por ferramenta.

## 1. Escreva a spec

Para comportamento novo, crie `specs/NNN-nome/spec.md` com os requisitos e
critérios de aceite (ver `.specify/memory/constitution.md`).

## 2. Declare a ferramenta

No módulo da família certa em `src/prodata/nodes/` (`io`, `prep`, `transform`,
`bi`, `ml`, `genai`):

```python
class RoundConfig(ToolConfig):
    columns: list[str] = Field(default_factory=list, title="Colunas", json_schema_extra=ui(widget="columns"))
    decimals: int = Field(2, ge=0, le=10, title="Casas decimais")


@tool(
    type="prep.round",
    name="Round",
    category="prep",
    icon="function",
    description="Arredonda colunas numéricas.",
    config=RoundConfig,
    annotate=lambda c: f"{len(c.columns)} coluna(s) · {c.decimals} casas",
)
def round_columns(ctx: NodeContext, cfg: RoundConfig) -> NodeOutput:
    df = ctx.input()
    return NodeOutput(tables={"out": df.with_columns(pl.col(cfg.columns).round(cfg.decimals))})
```

Portas padrão: uma entrada `in` e uma saída `out`. Para outras, passe
`inputs=[Port(...)]` / `outputs=[Port(...)]`; use `kind="model"` para objetos de
modelo e `required=False` para entradas opcionais.

## 3. Widgets disponíveis

O widget é inferido do tipo (`bool` → toggle, `Literal` → select, `int/float` →
número, `list[BaseModel]` → lista de itens). Para os demais, use
`json_schema_extra=ui(widget=...)`:

| Widget | Uso |
|--------|-----|
| `column` / `columns` | escolha de coluna(s) do esquema de entrada (`port=` para uma porta específica) |
| `expression` | expressão estilo Alteryx, com validação ao vivo |
| `sql`, `template`, `textarea` | editores de texto |
| `dataset`, `sheet` | arquivo de `storage/datasets` e aba do Excel |
| `grid` | tabela editável (Text Input) |
| `select_columns` | tabela manter/renomear/converter (Select) |
| `connection`, `db_table`, `db_query` | conexão de banco, tabela (agrupada por esquema) e consulta SQL com prévia |

`ui(show_if={"campo": [valores]})` mostra o campo condicionalmente;
`ui(group="Avançado")` move para uma seção recolhível; `ui(labels={...})` dá
rótulos legíveis às opções de um `Literal`.

## 4. Regras

- Erros esperados (coluna inexistente, configuração incompleta) são `ValueError`
  com mensagem para o usuário, em português.
- Nada de efeitos colaterais fora de `ctx.exports_dir`; se houver, marque
  `side_effect=True` para nunca usar cache.
- Se o resultado depende de algo além da configuração e das entradas (um
  arquivo, por exemplo), informe `fingerprint=` para invalidar o cache.

## 5. Teste

Adicione um teste em `tests/test_nodes.py` e rode `uv run pytest`.
