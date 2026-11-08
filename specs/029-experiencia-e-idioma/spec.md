# Spec 029 — Versão 0.6.1: mais espaço, nomes claros e uma língua só

Status: Proposta · Criada: 2026-11-07 · Versão alvo: 0.6.1

## Por que esta versão

A 0.6 trouxe a vista Dados, o Data Quality e as constantes, e a 0.5.8 acertou o tema escuro e as cores das caixas. Olhando as quatro vistas no claro, no escuro e numa tela de 1024 px, o que ainda atrapalha não é a cor: é espaço, nome e hierarquia.

| Ponto | Situação hoje |
|-------|---------------|
| Espaço do canvas | Em 1440×900, os painéis deixam cerca de 750×480 px para o fluxo; em 1024 px, quase nada. A barra do canvas flutua sobre as caixas. |
| Nomes repetidos | "Dados" é a vista do topo, uma aba à esquerda e uma aba à direita. A barra de status diz "nós"; o guia diz "caixas". |
| Tabela de resultado | Tipos em inglês ("String", "n 500") e barrinhas de distribuição cinzas iguais em colunas de identificador. |
| Caixas | Nomes cortados no fim ("Faturamento do …", "clientes_enterprise.c…"). |
| Configurar | 270 px para o editor de fórmula; listas de opção no estilo do Windows, diferentes dos menus do programa. |
| Dashboard | Título e logo repetidos; cartão de indicador com metade vazia; cinco botões com o mesmo peso. |
| Cores de ação | No escuro, Executar é laranja e Copiar SQL é lilás. |
| Texto | Cerca de 40 regras com letra de 10–11 px; dicas em cinza abaixo do contraste recomendado. |
| Topo | Seis botões só com ícone. |
| Achar as coisas | Não há busca de comandos. |
| Espera | Tabela e gráficos não mostram que estão carregando; a troca de vista é seca. |
| Data de hoje | `Today()` existe nas fórmulas, mas não onde as constantes valem (Filter básico, nome do arquivo, parâmetros de API). |
| Idioma | Interface em português com vazamentos de inglês, sem uma regra escrita. |

## Princípios que valem para toda a versão

1. **Nada muda de lugar sem aviso:** quem já usa acha tudo onde estava, ou a tela mostra onde ficou.
2. **Telas aprovadas antes do código:** cada mudança visual é desenhada e aprovada antes de ir para o programa, como no tema escuro.
3. **Claro e escuro juntos:** toda mudança é conferida nos dois temas e numa tela de 1024 px.
4. **Compatível:** fluxos da 0.6.0 abrem e dão o mesmo resultado (teste de comparação).
5. **Regra de idioma (RF-2961):** interface em português; nomes de ferramenta e funções de fórmula em inglês, como vocabulário do produto.

## Requisitos

### 1. Espaço para o fluxo

| ID | Requisito |
|----|-----------|
| RF-2901 | **Modo foco**: um atalho (F11 ou botão na barra do canvas) esconde os painéis e deixa só o canvas; o mesmo atalho devolve o arranjo de antes. |
| RF-2902 | Em janelas com menos de 1280 px, sem arranjo salvo, o painel de resultado e os Gráficos e resumos começam recolhidos em faixas finas. O resultado abre ao clicar numa caixa ou na faixa; os gráficos, ao clicar na faixa. |
| RF-2903 | A barra do canvas (desfazer, zoom, Etapa, Constantes, Foco) continua flutuando no canto do canvas. No modo foco, ela vira uma faixa fixa acima do canvas, sem cobrir caixas. |
| RF-2904 | A largura dos painéis e o que está recolhido ficam lembrados entre aberturas. |

### 2. Um nome para cada coisa

| ID | Requisito |
|----|-----------|
| RF-2911 | Abas renomeadas: à esquerda **Ferramentas · Fontes · Configurar**; à direita **Resultado · Perfil · Log**. "Dados" fica só para a vista do topo. |
| RF-2912 | "Caixa" em toda a interface: barra de status ("26 caixas"), mensagens e dicas. "Nó" sai do texto visível. |
| RF-2913 | Na primeira abertura da 0.6.1, uma dica curta mostra os nomes novos das abas, uma vez só. |

### 3. Tabela de resultado

