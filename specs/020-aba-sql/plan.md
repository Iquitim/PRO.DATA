# Plano — Spec 020: aba SQL

## O que já foi comprovado

Prova de conceito fora do programa, com o fluxo de demonstração, na versão 0.4.1:

- As 8 etapas de transformação até "Atingimento" (Cleanse, Formula, Filter, Summarize e Join) deram resultado idêntico ao do motor, etapa a etapa, usando `formula.transpile` e as macros atuais.
- O caminho completo, a partir dos 3 arquivos, também bateu em todas as 11 etapas.
- As consultas dos visuais executaram; não foram comparadas com o motor.

Isso cobre um único fluxo e não substitui os testes por ferramenta.

## Decisões tomadas na implementação

- **Ordem da trilha e do código:** `graph.reading_order` segue cada cadeia até onde der. A ordem de execução não mudou.
- **Esquema sem executar:** cada bloco é descrito com `DESCRIBE` sobre tabelas vazias que têm o esquema do motor. Só Cross Tab e Text To Columns sem número de partes pedem uma execução, porque as colunas vêm dos dados.
- **Transpose:** virou `UNION ALL` por coluna, em vez de `UNPIVOT`. É mais simples de levar a outros dialetos.
- **CP1252:** usa `latin-1`, que é nativo do DuckDB, quando o arquivo não tem bytes em que os dois diferem; é o mesmo resultado sem depender de extensão.
- **Segurança da conferência:** `allowed_paths` com `enable_external_access=false` funciona como previsto: só lê as fontes, não grava e não pode ser reativado. A caixa SQL só traduz um único `SELECT`.
- **Visuais:** a consulta por trás do visual não é comparada com o gráfico. As etapas antes dela são conferidas, e a saída fica no máximo como "Conferido, com ressalvas", com esse aviso.

- **CSV:** o DuckDB deduz alguns tipos de outro jeito ("007" vira texto; T/F vira booleano). A leitura compara a dedução com o esquema do motor e escreve `types` só para o que diverge; sem cabeçalho, escreve `names`.
- **Comandos:** gerar o código nunca executa. Toda caixa passa por uma checagem de consulta única antes de virar visão, e a fórmula do motor recusa `;` fora de texto.

- **Rótulo do estado:** "Conferido" no lugar de "Pronto para levar". O estado diz o que foi provado (o SQL dá o mesmo resultado que o fluxo), não que o código já roda no Fabric.

## Arquitetura

- `engine/sql/`: motor desacoplado da interface.
  - `fragment.py`: o que cada ferramenta recebe e devolve, e os cuidados com texto SQL.
  - `macros.py`: as funções do PRO.DATA em SQL.
  - `plan.py`: blocos, saídas, caminho por porta, ordem e nomes estáveis.
  - `render.py`: consulta única, código unificado, cabeçalho, preâmbulo de macros.
  - `verify.py`: conferência por etapa e de ponta a ponta.
- `@tool` ganha um parâmetro opcional `to_sql` ao lado do `run`, seguindo o princípio III. Ferramenta sem `to_sql` vira "sem tradução" sem nenhum tratamento especial.
- O dialeto é um parâmetro desde o início, mesmo só com DuckDB nesta versão.
- Formula e Filter em modo expressão reaproveitam `formula.transpile`. Não haverá um segundo tradutor.
- O preâmbulo traz só as macros usadas, com o texto de `formula.connect`. Para isso, as definições passam a ser consultáveis por nome.

## Contratos da API

- `POST /api/sql/generate`: recebe o fluxo e a seleção; devolve saídas, blocos, código e cabeçalho. Não executa o fluxo.
- `POST /api/sql/verify`: inicia a conferência e devolve um identificador.
- `GET /api/sql/verify/{id}`: andamento e resultado por etapa e por saída.
- `POST /api/sql/download`: `.sql` ou `.zip`.

## Conferência

- A conexão é separada e em memória, sem acesso a segredos, e registra as tabelas do cache (`ResultCache.table`).
- Cada saída é comparada com `EXCEPT ALL` nos dois sentidos, depois de normalizar decimais.
- Um limite de linhas por tabela fica configurável; acima dele, o estado é "Ainda não conferido".
- A execução usa uma assinatura do fluxo (`graph.upstream_signature`). Resultado de outra assinatura é descartado.
- Regra de segurança para a caixa SQL: consultas de usuário podem conter comandos como `COPY` ou leitura de arquivos. A conferência roda com acesso externo desligado (`enable_external_access=false`) nas etapas que usam o cache. A etapa de ponta a ponta libera só a leitura das fontes conhecidas; se o DuckDB não permitir esse recorte, ela pula as saídas que têm caixa SQL e o estado diz isso.

