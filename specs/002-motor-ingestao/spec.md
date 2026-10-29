# Spec 002 — Motor de ingestão de dados

Status: Implementada · Criada: 2026-10-28

## Contexto

O nó Input Data só lia arquivos já presentes em `storage/datasets`, assumindo
CSV com vírgula e UTF-8. Arquivos brasileiros comuns (CSV com `;`, decimal com
vírgula, Latin-1/CP1252, planilhas Excel) falhavam ou eram lidos errado, sem que
o usuário pudesse ver o problema antes de rodar o fluxo. O upload aceitava
qualquer nome de arquivo (path traversal) e o campo `custom_path` permitia ler
qualquer arquivo do servidor.

## Histórias de usuário

- **H1** — Como analista, quero arrastar um arquivo para a aplicação e vê-lo
  imediatamente como tabela, com tipos de coluna detectados.
- **H2** — Como analista, quero que delimitador e encoding sejam detectados
  automaticamente, mas poder corrigi-los e ver o preview mudar na hora.
- **H3** — Como analista, quero escolher a aba de uma planilha Excel.
- **H4** — Como analista, quero criar uma tabela pequena (de-para, parâmetros)
  digitando direto numa grade, sem escrever JSON.
- **H5** — Como analista, quero arrastar um dataset da lista para o canvas e
  obter um nó Input Data já configurado.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-201 | Formatos suportados: CSV/TXT/TSV, Excel (`.xlsx`, `.xls`), Parquet, JSON (array), NDJSON/JSONL, Arrow IPC/Feather. |
| RF-202 | Detecção automática de formato (extensão + conteúdo para JSON vs NDJSON). |
| RF-203 | Detecção automática de encoding (UTF-8, UTF-8 com BOM, fallback CP1252) e delimitador (`, ; \t |`). |
| RF-204 | Opções de leitura editáveis: formato, delimitador, encoding, cabeçalho, linhas a pular, decimal com vírgula, valores nulos, aba do Excel, linhas para inferência de tipo, parse de datas, limite de linhas. |
| RF-205 | `POST /api/datasets/{nome}/preview` devolve opções efetivamente usadas (após autodetecção), abas disponíveis, esquema (nome, tipo) e as primeiras N linhas. |
| RF-206 | Upload (`POST /api/datasets`) valida extensão e tamanho máximo (`PRODATA_MAX_UPLOAD_MB`), sanitiza o nome, não sobrescreve sem `overwrite=true`, e grava de forma atômica. |
| RF-207 | `GET /api/datasets` lista nome, formato, tamanho e data de modificação; `DELETE /api/datasets/{nome}` remove. |
| RF-208 | Todo caminho de dataset é resolvido dentro do diretório de dados; qualquer tentativa de sair dele retorna 400. |
| RF-209 | O nó Input Data usa as mesmas opções e o mesmo leitor do preview (o que se vê é o que se lê). |
| RF-210 | O nó Text Input é editado em uma grade (adicionar/remover linhas e colunas, colar do Excel) e infere tipos numéricos. |
| RF-211 | A assinatura do arquivo (tamanho + mtime) entra no fingerprint do nó, invalidando o cache quando o arquivo muda. |

## Critérios de aceite

- CSV com `;`, decimal com vírgula e CP1252 é lido com acentos e números corretos
  sem nenhuma configuração manual.
- Upload de `../../evil.csv` é salvo como `evil.csv` dentro de `storage/datasets`.
- Preview de 50 linhas de um CSV de 100 MB responde em menos de 1 s (leitura
  limitada por `n_rows`).
- Excel com 2 abas lista ambas e lê a escolhida.
