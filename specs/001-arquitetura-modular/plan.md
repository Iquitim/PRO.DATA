# Plano 001 — Arquitetura modular

## Layout (src layout)

```text
src/prodata/
├── config.py            # Settings (pydantic-settings, prefixo PRODATA_)
├── main.py              # create_app() + lifespan; nenhum efeito no import
├── __main__.py          # `python -m prodata` → uvicorn
├── api/
│   ├── deps.py          # acesso tipado aos serviços em app.state
│   ├── errors.py        # handlers → {"detail", "code"}
│   └── routes/          # catalog, datasets, workflows, execution, formula, copilot
├── domain/
│   ├── workflow.py      # Workflow, Node, Edge, Container (Pydantic)
│   └── execution.py     # NodeResult, AnchorSummary, ExecutionReport
├── engine/
│   ├── graph.py         # ordenação topológica com detecção de ciclo, ancestrais
│   ├── runner.py        # WorkflowRunner (validação, cache incremental, skip)
│   ├── cache.py         # ResultCache (memória + Arrow IPC em disco)
│   ├── profiling.py     # perfil de colunas (OK/vazio/nulo, histogramas, stats)
│   └── formula.py       # transpilador de expressões estilo Alteryx → DuckDB
├── nodes/
│   ├── base.py          # ToolSpec, Port, registro, describe_fields()
│   └── io.py, prep.py, transform.py, bi.py, ml.py, genai.py
├── ingestion/           # ver spec 002
├── services/            # workflows (repositório JSON), copilot (templates)
├── samples/             # geração dos datasets e fluxo de demonstração
└── web/                 # frontend estático (ver spec 003)
```

## Contrato de uma ferramenta

```python
class FilterConfig(ToolConfig):
    mode: Literal["expression", "simple"] = Field("expression", title="Modo")
    expression: str = Field("", json_schema_extra={"widget": "expression",
                                                   "show_if": {"mode": ["expression"]}})

@tool(type="prep.filter", name="Filter", category="prep", icon="filter",
      inputs=[Port("in", "I", "Entrada")],
      outputs=[Port("T", "T", "Verdadeiro"), Port("F", "F", "Falso")],
      config=FilterConfig)
def run_filter(ctx: NodeContext, cfg: FilterConfig) -> NodeOutput: ...
```

`describe_fields(FilterConfig)` produz a lista de campos consumida pelo
Inspector: `name, title, help, widget, default, options, show_if, item_fields`.
O widget é inferido da anotação (`bool→toggle`, `Literal→select`,
`int/float→number`, `list[BaseModel]→list`) ou declarado em
`json_schema_extra["widget"]`.

## Execução

1. `Workflow` é validado (Pydantic + `graph.validate`) → 422 se inválido.
2. Ordem topológica (Kahn); ciclo → `GraphError`.
3. Para cada nó: se desabilitado → `disabled`; se algum pai não produziu a porta
   necessária → `skipped`; senão valida config → calcula *fingerprint*
   (`sha256(tipo, config, fingerprints dos pais, assinatura de arquivo)`).
4. Fingerprint igual ao do cache → `cached`, sem reexecutar.
5. Saídas são guardadas em memória e em `storage/cache/<wf>/<node>__<porta>.arrow`.

## Riscos e decisões

- **Transpilador por regex** foi mantido (com testes); um parser completo fica
  para spec futura.
- **Modelos de ML** ficam só em memória (não serializamos objetos sklearn com
  pickle em disco por segurança).
- Compatibilidade do formato `.prodata.json` mantida: `sourceHandle` e
  `targetHandle` continuam como nomes de campo.
