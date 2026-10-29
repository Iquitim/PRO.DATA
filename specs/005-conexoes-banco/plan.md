# Plano 005

## Pacote `prodata.connectors`

| Módulo | Responsabilidade |
|--------|------------------|
| `models.py` | `Connection` (Pydantic, sem campo de senha), `ConnectionInfo` (+ `has_password`) |
| `secrets.py` | `SecretStore` (protocolo), `KeyringSecretStore` (cofre do SO), `MemorySecretStore` (testes) |
| `store.py` | `ConnectionStore`: CRUD em `storage/connections.json` + senha no `SecretStore` |
| `sql.py` | montagem de URI por dialeto, validação somente-leitura, `read_sql`, `list_tables`, limite por dialeto |

## Driver

`connectorx` com `return_type="arrow"` → `pl.from_arrow`. Lê PostgreSQL
(protocolo binário) e SQL Server (TDS nativo, sem ODBC). URI montada com
`urllib.parse.quote` para usuário/senha; a mensagem de erro do driver é
higienizada para remover a senha.

| Dialeto | URI | Limite | Identificador |
|---------|-----|--------|---------------|
| postgres | `postgresql://u:p@h:5432/db?sslmode=…&connect_timeout=10` | `SELECT * FROM (q) _q LIMIT n` | `"schema"."tabela"` |
| mssql | `mssql://u:p@h:1433/db?encrypt=…&trust_server_certificate=…` | `SELECT TOP n * FROM (q) _q` | `[schema].[tabela]` |

## Integração com o motor

- `NodeContext.connections` (opcional) dá acesso ao `ConnectionStore`.
- `WorkflowRunner(..., connections=...)`.
- Fingerprint do Database Input inclui um carimbo de tempo quando
  "Reaproveitar resultado" está desligado (força reconsulta).

## API

`GET/PUT/DELETE /api/connections[/{id}]`, `POST /{id}/test`,
`GET /{id}/tables`, `POST /{id}/preview`. A senha só entra no `PUT` e nunca sai.

## Configuração

`PRODATA_SECRETS_BACKEND=keyring|memory` (testes usam `memory`).

## Riscos

- Sem banco real disponível no ambiente de desenvolvimento desta entrega: a
  integração com servidores é coberta por testes com leitor simulado e por um
  teste de falha de conexão real (host inexistente).
- SQL Server não aceita `ORDER BY` em subconsulta sem `TOP`: o limite de preview
  envolve a consulta; documentado na UI.
