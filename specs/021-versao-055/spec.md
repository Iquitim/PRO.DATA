# Spec 021 — Versão 0.5.5: fontes de API, dashboard com filtros e HTML, Dracula e ajustes

Status: Implementada · Criada: 2026-11-04 · Versão alvo: 0.5.5

## Contexto (o que foi verificado no código)

| # | Pedido | Situação encontrada |
|---|--------|---------------------|
| 1 | Excel com mais de uma planilha/tabela no Output | Hoje exige uma caixa Output Data por planilha, todas em "Adicionar planilha". A caixa só tem uma entrada. |
| 2 | API na entrada de dados | Não existe. As consultas de banco já são fontes salvas na aba Dados, com o segredo no cofre do sistema: é o mesmo modelo a seguir. |
| 3 | Summarize da tabela inteira, sem agrupar | **O motor já faz** com "Agrupar por" vazio, e a saída correta foi confirmada no programa (uma linha com o total). Falta a tela deixar isso claro: nada indica que pode ficar vazio. |
| 4 | Caixa de abertura não some | **Defeito reproduzido.** No executável da 0.5.0, a janela da caixa continua visível 20 segundos depois de a janela principal abrir: depende de um único aviso para fechar, e uma falha é silenciosa. |
| 5 | Soma na visualização de dados | O perfil de cada coluna numérica já calcula a soma, mas o cabeçalho da tabela não mostra. |
| 6 | Modo escuro quase preto | Fundo `#111112` e superfícies próximas de preto. |
| 7 | Filtro no dashboard | Não existe. Os visuais são calculados na execução do fluxo. |
| 8 | Exportar o dashboard em HTML | Só há PNG. |
| 9 | Nomes de legendas e rótulos com muitos itens | **Defeito reproduzido.** Com 30 categorias, os rótulos do eixo viram "Ca.Ca.Ca." sobrepostos, em Colunas, Pareto e empilhados. A legenda em linha também pode ocupar o espaço do gráfico. |
| 10 | Fórmula multilinha | Não existe. Faz sentido: preencher para baixo, comparar com a linha anterior e calcular diferenças são usos comuns no Alteryx. |

## Requisitos funcionais

### Saída em Excel

| ID | Requisito |
|----|-----------|
| RF-2101 | Com o formato Excel, a mesma caixa Output Data recebe várias tabelas, até 8: uma entrada livre aparece sempre que as anteriores estão ligadas. Cada tabela vira uma planilha da mesma pasta de trabalho `.xlsx`. |
| RF-2102 | O Configurar lista as entradas ligadas, com o nome de cada planilha editável. Nomes inválidos ou repetidos dão erro claro antes de gravar. |
| RF-2103 | Fluxos existentes continuam iguais, e a opção "Adicionar planilha" com várias caixas continua funcionando. Nos outros formatos, a caixa segue com uma entrada só. |

### Fonte de API

| ID | Requisito |
|----|-----------|
| RF-2111 | Na aba Dados, "Nova API" cadastra uma fonte: nome, URL, método (GET ou POST), parâmetros, cabeçalhos e corpo. O Input Data a lê como qualquer outra fonte, e uma prévia mostra o resultado antes de salvar. |
| RF-2112 | Autenticação: nenhuma, Bearer Token, chave em cabeçalho ou na URL, usuário e senha, ou OAuth 2 por credenciais de cliente (com renovação automática do token). Os segredos ficam **só no cofre do sistema**, nunca no fluxo, em arquivos ou nos logs. |
| RF-2113 | Respostas JSON, CSV e XML. Um caminho indica onde estão os registros (ex.: `data.items`). Objetos aninhados viram colunas (`cliente.nome`), e listas internas podem virar linhas, à escolha. |
| RF-2114 | Paginação por número de página, deslocamento, cursor ou link da próxima página (no corpo ou no cabeçalho `Link`), até a resposta vir vazia ou até um limite de páginas. Nunca há laço infinito. |
| RF-2115 | Tempo limite, tamanho máximo, novas tentativas com espera em falhas temporárias (429, 5xx, respeitando `Retry-After`) e erro claro em português (401, tempo esgotado, JSON sem o caminho indicado). |
| RF-2116 | Só `https`, ou `http` com aviso visível. A URL pertence à fonte cadastrada neste computador: um fluxo recebido de outra pessoa não consegue fazer o programa chamar um endereço por conta própria. |
| RF-2117 | GET: cada execução chama a API de novo, com a opção "Reaproveitar resultado", como nas consultas de banco. POST e loops não rodam sozinhos ao abrir um fluxo: esperam o clique em Executar, porque podem ter efeito no sistema de origem ou consumir cota. |
| RF-2118 | Nova ferramenta **API Loop**: para cada linha da tabela de entrada, chama uma fonte de API cadastrada e junta as respostas numa tabela só. A entrada pode ser a saída de outra API. Colunas viram parte da chamada com `{coluna}` na URL, nos parâmetros, nos cabeçalhos ou no corpo. |
| RF-2119 | O API Loop tem saídas **R** (respostas, com as colunas da linha de origem) e **E** (linhas que falharam, com o erro). Uma linha que falha não derruba as outras, e chamadas iguais não se repetem. Limites de simultaneidade, chamadas por segundo e total de chamadas protegem a API de origem, e o andamento aparece enquanto roda. |
| RF-2120 | Na aba SQL, a fonte de API aparece como fonte externa, igual às consultas de banco, e o API Loop aparece como caixa sem tradução. |

