# PRO.DATA

*Ferramenta de dados do Grupo Protege.*

Plataforma visual de pipelines de dados: monte fluxos arrastando ferramentas
em um canvas, conecte entradas e saídas, execute e inspecione o resultado de
cada etapa. O motor é colunar (Polars + DuckDB + Apache Arrow) e roda
localmente.

- **Ingestão** de CSV, Excel (inclusive `.xlsb`), Parquet, JSON/JSON Lines e Arrow, com detecção
  automática de formato, encoding (UTF-8, Windows-1252…), delimitador e
  separador decimal — CSVs brasileiros (`;` e vírgula decimal) funcionam sem
  configuração. Em planilhas, a prévia mostra as **abas** como guias e permite
  **pular linhas e colunas** quando a tabela não começa em A1.
- **Manual dentro do programa** (`?` ou `F1`): o guia ao lado do trabalho, com busca, imagens no tema da tela,
  "Mostrar onde fica" e exemplos para experimentar. **Ctrl+K** acha ferramenta, ação, caixa, fonte ou capítulo.
- **Modo foco** (`F11`), painéis recolhidos em faixa e editor de fórmula em janela larga (**Abrir grande**).
- **Vista Dados**: a primeira tela reúne arquivos, consultas, APIs, conexões e constantes,
  com situação, prévia, qualidade das colunas e o **mapa de onde cada fonte é usada** nos
  fluxos da biblioteca. Antes de excluir uma fonte em uso, a tela lista o que deixa de funcionar.
- **Constantes**: um valor com nome, escrito `[#nome]`, nas fórmulas, no Filter básico, no
  nome do arquivo do Output Data e nos parâmetros fixos de API. Do fluxo (vão no arquivo) ou
  compartilhadas (vista Dados). Mudar o valor refaz só as caixas que usam a constante.
- **Data Quality**: regras prontas (não vazio, sem duplicados, CPF, CNPJ alfanumérico, e-mail,
  faixa de número, data, lista de valores e fórmula livre), escolhidas por cartões. Saídas
  P (passou) e F (falhou, com `regra` e `motivo`), e selo no canvas com as falhas.
- **Abertura protegida**: um fluxo que veio de fora não executa nada até a pessoa conferir o
  que ele lê, calcula e grava e confiar.
- **Bancos de dados**: conexões com PostgreSQL e SQL Server (somente leitura).
  Na vista Dados, **consultas de banco** (uma tabela ou SQL livre, com prévia)
  ficam ao lado dos arquivos, e o mesmo **Input Data** lê qualquer uma dessas
  fontes. A senha fica no Gerenciador de Credenciais do Windows, nunca em
  arquivos do projeto.
- **APIs**: cadastre uma API na vista Dados (GET ou POST, JSON, CSV ou XML, com
  paginação e novas tentativas) e leia no Input Data. Token, chave, senha e OAuth 2
  ficam no cofre do sistema. API de endereço fixo vira tabela direto no Input Data; com
  variável (`{sigla}`), entra como **API Loop**: você escolhe a coluna que preenche
  cada variável, e ele chama uma vez por valor, juntando as respostas. O cadastro guarda
  o link da documentação da API e uma anotação do que faz cada parâmetro. A tabela pode
  ser a saída de outra API. O cadastro tem
  exemplos prontos e mostra a resposta ao lado da tabela, e o fluxo de demonstração
  consome a API pública do IBGE, só depois do clique em Executar.
- **Destinos à sua escolha**: o Output Data grava em qualquer pasta, e o fluxo
  pode ser salvo e aberto de qualquer pasta (*Salvar como…* / *Abrir arquivo…*).
- **Jira Cloud, só leitura**: conexão guiada com token de leitura, consulta sem escrever
  JQL, demandas, histórico e comentários como tabelas, atualização só do que mudou e retomada.
- **Replay analítico**: linha do tempo no dashboard, corrida de barras, bolhas, Sankey,
  destaques com critério, história em cenas, GIF por gráfico e HTML com tudo isso.
