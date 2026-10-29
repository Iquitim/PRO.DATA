# Spec 014 — Dashboard em canvas, visuais personalizáveis e exportação

Status: Implementada (falta o fechamento: guia, versão 0.3.0 e instalador) · Criada: 2026-10-29 · Versão alvo: 0.3.0

## Contexto

- O dashboard é uma grade fixa: KPIs numa faixa no topo, gráficos em 1 ou 2 colunas,
  na ordem dos nós. Não dá para escolher posição, tamanho nem destacar um visual.
- A aparência não é configurável: cores fixas (paleta da marca), sem rótulos de
  dados, sem legenda, sem controle de eixos.
- Só 4 tipos de gráfico (colunas, barras, linha, rosca), todos com uma única
  dimensão. O KPI Card mostra só um número, sem contexto (meta, variação, tendência).
- Não há como levar o dashboard para fora do programa (e-mail, apresentação).

## Princípio da v0.3

**O fluxo define os dados; o dashboard define a aparência.** As caixas de BI no fluxo
continuam dizendo *o que* mostrar (coluna, agregação, período). O dashboard ganha um
modo de edição em canvas — como o fluxo — onde se decide *onde* e *como* mostrar.

## Histórias de usuário

1. Como analista, quero arrastar e redimensionar os visuais numa página, com encaixe
   e guias de alinhamento, para montar o layout que conta a história dos dados.
2. Como analista, quero clicar num gráfico e mudar cores, legenda, rótulos e eixos
   sem voltar ao fluxo.
3. Como gestor, quero big numbers que mostram a variação contra a meta ou o período
   anterior, com seta e cor, e uma linha de tendência.
4. Como analista, quero gráficos com duas dimensões (empilhado, agrupado, várias
   linhas), além de área, dispersão, funil, medidor, Pareto, diagrama de Venn e
   tabela.
5. Como analista, quero títulos, textos, o logo e formas para organizar a página em
   seções.
6. Como analista, quero organizar os visuais com um clique (automático ou por um
   layout pronto) em vez de posicionar um por um.
7. Como gestor, quero baixar o dashboard em PNG, ou só um gráfico, para colar num
   e-mail ou numa apresentação.

## Requisitos funcionais

### Canvas do dashboard

| ID | Requisito |
|----|-----------|
| RF-1401 | O dashboard tem dois modos: **Visualizar** (padrão, só leitura, tooltips e "ir para o nó") e **Editar** (canvas). |
| RF-1402 | A página tem tamanho fixo: 16:9 (1600×900, padrão), A4 paisagem, A4 retrato ou altura livre (largura 1600, altura escolhida). Cor de fundo configurável. A página é escalada para caber na tela, com zoom. |
| RF-1403 | No modo Editar, cada item pode ser arrastado e redimensionado pelas alças. Posição e tamanho se encaixam numa grade de 8 px (desligável segurando `Alt`). Aparecem guias de alinhamento ao chegar perto das bordas ou do centro de outro item ou da página. |
| RF-1404 | Seleção múltipla (`Shift`/`Ctrl`+clique, retângulo), mover em grupo, alinhar e distribuir, trazer para frente e enviar para trás, duplicar, excluir, copiar e colar. Setas movem 1 px (`Shift`+seta move 8 px). |
| RF-1405 | Alterações no layout entram no desfazer/refazer do fluxo, marcam o fluxo como não salvo e ficam gravadas no arquivo `.prodata.json`. |
| RF-1406 | Um visual novo (caixa de BI sem lugar na página) é posicionado automaticamente no primeiro espaço livre. Excluir a caixa de BI no fluxo remove o visual da página (mantém a spec 010). |
| RF-1407 | Remover um visual da página **não** apaga a caixa do fluxo: ele vai para a lista "Visuais fora da página", de onde volta com um clique ou arrastando. |
| RF-1408 | Fluxos antigos (sem layout salvo) abrem com o layout pronto "KPIs no topo + 2 colunas" (RF-1460), equivalente ao atual. |

### Organizar e layouts prontos