### Summarize

| ID | Requisito |
|----|-----------|
| RF-2121 | O "Agrupar por" diz que é opcional: "Vazio = calcula sobre a tabela inteira". O esquema "Como funciona" já mostra o caso; a anotação da caixa diz "Total geral". |
| RF-2122 | O painel Gráficos e resumos mostra esse resultado como número, não como gráfico de uma barra sem categoria. |

### Abertura

| ID | Requisito |
|----|-----------|
| RF-2131 | A caixa de abertura sempre some quando a janela principal aparece. Se o fechamento normal falhar, o programa fecha a janela da caixa diretamente, e o log registra o que aconteceu. |

### Visualização de dados

| ID | Requisito |
|----|-----------|
| RF-2141 | Em colunas numéricas, o cabeçalho da tabela mostra a soma ao lado do tipo (`Σ 2,4 mi`), com o valor completo ao passar o mouse. Nas demais, mostra a contagem de linhas não nulas (`n 368`). Considera a tabela inteira ou os filtros ativos, não só a página. Códigos numéricos também mostram a soma: o programa não tenta adivinhar. |

### Modo escuro

| ID | Requisito |
|----|-----------|
| RF-2151 | O modo escuro usa uma paleta análoga ao tema Dracula: fundo `#21222c`, superfícies a partir de `#282a36`, texto `#f8f8f2`, e acentos ciano, verde, laranja, rosa, roxo, vermelho e amarelo. O modo claro não muda. |
| RF-2152 | Texto mantém contraste mínimo de 4,5:1 com o fundo, verificado em teste, ajustando o tom quando a cor original não alcança. A barra do topo com a marca segue a nova paleta no modo escuro. |

### Filtros no dashboard

| ID | Requisito |
|----|-----------|
| RF-2161 | Uma barra no topo da página, na visualização e no modo Editar, permite adicionar filtros: um por coluna, usando seleção de valores ou, em colunas de data e número, um intervalo. |
| RF-2162 | O filtro vale para todos os visuais cuja tabela tem aquela coluna. Visuais sem a coluna não mudam e mostram um indicador discreto de que não foram filtrados. |
| RF-2163 | Filtrar recalcula só os visuais, sem executar o fluxo de novo. Os filtros escolhidos ficam salvos no fluxo. "Limpar filtros" volta ao estado original. |
| RF-2164 | A imagem PNG e o HTML exportados mostram os filtros ativos, para quem recebe saber o que está vendo. |

### HTML do dashboard

| ID | Requisito |
|----|-----------|
| RF-2171 | Ao lado de "Baixar imagem", "Baixar HTML" gera um arquivo único, que abre em qualquer navegador sem internet e sem o PRO.DATA. |
| RF-2172 | Mantém a página como está na tela, com o tema atual e os detalhes ao passar o mouse. **Os filtros funcionam dentro do arquivo**: ele leva os dados tratados e recalcula os visuais no navegador de quem abre, com os mesmos resultados do programa. |
| RF-2173 | O arquivo leva só as colunas que os visuais e os filtros usam, nunca as tabelas inteiras. Só os visuais que têm a coluna de algum filtro levam dados; os demais levam o número pronto. Sem filtros na página, o arquivo leva só o que está na tela. Antes de salvar, a tela avisa que os dados vão dentro do arquivo e mostra o tamanho e quantas linhas e colunas ele leva. |
| RF-2174 | Acima de um limite de tamanho, a exportação avisa e oferece gerar o retrato sem filtros, em vez de produzir um arquivo que o navegador não abre. Nenhum recurso externo é carregado. |