- **Lições guiadas** no Manual, cada uma num fluxo próprio.
- **44 ferramentas** na paleta, em 6 famílias: entrada/saída, preparação (com
  Text To Columns, Record ID, Running Total, Multi-Row Formula e Data Quality), combinação e transformação (Join
  com saídas L/J/R, Cross Tab, Transpose, Append Fields, Summarize, Union, SQL via
  DuckDB, Fuzzy Match), conferência e reúso (Reconcile, Compare Runs, Subflow), BI (Chart, KPI Card, Venn e Table)
  e Machine Learning (scikit-learn, com biblioteca de modelos).
- **Ponto de cache** (como o "Cache and Run" do Alteryx): congela o resultado de
  uma caixa — inclusive em disco — e dispensa tudo o que vem antes dela até alguma
  caixa anterior mudar. Ideal para consultas a banco e arquivos grandes.
- **Seleção múltipla**: `Shift`/`Ctrl` + clique, `Shift` + arrastar (retângulo) e
  `Ctrl+A`; mover, alinhar, distribuir, agrupar numa etapa ou tirar
  dela, copiar e excluir várias caixas de uma vez.
- **Dados de cada porta**: clicar numa saída mostra o que sai; clicar numa
  entrada mostra o que chega por ela.
- **Execução incremental**: só recalcula as caixas cuja configuração, entradas ou
  arquivo de origem mudaram.
- **Perfil de dados** em toda saída: barra de qualidade (preenchido/vazio/nulo),
  histogramas e estatísticas por coluna.
- **Dashboard em canvas**: página de tamanho fixo (16:9, A4 ou altura livre) onde
  os visuais se arrastam e redimensionam com encaixe e guias; **Organizar** com
  layout automático e 5 layouts prontos; painel **Formato** (cores, rótulos,
  eixos, cartão); textos, imagens, logo e formas; **filtros na página**, sem executar
  o fluxo de novo; **imagem PNG** da página ou de um visual e **HTML** num arquivo só,
  que abre sem o programa e sem internet, com os filtros funcionando. O layout fica
  gravado no arquivo do fluxo.
- **Visuais**: colunas, barras, linhas, rosca, empilhado, agrupado, 100%, área,
  Pareto, funil, dispersão, Venn (2 conjuntos proporcionais ou 3), medidor, tabela
  com cores por faixa e big number com variação contra meta ou período anterior e
  minigráfico de tendência. Um painel de **gráficos e resumos** abaixo do canvas
  mostra os mesmos visuais e um gráfico automático de cada Summarize.
- **Exploração sem mexer no fluxo**: filtros por coluna na tabela de resultados
  (texto, número, data, nulos), com perfil recalculado e opção de virar uma caixa Filter.
- **Organização**: caixas de etapa com nome, descrição, cor e interruptor
  liga/desliga (desligada, as caixas de dentro não executam).
- **Edição rápida**: lixeira em cada caixa, copiar/recortar/colar caixas ou
  etapas inteiras (inclusive entre fluxos) e menu de botão direito com as ações
  mais comuns.
- **Abas**: vários fluxos abertos ao mesmo tempo, cada um com seu resultado e
  seu desfazer; as abas voltam ao reabrir o programa. Fechar uma aba ou a janela
  com alterações pergunta *Salvar / Não salvar / Cancelar*.
- **Editor de fórmulas**: cores por tipo (coluna, função, controle, operador
  lógico, comparação, texto, número), autocompletar de funções e colunas
  (`Ctrl+Espaço`), dica da assinatura da função e assistente com 82 funções
  documentadas (inclusive números e datas no padrão brasileiro, CPF/CNPJ,
  expressões regulares) e botões de operadores. Diferente é `!=` (`<>` também
  vale). A Formula cria colunas novas ou altera colunas existentes, e calcula
  entre colunas da mesma linha com `Average`, `Sum`, `Median`, `Mode`, `StdDev`, `Max` e `Min`.
- **Esquemas visuais** no Configurar do Cross Tab, do Transpose, do Join, do
  Summarize e do API Loop: o antes e o depois com uma amostra dos seus dados.
