# Spec 006 — Painéis reposicionáveis e contêineres editáveis

Status: Implementada · Criada: 2026-10-29 · Revisa: spec 004 (RF-401) · **Defeito do RF-602 corrigido na spec 007 (RF-701)**

## Contexto

O layout da spec 004 fixou cada painel em um lugar (ferramentas/configuração à
esquerda, resultados à direita, gráficos embaixo). Usuários diferentes preferem
arranjos diferentes, e às vezes querem esconder um painel para ganhar espaço.
Além disso, os contêineres de etapa ("1 · Ingestão e preparação") existiam no
arquivo do fluxo, mas não podiam ser criados nem editados na interface.

## Histórias de usuário

- **H1** — Como analista, quero arrastar um painel para outra posição (esquerda,
  direita, embaixo) e o arranjo deve ser lembrado.
- **H2** — Como analista, quero ocultar e reexibir qualquer painel.
- **H3** — Como analista, quero criar uma caixa de etapa, dar nome e cor, movê-la
  levando os nós de dentro, redimensioná-la e excluí-la.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-601 | Existem três posições (esquerda, direita, embaixo do canvas) e três painéis: Ferramentas/Dados/Configurar, Resultados, Gráficos e resumos. Cada posição tem no máximo um painel. |
| RF-602 | Cada painel tem uma alça de arraste; ao arrastar, as três posições aparecem como alvos. Soltar em posição ocupada troca os painéis de lugar. |
| RF-603 | Cada painel tem um menu com "Mover para…" e "Ocultar" (alternativa ao arraste, acessível por teclado). |
| RF-604 | Menu "Painéis" na barra superior: mostrar/ocultar cada painel e restaurar o arranjo padrão. Painel reexibido ocupa uma posição livre. |
| RF-605 | Posição vazia não ocupa espaço. O arranjo é salvo no navegador. |
| RF-606 | Os painéis se adaptam à posição: gráficos e resumos empilham na vertical quando estão em uma lateral. |
| RF-607 | Contêineres: criar (barra do canvas, menu de contexto ou atalho `G`), renomear (duplo clique no título), trocar cor, ajustar aos nós de dentro, excluir (mantém os nós). |
| RF-608 | Arrastar o título de um contêiner move ele e os nós cujo centro está dentro dele; a alça do canto inferior direito redimensiona. |
| RF-609 | Contêiner selecionado é destacado; `Delete` o exclui. Todas as operações entram no desfazer/refazer. |

## Critérios de aceite

- Arrastar Resultados para "embaixo" troca de lugar com Gráficos e resumos, e a
  troca persiste após recarregar a página.
- Ocultar os três painéis deixa só o canvas; "Restaurar layout" volta ao padrão.
- Mover o contêiner "1 · Ingestão e preparação" leva os seis nós dele junto;
  `Ctrl+Z` desfaz em um passo.
