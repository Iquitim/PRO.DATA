# Plano 003 — Workbench

## Decisão: ES Modules nativos, sem build

O frontend é servido pelo FastAPI e escrito em JavaScript com ES Modules nativos
(`<script type="module">`), sem bundler. Motivo: zero toolchain Node para rodar
o projeto, depuração direta no navegador, e o tamanho atual (~3 mil linhas) não
justifica React/Vite. Se a UI crescer além disso, migrar para Vite + TypeScript
é direto, pois os módulos já são isolados.

## Módulos (`src/prodata/web/js/`)

| Módulo | Responsabilidade |
|--------|------------------|
| `main.js` | bootstrap, atalhos de teclado, ligação entre módulos |
| `api.js` | cliente HTTP; erros viram `ApiError` com mensagem do servidor |
| `store.js` | estado único + eventos (`on/emit`), histórico desfazer/refazer |
| `dom.js` | `h()` para criar elementos, `escapeHtml`, delegação de eventos |
| `icons.js` | ícones SVG (traço 1.75, 24×24) |
| `palette.js` | painel de ferramentas |
| `datasets.js` | painel Dados, upload, diálogo de preview |
| `canvas.js` | render incremental de nós/fios, interações com pointer events |
| `inspector.js` + `fields.js` | formulário gerado a partir de `config_fields` |
| `results.js` | grade com perfil, paginação, ordenação, log |
| `dashboard.js` | KPIs e gráficos SVG |
| `dialogs.js`, `toast.js`, `menu.js` | diálogos, notificações, menu de contexto |

## CSS (`src/prodata/web/css/`)

`tokens.css` (cores, espaçamento, raio, tipografia; claro/escuro),
`base.css`, `layout.css`, `components.css`, `canvas.css`, `grid.css`,
`dashboard.css`. Cores de categoria são dessaturadas e usadas só em ícones e
acentos; texto usa sempre tokens de texto.

## Gráficos

Paleta categórica de referência validada (8 cores, ordem fixa) para rosca;
gráficos de série única usam o azul de destaque. Barras com no máximo 24px,
ponta arredondada de 4px, grade de 1px, tooltip por marca, botão "Tabela".
