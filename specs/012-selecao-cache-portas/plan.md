# Plano 012

## Ponto de cache (motor)

- `Node.cache_point: bool`.
- `graph.upstream_signature(workflow, node)`: hash de tipo/config/habilitação da caixa e
  de todas as anteriores + ligações entre elas. Não depende dos dados — é o que permite
  não reler as entradas.
- `ResultCache.freeze/frozen/unfreeze/prune_frozen`: memória + disco em
  `<cache>/<fluxo>/frozen/` (Arrow IPC + `<nó>.json` com assinatura, data e `extra`).
- `WorkflowRunner.run`: pontos de cache com instantâneo válido entregam o instantâneo
  (status `cached`, `extra.cache_point="frozen"`), com fingerprint `frozen:<assinatura>`
  para os descendentes. As caixas necessárias são encontradas andando para trás a partir
  dos sumidouros (ou do alvo) sem atravessar pontos válidos; as demais recebem
  `extra.held=True` (status `cached` se ainda há resultado em memória, senão `skipped`).
  Ponto sem instantâneo válido executa normalmente e é congelado ao final.
- `DELETE /api/cache/{fluxo}/{nó}`: descarta o instantâneo ("Atualizar cache").

## Interface

- `store.selection.nodeIds` + `selectMany`, `isSelected`, `selectedIds`.
- Canvas: `Shift`/`Ctrl`+clique, retângulo com `Shift`+arrastar, arrastar em grupo
  (um passo de desfazer), menu da seleção, selo de cache e estilo "em cache".
- Ações: `alignNodes`, `distributeNodes`, `wrapInContainer`, `moveOutOfContainer`,
  `setDisabled(ids)`; área de transferência aceita conjuntos de caixas.
- Inspector: painel "N caixas selecionadas"; banner do ponto de cache.
- Porta de entrada clicável: `inspect(origem, saída, { via })`; o cabeçalho dos
  resultados mostra a entrada.
