# Plano 002 — Motor de ingestão

## Módulos

- `ingestion/options.py` — `ReadOptions` (Pydantic), compartilhado entre o nó
  Input Data, o endpoint de preview e os testes.
- `ingestion/detect.py` — `detect_format`, `detect_encoding`, `sniff_delimiter`.
  Lê no máximo 64 KiB do início do arquivo.
- `ingestion/readers.py` — `read_table(path, options, n_rows=None)` e
  `inspect_file(path, options, preview_rows)`. Um leitor por formato,
  despachado por dicionário.
- `ingestion/datasets.py` — `DatasetStore`: `list`, `save_upload`, `delete`,
  `resolve`, `signature`. Usa `resolve_inside(base, name)` para confinamento.

## Encoding

Polars só lê UTF-8. Para CP1252/Latin-1 o arquivo é decodificado em memória e
reencodado para UTF-8 antes do `read_csv`. Para preview, apenas os primeiros
bytes necessários são decodificados.

## Contratos HTTP

| Método | Rota | Corpo / Query | Resposta |
|--------|------|---------------|----------|
| GET | `/api/datasets` | — | `DatasetInfo[]` |
| POST | `/api/datasets` | multipart `file`, `overwrite` | `DatasetInfo` |
| POST | `/api/datasets/{name}/preview` | `ReadOptions`, `?rows=50` | `DatasetPreview` |
| DELETE | `/api/datasets/{name}` | — | 204 |

## UI (ver spec 003)

Painel "Dados" com dropzone, lista de datasets e diálogo de preview com as
opções de leitura à esquerda e a grade à direita. "Usar no fluxo" cria um nó
Input Data com as opções escolhidas.
