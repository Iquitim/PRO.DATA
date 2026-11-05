# Como adicionar uma ferramenta

Uma ferramenta é um modelo de configuração Pydantic + uma função decorada com
`@tool`. Catálogo da API, formulário do Inspector, validação, cache e paleta
vêm daí — não há código de frontend por ferramenta.

## 1. Escreva a spec

Para comportamento novo, crie `specs/NNN-nome/spec.md` com os requisitos e
critérios de aceite (ver `.specify/memory/constitution.md`).

## 2. Declare a ferramenta

No módulo da família certa em `src/prodata/nodes/` (`io`, `prep`, `transform`,
`bi`, `ml`, ou `reshape` para reformatação):

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

## 5. SQL (opcional)

Para a caixa aparecer na aba SQL, declare a tradução ao lado do `run`. Sem isso, ela
aparece em vermelho como "sem SQL", e o código da saída para nela.

```python
@sql_for("prep.round")
def round_sql(ctx: SqlContext, cfg: RoundConfig) -> dict[str, Fragment]:
    source = ctx.input()
    items = [f"round({q(c)}, {cfg.decimals}) AS {q(c)}" for c in cfg.columns]
    return {"out": Fragment(f"SELECT * REPLACE ({join_list(items)})\nFROM {q(source.block)}", f"Arredonda {len(items)} coluna(s)")}
```

Use `q()` em nomes e `lit()` em valores, nunca texto direto. Fragmento devolve uma
entrada por porta de saída; `explain` é a frase que aparece na trilha, e `notes` são as
ressalvas. A tradução precisa dar o mesmo resultado que o `run`: acrescente o caso em
`tests/test_sql_equivalence.py`, que usa dados com vazios, acentos e nomes estranhos.

## 6. Teste

Adicione um teste em `tests/test_nodes.py` e rode `uv run pytest`.

## Entradas extras e caixas que só rodam a pedido

- `Port(..., required=False, when={"campo": ["valor"]})` cria uma entrada que só aparece ligada ou, quando a
  configuração bate com `when`, como a próxima livre. É como o Output Data recebe várias planilhas.
- `only_on_request=` em `@tool` recebe `(ctx, cfg)` e devolve um texto quando a caixa não deve rodar sozinha ao abrir
  um fluxo: uma chamada que pode gravar dados ou gastar cota. Ela espera o clique em Executar.