| ID | Requisito |
|----|-----------|
| RF-1460 | Botão **Organizar** no modo Editar, com uma galeria de layouts prontos. Cada opção mostra uma miniatura desenhada com os visuais que o dashboard tem. As opções são: **KPIs no topo + 2 colunas**, **KPIs no topo + 3 colunas**, **Destaque** (um gráfico grande e os demais ao lado), **KPIs na lateral** (big numbers em coluna à esquerda) e **Relatório** (um visual por linha, em largura total; muda a página para altura livre). |
| RF-1461 | **Organizar automaticamente** escolhe o tamanho de cada visual pelo tipo e conteúdo (big number pequeno; rosca e medidor quadrados; tabela, linha e gráficos com muitas categorias mais largos), mantém a ordem de leitura atual (de cima para baixo, da esquerda para a direita) e preenche a página sem buracos, sem sobreposição e com espaçamento uniforme. |
| RF-1462 | Organizar mexe só nos visuais selecionados, ou em todos se nada estiver selecionado. Textos, imagens e formas ficam onde estão, e a área ocupada por eles é evitada. |
| RF-1463 | Se os visuais não couberem na página fixa, a altura vira livre, com aviso. Organizar é um único passo de desfazer. |

### Formatação dos visuais

| ID | Requisito |
|----|-----------|
| RF-1410 | Selecionar um item no modo Editar abre o painel **Formato**. Ele é gerado a partir de um modelo declarado por tipo de item, como os formulários do Inspector. |
| RF-1411 | Cartão: título (texto, tamanho, alinhamento, mostrar ou ocultar), subtítulo, fundo, borda, cantos e sombra. |
| RF-1412 | Cores: paleta da marca (padrão), outra paleta categórica validada, uma cor única, ou uma cor por categoria ou série. Cores escolhidas fora da paleta validada mostram um aviso de contraste. |
| RF-1413 | Gráficos: legenda (mostrar ou ocultar), rótulos de dados (nenhum, maior valor, ou maior e menor; nunca um número em cada ponto, os demais ficam no tooltip), formato dos números (compacto ou completo, casas decimais, prefixo e sufixo), eixos (título, mínimo e máximo, linhas de grade). Ordenação e limite de categorias continuam na caixa do fluxo, porque mudam os dados; o painel leva até ela. |
| RF-1414 | Formatação condicional nas tabelas e big numbers: cor do valor por faixa (ex.: < 0 vermelho, ≥ meta verde). |

### Big number rico

| ID | Requisito |
|----|-----------|
| RF-1420 | O KPI Card ganha uma **comparação** opcional: contra uma meta fixa, ou contra o período anterior (coluna de data + granularidade dia, semana, mês, trimestre ou ano; compara o último período completo com o anterior). |
| RF-1421 | A comparação mostra a variação absoluta e percentual, com seta ↑/↓. A cor depende de "maior é melhor" ou "menor é melhor", configurável. |
| RF-1422 | Minigráfico de tendência opcional (linha ou colunas) pela coluna de data, nos últimos N períodos. |
| RF-1423 | O formato do número é configurável: compacto (1,2 mi), completo, percentual, moeda (R$). |

### Novos tipos de gráfico