## Interface

- `web/js/sql_view.js`: a aba. `setView` em `main.js` ganha a visão `sql`; `index.html`, o terceiro botão.
- `web/css/sql.css`: novo arquivo, só com seletores da aba.
- Trilha: linhas calculadas por faixas, em SVG, com alocação automática. O algoritmo é a maior incerteza da interface: precisa ser testado com muitas ramificações. Como reserva, cada linha mostra só o caminho selecionado.
- Fluxo completo: reaproveita as classes das caixas sem alterar `canvas.js`. Se for preciso extrair uma função de desenho, a mudança não pode alterar o Designer.
- Destaque de sintaxe: leve, sem CDN, porque o programa funciona sem internet. Desligar ligaduras da fonte no código, para `>=` não virar `≥`.
- O item "Ver SQL" entra em `canvas.js`, no menu da caixa.

## Auditoria preliminar das ferramentas

Prevista pela leitura do código e a ser confirmada pelos testes de equivalência.

| Ferramenta | Tradução | Classe | Atenção |
|---|---|---|---|
| Input Data | `read_csv`, `read_parquet`, `read_json`, Excel | Traduz | Encoding: `latin-1` é nativo, mas difere de CP1252 em 0x80–0x9F. Excel exige extensão do DuckDB, e o programa funciona sem internet. |
| Database Input | Texto da consulta | Ressalva | Dialeto do banco de origem; não roda no DuckDB. |
| Text Input | `VALUES` | Traduz | Leva dados para o código (RF-2031). |
| Browse | Passa adiante | Traduz | |
| Output Data | Comentário e `COPY` de exemplo | Traduz | Nunca executado. |
| Select | Lista de colunas e macros de conversão | Traduz | `engine/convert.py` precisa de equivalente exato. |
| Filter | `WHERE`; F com `NOT` | Traduz | Nulos na saída F. |
| Formula | `transpile` em sequência | Traduz | Colunas das fórmulas anteriores; `target=existing` mantém a posição. |
| Data Cleansing | `TRIM`, `REGEXP_REPLACE`, `COALESCE` | Ressalva | Maiúsculas por palavra podem divergir de `to_titlecase`. |
| Unique | `ROW_NUMBER` | Ressalva | "Fica com o primeiro" depende da ordem. |
| Sort | `ORDER BY` | Traduz | Posição dos nulos; ordem não se mantém entre etapas. |
| Sample | `LIMIT`, janelas | Ressalva | Aleatório com semente não reproduz o Polars: não é comparável. |
| Record ID, Running Total | Janelas | Ressalva | Dependem da ordem. |
| Text To Columns | `string_split` | Traduz | Número de colunas. |
| Join | `INNER JOIN`; L e R com `NOT EXISTS` | Traduz | `keys_mode`, prefixo, Colunas do J. |
| Summarize | `GROUP BY` | Traduz | Moda com empate, `first`/`last` e concatenar dependem de regras próprias. |
| Union | `UNION ALL`, `BY NAME` | Traduz | Coluna de origem. |
| Cross Tab | `PIVOT` | Ressalva | Colunas vêm dos dados. |
| Transpose | `UNPIVOT` | Traduz | |
| Append Fields | `CROSS JOIN` | Traduz | |
| SQL | A própria consulta | Traduz | Renomear `input_1` e `input_2`; regra de segurança da conferência. |
| Chart, KPI, Table, Venn | Consulta por trás do visual | Ressalva | Precisa bater com a agregação real de `nodes/bi.py`. |
| Train/Test Split, AutoML, Predictor | Nenhuma | Sem tradução | Gera Parcial. |

## Riscos

- **Tamanho:** é a maior versão até agora. Se preciso, entra primeiro o que tem mais uso (Input, Select, Filter, Formula, Cleanse, Summarize, Join, Union, Sort), e o resto aparece como "sem tradução", de forma honesta, até a versão seguinte.
- **Funções da Formula:** as macros são do DuckDB. Os dialetos do Fabric serão o maior trabalho da versão seguinte.
- **Empacotamento:** nenhuma dependência nova é necessária nesta versão. O sqlglot fica para quando houver outros dialetos.
