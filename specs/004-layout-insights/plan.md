# Plano 004

## Layout (`index.html`, `app.css`)

```text
┌───────────────┬─────────────────────────────┬──────────────────┐
│ Ferramentas │ │                             │ Dados|Perfil|Log │
│ Dados       │ │           canvas            │                  │
│ Configurar  │ │                             │   resultados     │
│               ├─────────────────────────────┤  (altura total)  │
│               │  insights: KPIs · gráficos  │                  │
└───────────────┴─────────────────────────────┴──────────────────┘
```

CSS custom properties: `--left-w` (300), `--right-w` (460), `--dock-h` (280).

## Módulos

- `inspector.js` passa a renderizar dentro da aba Configurar; `main.js` troca de
  aba no evento `selection`.
- `canvas.js`: `NODE_W = 188`, altura `max(56, (portas + 1) · 18)`; legenda
  dentro do cartão; pílulas filtradas pelo nó selecionado; `fitView` com zoom
  mínimo 1,0 (ancora no início do fluxo se não couber).
- `charts.js` (novo): funções de gráfico extraídas de `dashboard.js`, agora com
  altura parametrizada; usadas pelo Dashboard e pelos insights.
- `insights.js` (novo): monta os cartões a partir de `bi_widgets` e busca as
  saídas dos Summarize em `/api/results` (até 30 linhas, ordenadas pelo valor).
- `results.js`: barra em duas linhas para caber no painel lateral.

## Dados de demonstração

Coordenadas do fluxo de demonstração e dos modelos do assistente refeitas para
cartões de 188 px (colunas a cada 248 px).