| ID | Requisito |
|----|-----------|
| RF-2921 | O cabeçalho de cada coluna usa os mesmos tipos do Configurar (abc, 123, 1,2, data, v/f) e diz o que falta: "sem vazios" ou "18 vazios", em vez de "n 500". Colunas de número mantêm a soma. |
| RF-2922 | A barrinha de distribuição só aparece quando informa: em coluna de identificador (quase todo valor diferente) mostra "todos diferentes" ou "quase todos diferentes" em texto. |

### 4. Caixas no canvas

| ID | Requisito |
|----|-----------|
| RF-2931 | Nome de arquivo longo na caixa corta no meio, guardando o fim que identifica ("clientes_ent…rise.csv"); o nome inteiro aparece ao passar o mouse. |
| RF-2932 | O nome da caixa ocupa até duas linhas, e a caixa mantém a largura: os fluxos salvos contam com ela, e uma caixa mais larga cobriria fios e vizinhas. |

### 5. Configurar

| ID | Requisito |
|----|-----------|
| RF-2941 | O editor de fórmula ganha **Abrir grande**: uma janela larga com o mesmo editor, a lista de colunas e funções ao lado e a validação embaixo. |
| RF-2942 | As listas de opção do Configurar usam o mesmo estilo dos menus do programa, com busca quando há mais de 10 opções, sem perder o uso pelo teclado. |

### 6. Dashboard

| ID | Requisito |
|----|-----------|
| RF-2951 | Um cabeçalho só: o título e o logo do relatório não se repetem na barra de ações. |
| RF-2952 | Cartões de indicador mais compactos, que não deixam metade vazia, com o valor e a variação lado a lado. |
| RF-2953 | Ação principal em destaque (Atualizar dados); Baixar imagem, Baixar HTML e Editar layout num grupo secundário ou menu. |

### 7. Idioma e cor

| ID | Requisito |
|----|-----------|
| RF-2961 | Regra escrita no guia e no `contexto-ia.md`: interface em português; os 31 nomes de ferramenta e as funções de fórmula ficam em inglês, como no Alteryx, para quem migra e para os fluxos salvos continuarem valendo. A descrição de cada ferramenta e função é em português. |
| RF-2962 | Varredura dos vazamentos de inglês no texto visível (tipos, status, mensagens do servidor, rótulos de porta) com um teste que barra palavras de uma lista proibida. |
| RF-2963 | Uma cor de ação principal por tema, usada em Executar, Copiar SQL, Atualizar dados e nos botões primários. As demais ações usam o estilo secundário. |

### 8. Leitura

| ID | Requisito |
|----|-----------|
| RF-2971 | Escala de letra com tamanho mínimo de 12 px para texto e 11 px só para rótulos de selo; os tamanhos viram tokens. |
| RF-2972 | Texto de dica e texto secundário com contraste de pelo menos 4,5:1 nos dois temas, conferido por teste como o de cores. |

### 9. Topo e busca

| ID | Requisito |
|----|-----------|
| RF-2981 | Os botões do topo ficam agrupados: Arquivo (novo, abrir, salvar, salvar como) num menu com texto; painéis, modo foco, densidade e atalhos num menu Exibir. O botão de tema claro e escuro continua à vista no topo, fora dos menus. |
| RF-2982 | **Busca de comandos (Ctrl+K)**: acha ferramentas (adiciona ao canvas), ações (executar, salvar, mudar de vista, tema), fontes (abre na vista Dados), caixas do fluxo (seleciona) e constantes, com o atalho de cada uma à direita. |

### 10. Espera e transições

| ID | Requisito |
|----|-----------|
| RF-2991 | Tabela de resultado, gráficos e vista Dados mostram um esqueleto enquanto carregam, em vez de espaço vazio. |
| RF-2992 | Troca de vista e abertura de painel com uma transição curta (até 150 ms), desligada quando o sistema pede menos movimento. |

### 11. Data de hoje

