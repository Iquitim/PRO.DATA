# Spec 013 — Ferramentas essenciais, Select completo e canvas responsivo

Status: Implementada · Criada: 2026-10-29

## Contexto

- A ferramenta Select não tinha "selecionar tudo / desmarcar tudo"; com dezenas de
  colunas, manter só algumas exigia desmarcar uma a uma.
- As ferramentas de IA generativa (Prompt Column, Text Extractor) apenas simulavam
  um modelo de linguagem com regras locais. Decisão do usuário: **remover** e manter
  só Machine Learning.
- Comparando com as ferramentas mais usadas do Alteryx, faltavam operações básicas
  de reformatação: tabela dinâmica, despivotar, dividir texto, numerar linhas, soma
  acumulada e anexar parâmetros.
- Arrastar no canvas às vezes travava. Medição: arrastar uma caixa solta custava
  5,7 ms por movimento (38 ms com a CPU 4x mais lenta, como num notebook corporativo),
  mais que o intervalo entre eventos do mouse — a caixa ficava para trás do cursor.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1301 | Select: botões **Todas**, **Nenhuma** e **Inverter**, caixa de marcar no cabeçalho (com estado parcial) e contador "N de M colunas mantidas". |
| RF-1302 | Prompt Column e Text Extractor saem do programa (código, catálogo, categoria "IA generativa", dados de exemplo dos chamados). A demonstração salva que ainda as use é atualizada ao abrir. |
| RF-1303 | **Cross Tab**: valores de uma coluna viram cabeçalhos, agrupando por colunas escolhidas; soma, média, contagem, mínimo, máximo, primeiro ou juntar textos; no máximo 500 colunas novas. |
| RF-1304 | **Transpose**: colunas escolhidas (ou todas exceto as chaves) viram pares nome/valor; tipos diferentes viram texto. |
| RF-1305 | **Text To Columns**: divide uma coluna por um separador em novas colunas (no lugar da original) ou em novas linhas; remove espaços; mantém a original se pedido. |
| RF-1306 | **Record ID**: numera as linhas a partir de um valor, como primeira ou última coluna. |
| RF-1307 | **Running Total**: soma acumulada de colunas numéricas, opcionalmente recomeçando a cada grupo. |
| RF-1308 | **Append Fields**: anexa as colunas de [S] a todas as linhas de [T] (produto cartesiano), com prefixo para nomes repetidos e limite de 10 milhões de linhas. |
| RF-1309 | Canvas: o encaixe de caixa solta sobre uma ligação calcula os pontos pela fórmula da curva (sem geometria SVG); os movimentos do mouse são processados uma vez por quadro (o mais recente); a posição da tela é salva só quando o movimento termina. |

## Critérios de aceite

- Select com 10 colunas: "Nenhuma" → 0 de 10; marcar uma → cabeçalho parcial; "Todas" → 10 de 10.
- Com a CPU 4x mais lenta, arrastar uma caixa solta mantém o quadro p95 em ~16,7 ms
  (antes: 32,9 ms) e o encaixe sobre a ligação continua funcionando.
