# PRO.DATA

*Ferramenta de dados do Grupo Protege.*

Plataforma visual de pipelines de dados: monte fluxos arrastando ferramentas
em um canvas, conecte entradas e saídas, execute e inspecione o resultado de
cada etapa. O motor é colunar (Polars + DuckDB + Apache Arrow) e roda
localmente.

- **Ingestão** de CSV, Excel, Parquet, JSON/JSON Lines e Arrow, com detecção
  automática de formato, encoding (UTF-8, Windows-1252…), delimitador e
  separador decimal — CSVs brasileiros (`;` e vírgula decimal) funcionam sem
  configuração. Em planilhas, a prévia mostra as **abas** como guias e permite
  **pular linhas e colunas** quando a tabela não começa em A1.
- **Bancos de dados**: conexões com PostgreSQL e SQL Server (somente leitura).
  Na aba Dados, **consultas de banco** (uma tabela ou SQL livre, com prévia)
  ficam ao lado dos arquivos, e o mesmo **Input Data** lê qualquer uma dessas
  fontes. A senha fica no Gerenciador de Credenciais do Windows, nunca em
  arquivos do projeto.
- **Destinos à sua escolha**: o Output Data grava em qualquer pasta, e o fluxo
  pode ser salvo e aberto de qualquer pasta (*Salvar como…* / *Abrir arquivo…*).
- **28 ferramentas** na paleta, em 5 famílias: entrada/saída, preparação (com
  Text To Columns, Record ID e Running Total), combinação e transformação (Join
  com saídas L/J/R, Cross Tab, Transpose, Append Fields, Summarize, Union, SQL via
  DuckDB), BI (Chart, KPI Card, Venn e Table) e Machine Learning (scikit-learn).
- **Ponto de cache** (como o "Cache and Run" do Alteryx): congela o resultado de
  uma caixa — inclusive em disco — e dispensa tudo o que vem antes dela até alguma
  caixa anterior mudar. Ideal para consultas a banco e arquivos grandes.
- **Seleção múltipla**: `Shift`/`Ctrl` + clique, `Shift` + arrastar (retângulo) e
  `Ctrl+A`; mover, alinhar, distribuir, agrupar em caixa de organização ou tirar
  dela, copiar e excluir várias caixas de uma vez.
- **Dados de cada porta**: clicar numa saída mostra o que sai; clicar numa
  entrada mostra o que chega por ela.
- **Execução incremental**: só recalcula os nós cuja configuração, entradas ou
  arquivo de origem mudaram.
- **Perfil de dados** em toda saída: barra de qualidade (preenchido/vazio/nulo),
  histogramas e estatísticas por coluna.
- **Dashboard em canvas**: página de tamanho fixo (16:9, A4 ou altura livre) onde
  os visuais se arrastam e redimensionam com encaixe e guias; **Organizar** com
  layout automático e 5 layouts prontos; painel **Formato** (cores, rótulos,
  eixos, cartão); textos, imagens, logo e formas; **imagem PNG** da página ou de um
  visual. O layout fica gravado no arquivo do fluxo.
- **Visuais**: colunas, barras, linhas, rosca, empilhado, agrupado, 100%, área,
  Pareto, funil, dispersão, Venn (2 conjuntos proporcionais ou 3), medidor, tabela
  com cores por faixa e big number com variação contra meta ou período anterior e
  minigráfico de tendência. Um painel de **gráficos e resumos** abaixo do canvas
  mostra os mesmos visuais e um gráfico automático de cada Summarize.
- **Exploração sem mexer no fluxo**: filtros por coluna na tabela de resultados
  (texto, número, data, nulos), com perfil recalculado e opção de virar um nó Filter.
- **Organização**: caixas de etapa com nome, descrição, cor e interruptor
  liga/desliga (desligada, os nós de dentro não executam).
