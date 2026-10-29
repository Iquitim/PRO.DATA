# Plano 006

## Painéis (`layout.js`, novo)

- Estado `{ left, right, bottom }` → id do painel ou `null`; salvo em
  `localStorage` (`prodata.panels.v1`).
- Os painéis são elementos fixos (`#explorerPanel`, `#results`, `#insights`)
  movidos com `appendChild` entre os contêineres de posição (`#slot-left`,
  `#slot-right`, `#slot-bottom`) — o estado interno de cada painel é preservado.
- Classes no `body` (`slot-left-empty`, …) recolhem a coluna/linha e a alça de
  redimensionamento correspondentes.
- Cada painel recebe controles (alça arrastável + menu) no próprio cabeçalho.
  Arraste via HTML5 DnD (`application/x-prodata-panel`); durante o arraste, uma
  camada mostra os três alvos.
- Evento `layout` permite que o painel de insights se redesenhe na orientação
  certa.

## Contêineres (`canvas.js`, `actions.js`)

- `addContainer`, `updateContainer`, `removeContainer`, `fitContainer` em
  `actions.js` (via `mutate`).
- Gestos novos no canvas: `container-move` e `container-resize` (com
  `checkpoint/commit`, um passo de desfazer por gesto).
- `store.selection.containerId`.
- Título editável inline; menu de contexto com cores (paleta fixa de 7).