| ID | Requisito |
|----|-----------|
| RF-1430 | O Chart aceita uma **segunda dimensão** (coluna de série): colunas e barras empilhadas, agrupadas ou 100%; linhas múltiplas; área e área empilhada. Limite de 8 séries; as demais viram "Outras". |
| RF-1431 | Dispersão: X e Y numéricos, cor por categoria opcional, amostra de até 2.000 pontos, informada no rodapé quando há amostragem. |
| RF-1432 | Funil (etapas ordenadas pela categoria ou pelo valor) e medidor (valor contra meta e faixa máxima). |
| RF-1435 | **Pareto** num eixo só, de 0 a 100%: cada coluna é a participação da categoria no total, em ordem decrescente, e a linha é o percentual acumulado, com rótulo direto no ponto de corte (sem segundo eixo Y: gráfico de dois eixos engana a leitura). Linha de referência configurável (padrão 80%); o valor absoluto fica no tooltip e no modo tabela. As categorias até a referência ficam destacadas. Acumulado calculado no motor. Aceita soma ou contagem. |
| RF-1436 | Nova ferramenta **Venn** (BI): diagrama de 2 ou 3 conjuntos com a contagem de cada região e o percentual do total. Os conjuntos podem vir de 2 ou 3 colunas verdadeiro/falso, ou de uma coluna de chave (ex.: cliente) + uma coluna de grupo (ex.: produto), escolhendo 2 ou 3 valores. Nesse caso, conta chaves distintas. |
| RF-1437 | Com 2 conjuntos, as áreas dos círculos e da interseção são proporcionais às contagens. Com 3, os círculos têm tamanho fixo e só os números indicam a proporção, e o rodapé do visual diz isso. O modo tabela mostra todas as regiões. |
| RF-1433 | Nova ferramenta **Table** (BI): tabela formatada no dashboard com as colunas escolhidas, totais opcionais, até 500 linhas e formatação condicional (RF-1414). |
| RF-1434 | O painel de insights e o modo tabela de cada visual continuam funcionando com os tipos novos. |

### Elementos livres

| ID | Requisito |
|----|-----------|
| RF-1440 | **Texto**: título ou parágrafo com negrito, itálico, tamanho, cor e alinhamento. |
| RF-1441 | **Imagem**: PNG, JPG ou SVG de até 1 MB, gravada dentro do fluxo para que o arquivo continue portátil. O logo da Protege está disponível com um clique. |
| RF-1442 | **Formas**: retângulo (fundo de seção) e linha divisória, com cor, borda e cantos. |

### Exportação

| ID | Requisito |
|----|-----------|
| RF-1450 | Botão **Baixar imagem** no dashboard: PNG da página inteira em alta resolução (2×), igual ao modo Visualizar, sem alças, guias nem botões. |
| RF-1451 | No menu de cada visual: "Baixar imagem (PNG)" daquele visual. |
| RF-1452 | No programa instalado, o arquivo é salvo pela janela "Salvar como" do Windows. No navegador, é baixado normalmente. O nome sugerido é `<fluxo> - <data>.png`. |
| RF-1453 | Se o fluxo não foi executado, ou há visuais com erro, a exportação avisa antes de gerar. |

## Fora do escopo (v0.3)

- Exportar em PDF (o PNG cobre e-mail e apresentações; pode voltar numa versão futura).
- Várias páginas no dashboard.
- Filtros interativos e cruzamento entre visuais (clicar numa barra e filtrar os
  outros).
- Atualização agendada e envio automático por e-mail.
- Temas completos do dashboard (só cor de fundo da página e formato por item).

## Critérios de aceite

- Mover um gráfico para o canto, redimensionar, salvar, fechar e reabrir: o layout
  volta igual. Um `Ctrl+Z` desfaz o último movimento.
- Abrir um fluxo da v0.2: o dashboard aparece com o layout automático, sem erro.
- Excluir a caixa Chart no fluxo: o visual sai da página. Remover o visual da página:
  a caixa continua no fluxo e o visual aparece em "Visuais fora da página".
- Mudar a cor e ligar os rótulos de um gráfico não executa o fluxo de novo.
- Big number "Receita" com comparação mês anterior e "maior é melhor": valor maior
  que no mês anterior mostra ↑ verde com o percentual correto (coberto por teste).
- Gráfico de colunas empilhadas por UF × produto: os totais batem com um Summarize
  equivalente (teste).
- Pareto de faturamento por cliente: o acumulado termina em 100% e as categorias
  destacadas são exatamente as que somam até 80% (teste).
- Venn de clientes por produto (A, B): as contagens de "só A", "A e B" e "só B" batem
  com a contagem de clientes distintos (teste); com 2 conjuntos, a área da interseção
  é proporcional (erro < 1%).
- Com 7 visuais espalhados, "Organizar automaticamente" e cada layout pronto deixam
  todos dentro da página, sem sobreposição e alinhados à grade. Um `Ctrl+Z` volta ao
  estado anterior. Um texto posicionado à mão não se move.
- Exportar PNG da demonstração: a imagem tem o tamanho da página × 2, com as fontes e
  as cores da tela.
