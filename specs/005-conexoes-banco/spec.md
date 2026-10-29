# Spec 005 — Conexões com bancos de dados (leitura)

Status: Implementada · Criada: 2026-10-29

## Contexto

A aba Dados aceita arquivos enviados, mas dados corporativos costumam estar em
bancos relacionais. O analista precisa ler tabelas ou o resultado de consultas
SQL de PostgreSQL e SQL Server diretamente no fluxo, sem exportar arquivos.

## Decisões do usuário

- Bancos nesta entrega: **PostgreSQL** e **SQL Server**.
- Senhas: **Gerenciador de Credenciais do Windows** (via `keyring`).
- Escopo: **somente leitura**.

## Histórias de usuário

- **H1** — Como analista, quero cadastrar uma conexão (host, porta, banco,
  usuário, senha), testá-la e reutilizá-la em vários fluxos.
- **H2** — Como analista, quero navegar pelas tabelas de uma conexão, ver uma
  prévia e adicionar a tabela ao fluxo com um clique.
- **H3** — Como analista, quero escrever uma consulta SQL e usar o resultado
  como entrada do fluxo.
- **H4** — Como responsável pela segurança, quero que nenhuma senha seja gravada
  em arquivo do projeto nem devolvida pela API.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-501 | Conexões têm id, nome, tipo (`postgres`, `mssql`), host, porta, banco, usuário e opções de TLS; são salvas em `storage/connections.json` **sem senha**. |
| RF-502 | A senha é guardada no cofre do sistema (`keyring`, serviço `PRODATA`), nunca em JSON, workflow, log ou resposta da API. A API informa apenas `has_password`. |
| RF-503 | `POST /api/connections/{id}/test` executa `SELECT 1` e devolve sucesso ou a mensagem do driver (sem a senha). |
| RF-504 | `GET /api/connections/{id}/tables` lista tabelas e views fora dos esquemas de sistema. |
| RF-505 | `POST /api/connections/{id}/preview` devolve esquema e até N linhas de uma tabela ou consulta. |
| RF-506 | Ferramenta **Database Input** (`io.database_input`): conexão + tabela **ou** consulta SQL + limite opcional. |
| RF-507 | Somente leitura: a consulta deve ser uma única instrução `SELECT`/`WITH`; no PostgreSQL a sessão é aberta com `default_transaction_read_only = on`. |
| RF-508 | Por padrão o Database Input reconsulta o banco a cada execução; a opção "Reaproveitar resultado" permite usar o cache incremental. |
| RF-509 | UI: seção "Conexões" na aba Dados (nova, editar, testar, excluir, explorar tabelas, adicionar ao fluxo) e widgets de conexão/tabela no Inspector. |
| RF-510 | Antes de chamar o driver, uma checagem TCP (5 s) acusa servidor inacessível com mensagem clara (host, porta, VPN/firewall), em vez de esperar ~30 s pelo pool do driver. |

## Critérios de aceite

- Após salvar uma conexão com senha, `connections.json` não contém a senha e a
  credencial aparece no Gerenciador de Credenciais do Windows.
- `DELETE` da conexão remove também a credencial.
- Consultas `DELETE`, `UPDATE`, `DROP` ou com duas instruções são recusadas com
  mensagem clara, antes de chegar ao banco.
- Falha de conexão mostra a mensagem do driver no nó e no teste de conexão.