- **Aba SQL**: o fluxo escrito em SQL do DuckDB, com um código por saída (só o
  que existe entre as entradas e ela) ou um código unificado de várias saídas,
  sem repetir etapas. Cada etapa é rodada e comparada com o resultado do fluxo:
  o estado da saída diz se o código deu o mesmo resultado, e caixas sem tradução
  ficam em vermelho. Copie ou baixe `.sql` ou `.zip` para o time de dados.
- **Join como no Alteryx**: escolha se o J mantém as chaves dos dois lados, só
  da esquerda ou só da direita, e selecione, renomeie, converta e reordene as
  colunas do J sem precisar de um Select depois.
- **Summarize** com moda e desvio padrão, além de soma, média, mediana,
  contagens, mínimo, máximo e concatenação.
- **Excel por padrão** no Output Data: ligue várias tabelas na mesma caixa e cada
  uma vira uma planilha do arquivo, ou junte planilhas de caixas diferentes. Se o arquivo de saída já existe, o
  PRO.DATA pergunta ao executar: substituir, criar um novo (data e hora no nome)
  ou adicionar a planilha.
- **Fontes que se atualizam**: *Vincular arquivo* lê a planilha original (pasta
  da rede, OneDrive) sem copiar; mudanças no arquivo são percebidas a cada
  execução e também invalidam o ponto de cache, que pode ainda renovar todo dia
  ou a cada hora (para bancos de dados).
- **Dashboard que responde ao clique**: faixa de filtros com valores à mostra e controle
  deslizante; clicar numa barra ou fatia filtra a página, também no HTML.
- **Multi-Row com receitas**: preencher para baixo, diferença, variação %, valor anterior,
  próximo valor e "mudou?", com esquema visual do antes e depois.
- **Fluxos recebidos sob controle**: fórmulas e a caixa SQL não acessam arquivos nem a
  internet, e a interface e o HTML exportado têm política de conteúdo.
- **Segurança**: rótulos de confidencialidade na exportação e no dashboard, com dica do que
  cada um faz, HTML com senha, registro local das exportações e destinos de API controlados: públicas livres,
  rede interna só com a lista da TI (`%ProgramData%\PRO.DATA\politica.json`).
- **Conectores e animações**: os fios levam a cor de uma família de ferramentas à
  outra, com seta na chegada. Ao executar, o dado corre pelo fio até a caixa da vez;
  com o programa parado, nada se move, e as animações respeitam a opção do Windows.
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
| `Ctrl+Enter` | Executar (com `Shift`: até a caixa selecionada) |
| `Ctrl+S` / `Ctrl+Shift+S` / `Ctrl+O` | Salvar / salvar como / abrir fluxo |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Desfazer / refazer |
| `Ctrl+C` / `Ctrl+X` / `Ctrl+V` | Copiar / recortar / colar caixa ou etapa |
| `Ctrl+D` / `Delete` | Duplicar / excluir seleção |
| `F` | Ajustar à tela |
| `G` | Nova etapa |
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
| [015](specs/015-ajustes-035/spec.md) | Subtítulo e nomes de legenda no dashboard, grupos do Venn escolhidos na lista, esquemas visuais (Cross Tab, Transpose, Join), Excel com várias planilhas, Formula alterando colunas, 42 funções novas, preferências lembradas no programa instalado |
| [016](specs/016-telas-menores-cache/spec.md) | Painéis proporcionais e densidade compacta em telas menores; caixas puladas pelo ponto de cache em destaque, com contagem e "mostrar as puladas" |
| [017](specs/017-fontes-vivas-exportacao/spec.md) | Arquivos vinculados (fonte sempre atualizada), cache que percebe a fonte e renova por prazo, exportação que pergunta antes de sobrescrever, Venn seguro com colunas grandes |
| [018](specs/018-versao-04/spec.md) | Tela de abertura, `.xlsb`, Select que reordena colunas e converte tipos com tolerância e aviso, Formula em coluna existente corrigida, média/soma entre colunas, Join que mantém as duas chaves, aviso de espaços em branco, caixa em execução brilhando |
| [019](specs/019-join-select-summarize/spec.md) | Join com lado das chaves e Select embutido, esquema visual do Summarize, moda e desvio padrão (Summarize e Formula), compatibilidade com fluxos da 0.3.8 |
| [020](specs/020-aba-sql/spec.md) | Aba SQL: código por saída e unificado, caminho por porta, trilha do fluxo, conferência com o motor por etapa e de ponta a ponta, entrega em `.sql` e `.zip` |
| [021](specs/021-versao-055/spec.md) | APIs, filtros e HTML no dashboard, Multi-Row e tema Dracula |
| [022](specs/022-api-didatica/spec.md) | API didática, com exemplos visuais |
| [023](specs/023-parametros-api/spec.md) | API com e sem parâmetro; variáveis e parâmetros fixos |
| [024](specs/024-documentacao-api/spec.md) | Documentação e anotações de cada API |
| [025](specs/025-conectores-e-guia/spec.md) | Conectores, animações e guia reorganizado |
| [026](specs/026-seguranca-e-rotulos/spec.md) | Ordenação, Summarize por tipo, rótulos, segurança de API e HTML; Multi-Row com receitas e clique no gráfico |
| [027](specs/027-qualidade-do-codigo/spec.md) | Código dividido, limites verificados por teste e fórmulas sem acesso externo |
| [028](specs/028-dados-e-confianca/spec.md) | Vista Dados com mapa de uso, abertura protegida, Data Quality e constantes |
| [030](specs/030-jira-e-replay/spec.md) | Conector do Jira (só leitura), Estado por período, linha do tempo, corrida de barras, bolhas, Sankey, destaques, história, GIF por gráfico e lições guiadas. |
| [029](specs/029-experiencia-e-idioma/spec.md) | Espaço para o fluxo, um nome para cada coisa, letra e contraste, busca Ctrl+K, `[#hoje]` e Manual dentro do programa |