### Rótulos e legendas

| ID | Requisito |
|----|-----------|
| RF-2181 | Rótulos do eixo nunca se sobrepõem: quando não cabem, aparece um a cada N, e o nome completo fica no detalhe ao passar o mouse. Vale para Colunas, Linha, Área, Pareto, empilhados e agrupados. |
| RF-2182 | Legendas com muitos itens não tomam o espaço do gráfico: ocupam até 3 linhas, o gráfico diminui só o necessário e nomes longos ficam com reticências, com o nome completo no detalhe. |
| RF-2183 | O que não couber nas 3 linhas vira "+N", com os nomes no detalhe. Vale igual na tela, na imagem PNG e no HTML. |

### Fórmula multilinha

| ID | Requisito |
|----|-----------|
| RF-2191 | Nova ferramenta **Multi-Row Formula**, que referencia outras linhas: `[Row-1:valor]`, `[Row+1:valor]`, até 100 linhas de distância. A expressão usa o mesmo editor e as mesmas funções da Formula. |
| RF-2192 | Cria uma coluna nova ou altera uma existente. "Agrupar por" é opcional: as referências não atravessam grupos. |
| RF-2193 | Uma referência à linha anterior da própria coluna usa o valor já calculado. É o que permite preencher para baixo: `IF IsNull([uf]) THEN [Row-1:uf] ELSE [uf] ENDIF`. Referência à linha seguinte da própria coluna é recusada, com explicação. |
| RF-2194 | Linha inexistente (antes da primeira ou depois da última) vale vazio por padrão, ou 0/texto vazio, à escolha. |
| RF-2195 | O cálculo segue a ordem das linhas que chegam, e o Configurar avisa para usar um Sort antes quando a ordem importar. |
| RF-2196 | A aba SQL traduz a ferramenta, com a ressalva de ordem: janelas para outras colunas e consulta recursiva para a própria coluna, conferidas com o motor como as demais. |
| RF-2197 | Um limite de rodadas protege contra lentidão no caso recursivo, com erro que indica o Running Total para somas acumuladas. Acima de 5.000 linhas, a aba SQL mostra a tradução, mas informa que não conferiu. Na própria coluna, a tradução cobre `[Row-1:…]`; olhar mais longe fica sem tradução. |

## Critérios de aceite

- Uma caixa Output Data com 3 entradas gera um `.xlsx` com 3 planilhas e os nomes escolhidos, e fluxos antigos seguem iguais (teste e regressão contra a 0.4.1).
- API de teste local: cada autenticação, JSON aninhado, cada tipo de paginação, 401, 429 com nova tentativa, tempo esgotado e resposta grande demais. O segredo não aparece no fluxo, em arquivos, logs ou no SQL (teste).
- API Loop: chamada por linha, com a saída de uma API alimentando outra, linhas com erro na saída E e limites respeitados (teste).
- Summarize com "Agrupar por" vazio dá o total, e a tela indica que é possível (teste no navegador).
- A caixa de abertura some em lançamentos repetidos do executável, verificado pelas janelas do processo.
- Soma no cabeçalho respeita filtros (teste no navegador).
- Contraste do modo escuro verificado em teste automático; modo claro idêntico nas capturas.
- Filtro no dashboard muda os visuais certos, sem executar o fluxo, e continua ao salvar e reabrir (teste).
- HTML exportado abre sem rede e leva só as colunas usadas; filtrar dentro dele dá os mesmos números que o programa, em cada tipo de visual (teste que compara os dois).
- Com 30 categorias, nenhum rótulo sobreposto em nenhum tipo de gráfico (teste de geometria no navegador).
- `Row-1` e `Row+1`, grupos, preencher para baixo e bordas batem com o esperado e com o SQL (teste de equivalência).

## Fora de escopo

Agendar execuções; OAuth com login pelo navegador; GraphQL dedicado (funciona como POST); filtros diferentes por visual; várias tabelas dentro da mesma planilha; PUT, PATCH e DELETE em API.