| ID | Requisito |
|----|-----------|
| RF-2995 | **`[#hoje]`** é uma constante do sistema, sempre disponível e sem cadastro, do tipo data, com o valor do dia (AAAA-MM-DD). Vale onde `[#nome]` vale: fórmulas, valor do Filter básico, nome do arquivo do Output Data e parâmetros fixos de API. |
| RF-2996 | Uma caixa que usa `[#hoje]` refaz quando o dia muda; nas demais, nada muda. |
| RF-2997 | `hoje` é nome reservado: não dá para cadastrar uma constante com esse nome. O botão Constante a mostra no topo, marcada como "do sistema". |
| RF-2998 | Na aba SQL, `[#hoje]` numa fórmula vira `Today()`, que o DuckDB entende como a data do dia (o mesmo que `CURRENT_DATE`); nos demais campos entra a data de quando o código foi gerado. O cabeçalho diz isso. Uma fórmula com `Today()` também refaz quando o dia muda. |

### 12. Manual dentro do programa

| ID | Requisito |
|----|-----------|
| RF-2983 | Um **Manual** dentro do programa, aberto pelo botão **?** no topo ou pela tecla F1, com sumário, busca e as imagens do guia. As imagens seguem o tema: cada captura existe em versão clara e escura, e trocar o tema troca as imagens na hora. O Manual pode ser expandido por um botão ou ter a largura ajustada arrastando a borda, e a largura fica lembrada. Funciona sem internet: vai no instalador. Abre ao lado do trabalho, sem cobrir o fluxo, e pode ser recolhido. |
| RF-2984 | Uma fonte só: `docs/guia/guia.html` gera o manual do programa e o PDF. As partes interativas são marcações no guia que no PDF aparecem como texto normal. |
| RF-2985 | **Mostrar onde fica**: um link no texto acende na tela o botão, aba ou painel citado, trocando de vista se preciso. |
| RF-2986 | **Experimentar**: abre numa aba nova um fluxo de exemplo pronto para o assunto, sem mexer no fluxo aberto. |
| RF-2987 | Nomes de ferramenta no texto viram links: clicar mostra a ferramenta na lista de Ferramentas. |
| RF-2988 | Ajuda conforme a tela: o **?** abre o capítulo do lugar onde a pessoa está (vista Dados → fontes; Data Quality selecionado → "Dados que dá para confiar"). A busca de comandos (RF-2982) também acha capítulos. |
| RF-2989 | Um teste confere que todo "mostrar onde fica" aponta para algo que existe na tela e todo "experimentar" para um exemplo que abre sem erro. |
| RF-2990 | Lições guiadas passo a passo ("Seu primeiro fluxo", "Juntar duas tabelas", "Conferir a qualidade", "Montar um dashboard"): ficam descritas aqui e entram na 0.6.2, sobre telas já estáveis. |

## Compatibilidade

- Fluxos da 0.6.0 abrem sem mudança e dão o mesmo resultado.
- Um fluxo que já tem uma constante do fluxo chamada `hoje` continua usando o valor dela, com um aviso para renomear.
- Nenhum nome de ferramenta ou função muda (RF-2961).
- O arranjo de painéis salvo na 0.6.0 continua valendo; só janelas pequenas sem arranjo salvo começam com o resultado recolhido.

## Critérios de aceite

- Comparação com a 0.6.0 nas saídas do exemplo (teste).
- `[#hoje]` resolve nos quatro lugares, refaz só quem a usa e vira `CURRENT_DATE` no SQL (teste).
- Nenhuma palavra da lista proibida no texto visível (teste); contraste e tokens de letra conferidos (teste, como o de tema).
- Busca de comandos, modo foco e abas renomeadas cobertos por bateria no navegador, nos dois temas e em 1024 px.
- Pytest, ruff, mypy, baterias, guia em PDF sem páginas vazias e executável testado.

## Fora de escopo

Interface em outros idiomas; nomes de ferramenta e função em português; `[#ontem]`, `[#mes_atual]` e outras constantes do sistema (só com pedido real); temas além de claro e escuro.

## Riscos e como tratar

| Risco | Tratamento |
|-------|------------|
| Quem já usa estranhar as abas renomeadas | Dica de primeira abertura (RF-2913), nota da versão e guia |
| Listas de opção próprias piorarem o uso pelo teclado | Seguir o padrão de lista com busca acessível; bateria só com teclado |
| `[#hoje]` dar resultados diferentes conforme o dia nos testes | Data injetada no teste; comparação com a 0.6.0 sem `[#hoje]` |
| Versão crescer demais | Etapas independentes; o que não couber vai para a 0.6.2 sem deixar nada pela metade |