- **Edição rápida**: lixeira em cada caixa, copiar/recortar/colar caixas ou
  etapas inteiras (inclusive entre fluxos) e menu de botão direito com as ações
  mais comuns.
- **Abas**: vários fluxos abertos ao mesmo tempo, cada um com seu resultado e
  seu desfazer; as abas voltam ao reabrir o programa. Fechar uma aba ou a janela
  com alterações pergunta *Salvar / Não salvar / Cancelar*.
- **Editor de fórmulas**: cores por tipo (coluna, função, controle, operador
  lógico, comparação, texto, número), autocompletar de funções e colunas
  (`Ctrl+Espaço`), dica da assinatura da função e assistente com 33 funções
  documentadas e botões de operadores. Diferente é `!=` (`<>` também vale).
- **Interface ajustável**: painéis de ferramentas/configuração, resultados e
  gráficos podem ser arrastados para esquerda, direita ou embaixo, ou ocultados.
- **Aplicativo de desktop** para Windows: instalador `.exe` ou `.zip` portátil,
  sem exigir Python na máquina do usuário.

## Início rápido

Requer [uv](https://docs.astral.sh/uv/) (instala o Python 3.14 se preciso).

```powershell
uv sync
uv run prodata
```

Abra http://127.0.0.1:8765. Na primeira execução são gerados datasets de
exemplo e o fluxo de demonstração *Pipeline 360° de clientes*.

| Atalho | Ação |
|--------|------|
| `Ctrl+Enter` | Executar (com `Shift`: até o nó selecionado) |
| `Ctrl+S` / `Ctrl+Shift+S` / `Ctrl+O` | Salvar / salvar como / abrir fluxo |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Desfazer / refazer |
| `Ctrl+C` / `Ctrl+X` / `Ctrl+V` | Copiar / recortar / colar caixa ou etapa |
| `Ctrl+D` / `Delete` | Duplicar / excluir seleção |
| `F` | Ajustar à tela |
| `G` | Nova etapa (contêiner) |
| `?` | Todos os atalhos |

## Aplicativo de desktop (Windows)

O PRO.DATA também roda como programa instalável, em janela própria e offline:

```powershell
uv sync --extra desktop --group build
uv run prodata-desktop                 # testar a janela a partir do código
uv run python packaging/build.py       # gera dist/: instalador .exe, .zip portátil e a pasta do app
```

Os dados do usuário ficam em `%LOCALAPPDATA%\PRO.DATA`. Detalhes, requisitos e
diagnóstico em [docs/distribuicao.md](docs/distribuicao.md).

## Desenvolvimento

```powershell
uv run pytest            # testes
uv run ruff check src tests && uv run ruff format src tests
uv run mypy              # tipos
$env:PRODATA_RELOAD="true"; uv run prodata   # servidor com reload
```

A CI (`.github/workflows/ci.yml`) roda lint, tipos e testes em todo push e PR.
Para hooks locais: `uvx pre-commit install`.

### Spec-Driven Development

O projeto segue SDD no formato do [GitHub Spec Kit](https://github.com/github/spec-kit):

- `.specify/memory/constitution.md` — princípios não negociáveis (motor
  desacoplado da UI, ferramentas declarativas, segurança por padrão, falhas
  explícitas, testes).
- `specs/NNN-nome/` — `spec.md` (o quê e por quê, requisitos `RF-xxx`),
  `plan.md` (como) e `tasks.md` (passos ligados aos requisitos).

| Spec | Escopo |
|------|--------|
| [001](specs/001-arquitetura-modular/spec.md) | Arquitetura modular do motor e da API |
| [002](specs/002-motor-ingestao/spec.md) | Motor de ingestão de dados |
| [003](specs/003-workbench-ui/spec.md) | Interface de trabalho |
| [004](specs/004-layout-insights/spec.md) | Layout revisado: configuração à esquerda, dados à direita, gráficos e resumos abaixo do canvas |
| [005](specs/005-conexoes-banco/spec.md) | Conexões com PostgreSQL e SQL Server (somente leitura, senha no cofre do SO) |
| [006](specs/006-paineis-conteineres/spec.md) | Painéis reposicionáveis/ocultáveis e contêineres de etapa editáveis |
| [007](specs/007-organizacao-filtros/spec.md) | Caixa de organização na paleta e no Configurar; filtros exploratórios nos resultados |
| [008](specs/008-app-desktop/spec.md) | Aplicativo de desktop instalável (janela própria, instalador e portátil) |
| [009](specs/009-edicao-fontes-destinos/spec.md) | Lixeira, copiar/colar e menus no canvas; consultas na aba Dados lidas pelo Input Data; pasta do Output Data e do fluxo |
| [010](specs/010-abas-formulas-fechamento/spec.md) | Abas de fluxos, editor de fórmulas com cores e autocompletar, fechamento seguro; corrige o Salvar como no executável |
| [011](specs/011-planilhas-identidade/spec.md) | Abas e recorte de planilhas (pular linhas/colunas); identidade visual Grupo Protege |
| [012](specs/012-selecao-cache-portas/spec.md) | Seleção múltipla, ponto de cache e dados de entrada por porta; remove o assistente de fluxo |
| [013](specs/013-ferramentas-desempenho/spec.md) | Select com Todas/Nenhuma/Inverter, 6 ferramentas novas (Cross Tab, Transpose, Text To Columns, Record ID, Running Total, Append Fields), remove a IA generativa, canvas mais responsivo |
| [014](specs/014-dashboard-canvas/spec.md) | Dashboard em canvas (arrastar, redimensionar, guias, Organizar com layouts prontos), painel Formato, textos/imagens/formas, PNG, big number com variação e tendência, empilhados, Pareto, Venn, funil, dispersão, medidor e Table |

Para adicionar uma ferramenta, veja [docs/nova-ferramenta.md](docs/nova-ferramenta.md).

## Arquitetura

```text
src/prodata/
├── config.py          configurações (variáveis PRODATA_*)
├── main.py            create_app(): FastAPI + serviços + arquivos estáticos
├── api/               rotas HTTP finas e tradução de erros
├── domain/            modelos Pydantic do workflow e do relatório de execução
├── engine/            grafo, executor incremental, cache Arrow, perfil, fórmulas
├── nodes/             ferramentas (uma família por módulo) + registro declarativo
├── ingestion/         detecção e leitura de arquivos, repositório de datasets
├── connectors/        conexões com bancos (connectorx), senhas no cofre do SO
├── services/          repositório de workflows (biblioteca e arquivos)
├── samples/           datasets e fluxo de demonstração
├── desktop.py         app de desktop (servidor local + janela WebView2)
└── web/               frontend (ES modules nativos, sem build)
tests/                 pytest: grafo, fórmulas, ingestão, ferramentas, executor, API, conectores, exploração
specs/                 especificações (SDD)
storage/               datasets, workflows, cache e exportações (configurável)
```

O motor (`engine`, `nodes`, `ingestion`) não depende de FastAPI e pode ser
usado em scripts:

```python
from prodata.engine.cache import ResultCache
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.domain.workflow import Workflow

runner = WorkflowRunner(ResultCache(cache_dir), DatasetStore(data_dir, 200 * 2**20), exports_dir)
report = runner.run(Workflow.model_validate_json(path.read_text()))
```

Cada ferramenta declara um modelo de configuração Pydantic; o catálogo
(`GET /api/catalog`) descreve os campos e o Inspector gera o formulário a
partir dele. O frontend não tem código específico por ferramenta.

## API

Documentação interativa em http://127.0.0.1:8765/docs.

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/catalog` | Ferramentas, portas e campos de configuração |
| GET · POST | `/api/datasets` | Listar · enviar arquivo (`multipart`, `overwrite`) |
| POST | `/api/datasets/{nome}/preview` | Pré-visualizar com opções de leitura (`auto` é resolvido) |
| DELETE | `/api/datasets/{nome}` | Excluir arquivo |
| GET | `/api/workflows` · `/api/workflows/{id}` | Listar · obter fluxo |
| PUT · DELETE | `/api/workflows/{id}` | Salvar · excluir fluxo |
| POST | `/api/workflows/assistant` | Gerar fluxo a partir de uma descrição |
| POST | `/api/execute` | Executar (opcional `target_node_id`) |
| GET | `/api/results/{wf}/{nó}/{porta}` | Página de resultados com perfil (`offset`, `limit`, `search`, `sort_col`, `filters` em JSON) |
| GET | `/api/exports/{arquivo}` | Baixar arquivo gerado pelo Output Data |
| POST | `/api/formula/validate` | Validar expressão contra um esquema |
| GET · PUT · DELETE | `/api/connections[/{id}]` | Conexões com bancos (a senha só entra no PUT, nunca sai) |
| POST · GET · POST | `/api/connections/{id}/test` · `/tables` · `/preview` | Testar, listar tabelas, pré-visualizar |
| GET · PUT · DELETE | `/api/queries[/{id}]` | Consultas de banco da aba Dados (sem senha) |
| POST | `/api/queries/preview` | Prévia de uma consulta ainda não salva |
| POST | `/api/files/workflow/save` · `/open` | Salvar / abrir fluxo num caminho escolhido (`.prodata.json`) |

Fluxos são salvos na biblioteca `storage/workflows/<id>.prodata.json` ou, com
*Salvar como…*, em qualquer pasta (JSON legível, versionável em Git). O Input
Data aponta para um arquivo da aba Dados pelo nome ou para uma consulta como
`sql:<id>`; as consultas ficam em `storage/queries.json`.

## Desempenho

Decisões medidas (detalhes nos comentários do código):

- Bibliotecas pesadas carregam sob demanda: scikit-learn só ao treinar e
  connectorx só ao consultar um banco; o scikit-learn é pré-carregado em segundo
  plano logo após o servidor subir. Inicialização: 1,6 s → 0,8 s.
- O motor de fórmulas reaproveita uma base DuckDB com as macros já criadas e usa
  um cursor isolado por execução: 30–60 ms → 6 ms por nó Formula/Filter.
- Random Forest só usa vários núcleos acima de 20 mil linhas; abaixo disso o
  paralelismo deixava o treino mais lento (270 ms contra 203 ms).
- Conexões com banco fazem uma checagem TCP de 5 s antes do driver: servidor
  inacessível falha em ~2 s em vez de ~30 s.
- Execução incremental: reexecutar um fluxo sem mudanças leva ~9 ms.

## Configuração

Variáveis de ambiente (ou `.env`, ver `.env.example`): `PRODATA_HOST`,
`PRODATA_PORT`, `PRODATA_STORAGE_DIR`, `PRODATA_MAX_UPLOAD_MB`,
`PRODATA_CORS_ORIGINS`, `PRODATA_LOG_LEVEL`, `PRODATA_SEED_SAMPLES`,
`PRODATA_RELOAD`, `PRODATA_SECRETS_BACKEND` (`keyring` ou `memory`).

## Limitações conhecidas

- Modelos de ML ficam só em memória (não são serializados em disco) e são
  retreinados após reiniciar o servidor.
- Aplicação local e de usuário único: não há autenticação.
- Datasets são carregados inteiros em memória pelo Polars.

## Identidade visual

O tema segue a marca do Grupo Protege: azul-marinho `#043154`, dourado `#95793c`,
fonte Open Sans e o escudo oficial (`src/prodata/web/brand/`, ver o `LEIA-ME.md`
da pasta). Tudo fica em `src/prodata/web/css/brand.css`, carregado por último:
trocar a marca é editar esse arquivo e os arquivos de `brand/`. O ícone do
executável é gerado de `packaging/brand/protege-escudo-1024.png`.

