# Plano da spec 033

## Arquitetura

- **Contexto das caixas** (`nodes/base.py`): `NodeContext` ganha quem é a caixa (`workflow_id`, `node_id`), a pasta
  de estado (`state_dir()`), se a execução é automática (`hold`), a assinatura das entradas e três ganchos opcionais:
  `run_subflow`, `subflow_signature` e `secret_key`. O motor continua sem conhecer HTTP.
- **Estado entre execuções**: `<pasta de dados>/estado/<fluxo>/<caixa>/`. Guarda as tabelas do Compare Runs
  (`AAAA-MM-DD.parquet`) e os modelos de ML (`vN.joblib` e `vN.json`). Nunca vai no arquivo do fluxo.
- **Linha de comando** (`cli.py`): `prodata run|list|serve`. Monta os mesmos serviços do servidor, sem FastAPI em
  execução. `prodata-cli.exe` é um segundo executável do mesmo pacote, com console.
- **Subfluxos** (`engine/subflow.py`): o fluxo de origem roda num `WorkflowRunner` próprio, com um ID de cache por
  uso (`sub_<hash>`), para o mesmo subfluxo em dois lugares não misturar resultados. A cadeia de IDs reais impede
  recursão e limita a 5 níveis.
- **Memória do cache** (`engine/cache.py`): `StoredTables` é um `Mapping` que solta as tabelas da memória e as relê
  do Arrow já gravado. O resumo de linhas e colunas fica guardado na entrada, para ler o resumo não trazer a tabela.
- **SQL para o Fabric** (`engine/sql/dialects.py`): conversão bloco a bloco com SQLGlot, depois do `render`. A trilha
  e os blocos não mudam.
- **ODBC** (`connectors/odbc.py`): `pyodbc`, só por DSN. Passa pelo mesmo `ensure_read_only`.

## Contratos

- `POST /api/sql/generate` e `/download`: campo `dialect` (`duckdb`, `spark`, `tsql`). A resposta traz `unverified`.
- `GET /api/catalog`: `cli_command`, a forma de chamar a linha de comando neste computador.
- `Connection.kind = "odbc"` com `odbc_dsn`. `host`, `database` e `user` deixam de ser obrigatórios no modelo e
  passam a ser conferidos por tipo.
- Códigos de saída do `prodata run`: 0, 1 e 2.

## Segurança

- Pasta do Input Folder e modelo de Excel: caminho completo, existente, extensão da lista, somente leitura. A
  abertura protegida lista os dois para quem recebe o fluxo.
- Modelos de ML: `joblib` só é lido da pasta de estado, cujo caminho vem do ID do fluxo e da caixa, nunca da
  configuração. O registro guarda o SHA-256 do arquivo, e arquivo alterado é recusado.
- Arquivo `.modelo` (`nodes/ml_library.py`): formato do skops. Antes de abrir, a lista de tipos do arquivo é comparada
  com a dos modelos que o PRO.DATA treina; fora dela, o arquivo é recusado sem ser carregado. Um pickle nunca é lido
  de um arquivo que veio de fora.
- DSN do ODBC: só o nome, sem `;` nem `=`. A senha vai entre chaves no texto de conexão montado em memória.
- Chave do Mask: gerada no primeiro uso, guardada no cofre, nunca devolvida pela API.
- `prodata run` usa `trust.opened`: não há opção para pular a conferência.

## Riscos

| Risco | Tratamento |
|---|---|
| Tabela fora da memória e arquivo do cache apagado | A caixa seguinte fica "não executou" com pedido de executar de novo, e o cache da origem é descartado. |
| Modelo guardado de outra versão do scikit-learn | Erro com pedido de versão nova. |
| Driver ODBC devolve tipos que o Polars não conhece | A coluna vira texto. |
| SQLGlot não entende um bloco | O bloco fica em DuckDB, com o motivo. |
| Fluxo antigo com Model Trainer | Passa a ter modelo fixo: a primeira execução treina e guarda a v1. |
