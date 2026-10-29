# Spec 001 — Arquitetura modular do motor e da API

Status: Implementada · Criada: 2026-10-28

## Contexto

A versão inicial concentrava catálogo e execução de 21 ferramentas em um único
arquivo de ~1.100 linhas (`if/elif` por tipo), criava estado global no import,
aceitava configurações sem validação e executava nós mesmo quando o nó anterior
falhava. Isso tornava o projeto difícil de testar, estender e confiar.

## Histórias de usuário

- **H1** — Como desenvolvedor, quero adicionar uma ferramenta nova criando um
  único módulo, sem editar o roteador da API nem o frontend.
- **H2** — Como analista, quero que um erro em um nó seja mostrado nele e que os
  nós seguintes apareçam como "não executados", em vez de erros em cascata.
- **H3** — Como analista, quero reexecutar um fluxo grande e ver apenas os nós
  alterados sendo recalculados.
- **H4** — Como analista, quero salvar, abrir, listar e excluir fluxos.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-001 | Cada ferramenta declara metadados, portas, modelo de configuração (Pydantic) e função de execução em um único registro. |
| RF-002 | O catálogo (`GET /api/catalog`) expõe, para cada ferramenta, a descrição dos campos de configuração (tipo de widget, opções, padrão, condições de visibilidade). |
| RF-003 | A configuração de cada nó é validada antes da execução; erros de validação são reportados no nó, com o campo afetado. |
| RF-004 | O grafo é validado: IDs únicos, arestas apontando para nós e portas existentes, ausência de ciclos. |
| RF-005 | Um nó com falha (ou com entrada obrigatória ausente) não executa; seus descendentes recebem status `skipped` com o motivo. |
| RF-006 | "Executar até aqui" executa apenas o nó alvo e seus ancestrais. |
| RF-007 | Execução incremental: um nó cuja configuração, entradas e arquivos de origem não mudaram reaproveita o resultado em cache (status `cached`). |
| RF-008 | CRUD de workflows: listar, obter, salvar (upsert) e excluir, com ID validado (`^[A-Za-z0-9_-]{1,64}$`). |
| RF-009 | Métricas do AutoML são calculadas em um conjunto de validação separado (holdout). |
| RF-010 | A aplicação é criada por uma factory (`create_app(settings)`), sem efeitos colaterais no import. |

## Requisitos não funcionais

- RNF-01 — Configuração via variáveis de ambiente `PRODATA_*` (ver `config.py`).
- RNF-02 — Logs estruturados com `logging`; nenhum erro engolido silenciosamente.
- RNF-03 — CORS restrito a origens configuradas.

## Critérios de aceite

- Fluxo 360° de demonstração executa com todos os nós `executed`.
- Reexecução imediata do mesmo fluxo retorna todos os nós como `cached`.
- Um fluxo com ciclo retorna HTTP 422 com mensagem identificando o ciclo.
- Quebrar a configuração do Filter marca Filter como `error` e Join e
  descendentes como `skipped`.
- `uv run pytest` cobre RF-001 a RF-010.
