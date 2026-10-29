# Spec 003 — Workbench: interface de trabalho

Status: Implementada · Criada: 2026-10-28 · **Layout (RF-301) revisado pelas specs 004 e 006**

## Contexto

A interface original funcionava como demonstração: emojis como ícones, textos
de marketing espalhados pela tela, formulários de texto livre para nomes de
coluna, nenhum feedback de erro, nenhuma forma de salvar/abrir fluxos, e um
único arquivo JS de 1.200 linhas com handlers inline que redesenhava o DOM
inteiro a cada movimento do mouse.

## Histórias de usuário

- **H1** — Como analista, quero encontrar uma ferramenta digitando seu nome.
- **H2** — Como analista, quero configurar nós escolhendo colunas em listas
  (vindas do nó anterior), não digitando nomes.
- **H3** — Como analista, quero desfazer/refazer alterações no fluxo.
- **H4** — Como analista, quero ver erros de execução no nó e em uma notificação.
- **H5** — Como analista, quero salvar e reabrir fluxos.
- **H6** — Como analista, quero paginar e ordenar os resultados de qualquer porta.
- **H7** — Como analista, quero ajustar o tamanho dos painéis.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-301 | Layout: barra superior, painel esquerdo (Ferramentas / Dados), canvas, Inspector à direita, painel de resultados inferior redimensionável e recolhível. |
| RF-302 | Paleta de ferramentas com busca e agrupamento por categoria; clique adiciona ao centro, arrastar solta na posição (ou no meio de um fio). |
| RF-303 | Inspector gerado a partir de `config_fields` do catálogo, com widgets: texto, número, toggle, select, coluna, colunas, expressão (com validação e inserção de colunas), SQL, template, dataset, lista de itens, grade (Text Input), seletor de colunas (Select). |
| RF-304 | Canvas: pan, zoom no cursor, "ajustar à tela", arrastar nós, conectar portas, excluir fio selecionado, menu de contexto do nó (executar até aqui, duplicar, desabilitar, excluir). |
| RF-305 | Desfazer/refazer (Ctrl+Z / Ctrl+Shift+Z) para toda alteração estrutural e de configuração. |
| RF-306 | Salvar (Ctrl+S), abrir e criar novo fluxo; indicador de alterações não salvas. |
| RF-307 | Resultados: abas Dados / Perfil / Log; seleção de porta; busca; ordenação por coluna; paginação. |
| RF-308 | Notificações (toasts) para erros de API e resumo de execução. |
| RF-309 | Dashboard (BI) com cartões KPI e gráficos SVG (barras, barras horizontais, linha, rosca) com tooltip e alternância para tabela. |
| RF-310 | Tema claro/escuro seguindo o sistema, com alternância persistida. |
| RF-311 | Ícones SVG consistentes; nenhum emoji na interface. |

## Critérios de aceite

- Arrastar um nó com 30 nós na tela não recria os elementos dos outros nós.
- Configurar o Join escolhendo as chaves em selects populados pelo esquema de
  L e R.
- Erro de API exibe toast com a mensagem do servidor.
- Interface navegável por teclado nos controles de formulário, com foco visível.
