# Plano 009

## Constituição

O princípio IV dizia que nenhum caminho vindo do cliente sai do diretório de
dados. RF-905 e RF-907 pedem exatamente isso. Emenda 1.2.0: caminhos absolutos
escolhidos pelo usuário são aceitos **só** para (a) a pasta de destino do
Output Data e (b) arquivos de fluxo `.prodata.json`, com as regras abaixo. Uploads,
datasets e caches continuam confinados.

## Backend

### Fontes: consultas salvas (`prodata.connectors.queries`)

- `SavedQuery(id, name, connection, mode: table|query, table, query, cache_results)`.
- `QueryStore(path)` grava `storage/queries.json` (escrita atômica, lock), sem
  segredos — a senha continua resolvida pela conexão no momento da leitura.
- `read(query, connections, limit)` monta o SQL (`sql.table_query` ou a consulta)
  e chama `sql.read_sql` (que já recusa o que não for SELECT/WITH).
- Rotas `/api/queries`: `GET`, `PUT /{id}`, `DELETE /{id}`, `POST /preview`
  (prévia de uma definição ainda não salva).

### Input Data (`io.input_data`)

- O campo `dataset` aceita o nome de um arquivo ou `sql:<id da consulta>`.
  Nomes de arquivo nunca têm `:` (o saneamento troca), então não há ambiguidade.
- `NodeContext.queries: QueryStore | None`.
- Fingerprint: arquivo → assinatura (tamanho, mtime); consulta → hash da
  definição + carimbo de tempo quando `cache_results` está desligado.
- `show_if` ganha a chave `$source` (`file` | `query`) para esconder as opções
  de leitura de arquivo quando a fonte é uma consulta.
- `io.database_input` continua registrado, com `hidden=True` (sai da paleta e da
  busca rápida, segue no catálogo para fluxos antigos).

### Destinos

- `OutputDataConfig.folder: str = ""`. Vazio → `exports_dir` (confinado, como
  antes). Preenchido → `Path(folder)` deve ser absoluto e um diretório existente;
  o arquivo é `folder / (nome saneado + extensão do formato)`. `extra` passa a ter
  `exported_path` (caminho completo) além de `exported_file`.
- Rotas `/api/files`:
  - `POST /workflow/save {path, workflow}` e `POST /workflow/open {path}`.
    `path` absoluto, terminado em `.prodata.json` (acrescentado se faltar),
    diretório pai existente. Escrita atômica.
- Desktop: `webview.create_window(..., js_api=DesktopApi())` com
  `choose_folder()`, `save_file(suggested)`, `open_file()` (diálogos nativos via
  `FileDialog`) e `reveal(path)` (abre o Explorer na pasta do arquivo). No
  navegador (modo servidor) a UI cai num campo de texto para o caminho.

## Frontend

- `clipboard.js`: `copySelection()`, `cutSelection()`, `paste(at?)`. Formato
  `{ kind: 'prodata/clip', nodes, edges, containers }` em `localStorage`
  (`prodata.clipboard`). Colar gera IDs novos, desloca tudo para o ponto de
  colagem e reconstrói as ligações internas.
- Canvas: botão `.node-delete` no cartão (visível em hover/seleção); menus de
  contexto ampliados; rastreia a última posição do cursor para colar.
- `desktop.js`: detecta `window.pywebview.api` e expõe `chooseFolder`,
  `saveFile`, `openFile`, `reveal`, com fallback para diálogo de texto.
- Topbar: menu do botão Salvar com "Salvar" e "Salvar como…"; diálogo Abrir com
  "Abrir arquivo…" e lista de recentes externos (`localStorage`).
- Aba Dados: seção "Consultas de banco" entre Arquivos e Conexões; editor de
  consulta = explorador da spec 005 com nome + conexão + botões
  "Salvar" / "Salvar e adicionar ao fluxo".
- Widget `dataset`: `<optgroup>` Arquivos / Consultas de banco; o botão de olho
  abre a prévia do arquivo ou o editor da consulta.

## Riscos

- **Gravação fora do diretório de dados**: limitada a extensões fixas, nome
  saneado e diretório já existente; o servidor só escuta em 127.0.0.1 e a API
  JSON exige preflight CORS, então outras origens não conseguem disparar.
- **Fluxos copiados entre máquinas** podem apontar para pastas que não existem:
  o erro do Output Data diz qual pasta falta.
