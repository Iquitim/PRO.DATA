# Plano 014

## Modelo de dados (domínio)

`Workflow.dashboard: Dashboard` (opcional; ausente = layout automático, RF-1408).

```
Dashboard
  page: { size: "16:9" | "a4-landscape" | "a4-portrait" | "free", height?: int, background: str }
  items: list[DashItem]          # ordem = camada (z)
  hidden: list[str]              # node_ids de visuais fora da página (RF-1407)

DashItem
  id, kind: "visual" | "text" | "image" | "shape"
  x, y, w, h: int                # px da página
  node_id?: str                  # kind=visual → caixa de BI
  format: dict                   # validado pelo modelo de formato do tipo (abaixo)
  content?: str                  # texto; imagem como data URI (≤ 1 MB, só png/jpeg/svg+xml)
```

- O validador de `Workflow` remove itens `visual` cujo `node_id` não existe (o
  comportamento da spec 010 vira regra do domínio).
- SVG de imagem é saneado no servidor (remove `<script>`, `on*=`, `href` externos)
  antes de ser aceito. É conteúdo vindo do usuário e será embutido na página.

## Formatação declarativa (constituição III)

- `prodata/dashboard/formats.py`: modelos Pydantic `CardFormat`, `ChartFormat`,
  `KpiFormat`, `TableFormat`, `TextFormat`, `ImageFormat`, `ShapeFormat`, com `ui()`
  (grupos, `show_if`, novos widgets `color` e `palette`).
- `GET /api/dashboard/formats`: os JSON Schemas. O painel Formato reutiliza o gerador
  de formulários do Inspector (`forms`), sem formulário escrito à mão.
- Formatar não executa o fluxo: o formato fica no item, e os dados no resultado do nó
  (RF-1410).

## Motor (BI)

- `bi.chart`: `series_column`, `chart_type` amplia para `stacked`, `grouped`,
  `stacked100`, `hbar_stacked`, `area`, `area_stacked`, `scatter`, `funnel`. O widget
  passa a ter `series: [{label, values: {serie: valor}}]` quando há segunda dimensão
  (mantém o formato atual quando não há). Dispersão devolve `points` amostrados com
  semente fixa.
- `bi.kpi_card`: `compare: none | target | previous_period`, `target`, `date_column`,
  `period`, `higher_is_better`, `sparkline_periods`. Calcula `value`, `previous`,
  `delta`, `delta_pct`, `trend: [{period, value}]` no motor (testável sem interface).
  Medidor = KPI com `display: gauge` (usa `target` e `gauge_max`).
- `bi.chart` com `chart_type="pareto"` (um só eixo Y, acumulado com rótulos diretos): ordena por valor decrescente e calcula
  `cum_pct` por categoria no motor. "Outros" entra no fim, para o acumulado fechar em
  100%. `pareto_threshold` (padrão 0,8) marca `highlight` nas categorias até o corte.
- `bi.venn` (nova): `mode: flags | key_group`. Em `flags`, 2 ou 3 colunas são
  convertidas para booleano; em `key_group`, `key_column`, `group_column` e
  `groups: list[str]` (2–3) com chaves distintas. Devolve `sets` e `regions`: as 3 ou 7
  regiões exclusivas com `count` e `pct`. A geometria de 2 conjuntos é resolvida no
  motor: raios pela área e distância entre centros por bisseção da área da lente, para
  bater com a interseção. Com 3 conjuntos, a geometria é fixa no front.
- `bi.table` (nova): `columns`, `totals`, `max_rows ≤ 500`.
- Os widgets ganham `version: 2`. O frontend aceita os dois formatos.

## Frontend

- `dashboard.js` passa a ser só o orquestrador. Módulos novos:
  - `dash_canvas.js`: página escalada, modos Visualizar e Editar, arrastar e
    redimensionar com encaixe e guias, seleção múltipla, setas. Mesmo padrão de
    gestos do `canvas.js` (rAF coalescido, captura de ponteiro, só no item).
  - `dash_format.js`: painel Formato (formulário gerado + widgets de cor e paleta,
    com aviso de contraste calculado no cliente pela mesma fórmula do validador de
    paleta).
  - `dash_items.js`: render de texto, imagem e forma.
  - `charts.js`: novos renderizadores (empilhado, agrupado, multi-linha, área,
    dispersão, funil, medidor, sparkline), todos SVG puro, com legenda e rótulos
    opcionais. `renderChart(type, data, w, h, format)`.
