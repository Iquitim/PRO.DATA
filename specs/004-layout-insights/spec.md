# Spec 004 — Layout revisado, nós legíveis e painel de insights

Status: Implementada · Criada: 2026-10-29 · Revisa: spec 003 (RF-301) · **Posições fixas (RF-401) revisadas pela spec 006**

## Contexto

Feedback de uso da spec 003: a tela ainda parecia poluída. Os nós eram ícones
de 52px com legendas miúdas abaixo; cada fio tinha uma pílula de contagem; a
configuração ocupava o lado direito e a tabela de resultados ficava espremida
embaixo do canvas, sem espaço para ver gráficos enquanto se monta o fluxo.

## Histórias de usuário

- **H1** — Como analista, quero ler o nome e o resumo da configuração de cada
  nó sem dar zoom.
- **H2** — Como analista, quero ver a tabela de dados ao lado do canvas, com
  altura total, enquanto edito o fluxo.
- **H3** — Como analista, quero ver, embaixo do canvas, os gráficos e
  indicadores que o fluxo produz, inclusive os resumos (Summarize), sem trocar
  para o Dashboard.
- **H4** — Como analista, quero configurar o nó em um painel à esquerda, que abre
  sozinho quando clico no nó (como no Alteryx).

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-401 | Layout: esquerda com abas Ferramentas / Dados / Configurar; centro com canvas e, abaixo, painel de insights; direita com resultados (Dados / Perfil / Log) em altura total. Os três painéis são redimensionáveis; o de insights é recolhível. |
| RF-402 | Selecionar um nó (clique, criação pela paleta ou pelo painel Dados) ativa a aba Configurar. Sem nó selecionado, Configurar mostra as propriedades do fluxo. |
| RF-403 | Nós são cartões horizontais (188 px) com ícone da categoria, nome e resumo da configuração em uma linha cada; a altura cresce com o número de portas para que nenhuma porta se sobreponha. |
| RF-404 | Pílulas de contagem de linhas aparecem só nos fios do nó selecionado. |
| RF-405 | O painel de insights lista, na ordem do fluxo: KPI Cards, Charts e um gráfico automático para cada Summarize executado (categoria = colunas de agrupamento, valor = primeira agregação numérica; sem agrupamento, vira cartão de indicadores). |
| RF-406 | Clicar em um cartão de insight seleciona o nó de origem e mostra seus dados à direita. |
| RF-407 | Ao abrir um fluxo, a visão se ajusta à tela em 100% de zoom ancorada no início do fluxo, priorizando legibilidade. |
| RF-408 | Uma caixa solta (sem conexões) com entrada e saída de dados, arrastada da paleta ou do próprio canvas para cima de um fio, é inserida entre as duas caixas: o fio é destacado antes de soltar, a caixa é posicionada logo após a origem e o destino e seus dependentes são deslocados para a direita (contêineres acompanham). |

## Critérios de aceite

- No fluxo de demonstração, nenhum texto de nó fica abaixo de 11 px na abertura.
- O painel de insights mostra 1 KPI, 2 Charts e 2 resumos (Vendas por cliente,
  MRR por UF) após executar.
- Clicar no nó Join abre Configurar à esquerda e mostra L/J/R à direita.
