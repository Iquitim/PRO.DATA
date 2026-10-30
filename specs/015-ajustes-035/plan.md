# Plano 015

## Dashboard (RF-1501, RF-1502)

- `CardFormat.subtitle` (texto; vazio = automático).
- `ChartFormat.labels: dict[str, str]` (renomear séries/categorias/conjuntos; widget
  `rename_labels` listando os nomes atuais) e `legend_position: top | bottom`. `show_legend`
  passa a valer para todos os gráficos com legenda.
- O front aplica o mapa de nomes ao widget antes de desenhar (`relabel(w, labels)`), então eixo,
  legenda, tooltip e modo tabela mudam juntos. Cores por categoria continuam ligadas ao nome
  original (o dado), não ao texto exibido.

## Venn (RF-1503)

- `GET /api/results/{fluxo}/{nó}/{saída}/values?column=&limit=` → valores distintos com contagem
  (`results.distinct_values`, até 500, ordem por frequência).
- Widget `column_values` (`ui(widget="column_values", source="group_column", max_items=3)`):
  pede os valores da entrada da caixa via `ctx.values(coluna)`, mostra chips marcáveis com busca.

## Explicações visuais (RF-1504)

- `tool(..., explainer="crosstab" | "transpose" | "join")` → `describe()` publica `explainer`.
- `explainers.js`: um desenho por ferramenta, em HTML (tabelas mini com setas). Dados: amostra da
  entrada (`api.results` da saída ligada, 200 linhas) e a configuração; sem execução, um exemplo
  fixo com os nomes das colunas configuradas. Cálculo da amostra no front (só ilustração; o
  resultado real é o do motor). `data-link` liga origem e destino para o destaque ao passar o mouse.
- Join: contagens L/J/R vêm do resultado da execução; clicar abre a saída nos Resultados.
- Constituição III: é um widget especializado reutilizável, declarado pela ferramenta, não um
  formulário escrito à mão.

## Output Data (RF-1505, RF-1507)

- `format` padrão `excel`. Novos campos (só para Excel): `sheet_name` ("Dados"), `if_exists`
  (`replace` | `add_sheet`).
- `add_sheet` com arquivo existente: `openpyxl` abre o arquivo, remove a planilha de mesmo nome
  (mantendo a posição), escreve cabeçalho + linhas e salva por arquivo temporário + `os.replace`.
  Senão: `write_excel(worksheet=...)`. Nova dependência: `openpyxl`.
- Nome de planilha: 1–31 caracteres, sem `[ ] : * ? / \`.

## Porta fixa (RF-1506)

- `desktop._choose_port()`: tenta `PREFERRED_PORT = 47615`; se ocupada (outra instância),
  usa uma livre e registra no log que as preferências desta janela ficam separadas.

## Formula (RF-1508, RF-1509)

- `FormulaItem.target: new | existing`, `existing: str` (widget `column`). O motor escreve em
  `existing` quando o alvo é uma coluna existente; `with_columns` mantém a posição.
- Funções novas como macros DuckDB em `ALTERYX_FUNCTIONS` (ou repasse de funções nativas, só
  documentadas). Unidades de data aceitam português (dia, mês, ano, semana). `FormatNumber`
  usa o padrão brasileiro (1.234,56). Exemplos validados pelo teste existente do catálogo.