- Mutações do layout via `mutate()` do store: entram no histórico e no estado "não
  salvo" sem código novo (RF-1405).
## Organizar e layouts prontos (RF-1460..RF-1463)

- `prodata/dashboard/layouts.py`: função pura `arrange(items, page, template,
  obstacles)` → novas posições, testada com pytest (o projeto não tem Node). A rota
  `POST /api/dashboard/arrange` devolve, numa chamada, o resultado de todos os layouts.
  Assim a galeria desenha as miniaturas e aplica o escolhido sem nova ida ao servidor.
- Tamanho base por tipo: big number 2×1 células; rosca, medidor e Venn 1×1
  (quadrado); colunas, barras, Pareto e dispersão 2×1, ou 3×1 com mais de 12
  categorias; linha, área e tabela com largura total ou 3×1. Grade de 12 colunas, com
  margem e espaçamento de 16 px, alinhada à grade de 8 px.
- Layouts prontos: cada um é uma lista de "faixas" (topo de KPIs, colunas, destaque,
  lateral) preenchida na ordem de leitura atual (ordena por `y` e depois `x`).
- Automático: ordem de leitura + empacotamento por linhas (*shelf packing*). Cada linha
  é esticada para fechar a largura, o que evita buracos.
- Obstáculos (textos, imagens, formas) viram retângulos ocupados que as faixas
  contornam. As miniaturas da galeria usam a mesma função, desenhada num SVG pequeno.
- Aplicação via um único `mutate()` (um passo de desfazer).
- O layout da migração (RF-1408) é `arrange(..., template="kpis-top-2")`, aplicado
  pelo servidor ao carregar um fluxo sem `dashboard`.

## Exportação (PNG)

- **Render de exportação**: a página é desenhada num contêiner fora da tela, no tamanho
  real (sem escala), em modo Visualizar. Todos os visuais já são SVG ou HTML simples.
- **PNG** (página e visual individual): o DOM vira um SVG `<foreignObject>` com o CSS
  e as fontes Open Sans embutidas (data URI), é desenhado num `<canvas>` 2× e salvo
  com `toBlob`. Não precisa de biblioteca externa. Risco: imagens externas mancham o
  canvas. Mitigação: as imagens já ficam como data URI (RF-1441).
- **Gravação** (RF-1452): no app, `DesktopApi.save_png(nome, base64)` abre "Salvar
  como" com filtro PNG e grava os bytes. No navegador, o arquivo é baixado via `<a
  download>`. Ver a emenda à constituição abaixo.

## Constituição

Emenda 1.3.0 no princípio IV: a lista de "destinos escolhidos explicitamente pelo
usuário" passa a incluir imagens exportadas do dashboard (`.png`), com as mesmas
condições: caminho absoluto, diretório existente, extensão fixa e nome saneado.

## Riscos

| Risco | Mitigação |
|-------|-----------|
| `foreignObject` não renderiza alguma propriedade CSS no canvas | Teste visual automatizado (Playwright) comparando PNG exportado e captura da tela |
| Venn de 3 conjuntos com áreas proporcionais exige otimização numérica e nem sempre tem solução exata | Na v0.3 só 2 conjuntos são proporcionais; com 3, a interface diz que os círculos são ilustrativos (constituição VI) |
| Layout pronto ficar ruim com muitos ou poucos visuais | Miniatura mostra o resultado antes de aplicar; desfazer em um passo |
| Arquivos de fluxo maiores por causa das imagens | Limite de 1 MB por imagem, aviso de tamanho total |
| Layout quebrar ao mudar o tamanho da página | Itens fora da página são trazidos para dentro e avisados; não são apagados |
| Regressão no painel de insights, que usa `chartCard` | Testes da spec 004 reexecutados e `chartCard` mantido como adaptador |
