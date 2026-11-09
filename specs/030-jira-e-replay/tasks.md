# Tarefas — Spec 030 (versão 0.7)

Cada etapa funciona sozinha e fecha com testes verdes. Etapas visuais começam com telas aprovadas.

## Etapa 0 — Preparação
- [x] Dividir `dashboard.js`, `charts.js` e `fields.js` (RF-3091)
- [x] Teste de comparação com a 0.6.1
- [ ] Conferir no Jira de teste as permissões do token e o histórico em lote; guardar respostas anonimizadas (depende de um token real)
- [x] Jira simulado no repositório

## Etapa 1 — Conexão com o Jira
- [x] Telas aprovadas: Adicionar > Jira e token guiado
- [x] Conexão, cofre, descoberta do endereço, avisos (RF-3001..3006)

## Etapa 2 — Consulta Jira
- [x] Telas aprovadas: escolha de projetos, colunas, filtros e JQL
- [x] Consulta como fonte, tabelas, filtros, prévia (RF-3011..3015)
- [x] Paginação, limites, retomada, conversão de texto, registro (RF-3016..3019)
- [x] Teste de que nenhuma chamada escreve

## Etapa 3 — Atualização incremental
- [x] Guardado local, busca por alteração, releitura completa (RF-3021..3024)

## Etapa 4 — Estado por período
- [x] Tela aprovada: esquema "Como funciona"
- [x] Ferramenta, casos de borda, limite, SQL (RF-3031..3035)

## Etapa 5 — Linha do tempo
- [x] Telas aprovadas: barra de reprodução e modos
- [x] Cálculo no navegador conferido com o motor (RF-3092)
- [x] Linha do tempo, sincronia, filtros, abrir registros (RF-3041..3046)
- [x] Exemplo de demonstração (RF-3048)

## Etapa 6 — Gráficos animados
- [x] Telas aprovadas: corrida de barras, bolhas e Sankey
- [x] Transições e opção de desligar (RF-3051, RF-3055)
- [x] Corrida de barras e bolhas (RF-3052, RF-3053)
- [x] Sankey (RF-3054)

## Etapa 7 — Exportação
- [x] Tela aprovada: GIF
- [x] GIF por gráfico, rótulo e limites (RF-3071..3073, RF-3075)
- [x] HTML com linha do tempo (RF-3074)

## Etapa 8 — Destaques
- [x] Tela aprovada: marcas e critério
- [x] Picos, tendências e valores fora do padrão (RF-3047)

## Etapa 9 — História
- [x] Telas aprovadas: cenas e apresentação
- [x] Cenas, apresentação, rastreabilidade e HTML (RF-3061..3064)

## Etapa 10 — Lições guiadas
- [x] Tela aprovada: passo a passo
- [x] Quatro lições e teste de cada uma (RF-3081..3083)

## Etapa 11 — Fechamento
- [ ] Conferência num Jira Cloud real (depende de um token real)
- [x] Guia, Manual, README, `contexto-ia.md`, imagens nos dois temas e notas (RF-3093)
- [x] Comparação com a 0.6.1, pytest, ruff, mypy, baterias, PDF e executável