Para adicionar uma ferramenta, veja [docs/nova-ferramenta.md](docs/nova-ferramenta.md).

Para pedir ajuda a um assistente de IA sobre um fluxo, envie junto o [docs/contexto-ia.md](docs/contexto-ia.md): ele
explica o formato do arquivo e todas as ferramentas. É gerado do código por `docs/gerar_contexto_ia.py`.

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
| GET · PUT · DELETE | `/api/queries[/{id}]` | Consultas de banco da vista Dados (sem senha) |
| POST | `/api/queries/preview` | Prévia de uma consulta ainda não salva |
| GET · PUT · DELETE | `/api/apis[/{id}]` | Fontes de API da vista Dados (segredos entram no PUT, nunca saem) |
| POST | `/api/apis/preview` | Chamada de teste de uma API, só a primeira página, com amostra da resposta |
| GET | `/api/apis/examples` | APIs públicas de exemplo para começar um cadastro (nada é chamado) |
| POST | `/api/dashboard/filter-options` · `/filtered` | Valores dos filtros · visuais recalculados, sem executar o fluxo |
| POST · GET | `/api/dashboard/export-data` · `/viewer.js` | Dados e script do dashboard em HTML |
| POST | `/api/dashboard/export-log` | Registra uma exportação feita na tela (sem os dados) |
| POST | `/api/files/workflow/save` · `/open` | Salvar / abrir fluxo num caminho escolhido (`.prodata.json`) |
| GET | `/api/usage` | Onde cada fonte e cada constante é usada nos fluxos da biblioteca |
| GET · POST · DELETE | `/api/constants[/{nome}]` | Constantes compartilhadas (`previous` no POST renomeia) |
| POST | `/api/trust/state` · `/confirm` | Abertura protegida: situação do fluxo e confirmação de confiança |

Fluxos são salvos na biblioteca `storage/workflows/<id>.prodata.json` ou, com
*Salvar como…*, em qualquer pasta (JSON legível, versionável em Git). O Input
Data aponta para um arquivo da vista Dados pelo nome, para uma consulta como
`sql:<id>` ou para uma API como `api:<id>`; as consultas ficam em
`storage/queries.json` e as APIs, sem segredos, em `storage/apis.json`. As constantes compartilhadas ficam em
`storage/constantes.json` e os fluxos confirmados na abertura protegida, em `storage/confianca.json`.

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

