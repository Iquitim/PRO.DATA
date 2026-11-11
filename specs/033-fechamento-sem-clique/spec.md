# Spec 033: fechamento sem clique (0.7.5)

O PRO.DATA promete que o fechamento se refaz sozinho. Esta spec fecha as lacunas vistas numa revisão
externa do produto: executar sem abrir o programa, ler uma pasta inteira, avisar dos erros que mudam
totais em silêncio, conferir entrada e saída, comparar com a execução anterior e reaproveitar etapas.

## Histórias

- Como analista de controladoria, quero agendar o fluxo no Windows e encontrar os arquivos prontos de manhã.
- Como analista, quero apontar para a pasta do mês e ler todos os `vendas_*.xlsx` de uma vez.
- Como quem vem do PROCV, quero ser avisado quando a junção multiplica linhas.
- Como responsável pelo número, quero que o fluxo pare quando a qualidade ou os totais não fecham.
- Como controladoria, quero ver o que mudou em cada saída desde a execução anterior.
- Como time, quero uma etapa mantida num lugar só e usada em vários fluxos.

## Requisitos

### Execução sem clique

| ID | Requisito |
|---|---|
| RF-3301 | `prodata run <fluxo>` executa um fluxo da biblioteca (pelo ID ou nome) ou um arquivo `.prodata.json`, sem servidor e sem janela. |
| RF-3302 | O código de saída é 0 quando todas as caixas executam, 1 quando alguma falha e 2 quando o fluxo não pode ser lido ou está protegido. |
| RF-3303 | A execução escreve um resumo por caixa na tela e grava o relatório em `logs/execucoes/` na pasta de dados. `--relatorio <arquivo.json>` grava também onde o usuário pedir. |
| RF-3304 | Arquivo de fora da biblioteca só executa se já foi aberto e confirmado no programa (abertura protegida, spec 028). Não existe opção para pular a conferência. |
| RF-3305 | Exportação em "Perguntar" nunca sobrescreve: sem ninguém para responder, cria arquivo novo com data e hora, como já faz a execução pela API. |
| RF-3306 | O instalador traz `prodata-cli.exe`, com console. O programa mostra a linha de comando pronta do fluxo aberto e o comando do Agendador do Windows. |

### Ler uma pasta

| ID | Requisito |
|---|---|
| RF-3310 | A caixa **Input Folder** lê todos os arquivos de uma pasta que casam com um padrão de nome (`vendas_*.xlsx`) e os empilha por nome de coluna. |
| RF-3311 | A pasta é escolhida pelo usuário, com caminho completo e existente. A leitura é somente leitura e só aceita as extensões já permitidas para arquivos de dados. |
| RF-3312 | Uma coluna opcional traz o nome do arquivo de origem. Colunas que faltam num arquivo ficam vazias, e a caixa avisa quais arquivos têm colunas diferentes. |
| RF-3313 | A caixa refaz quando um arquivo entra, sai ou muda. Sem arquivos no padrão, falha com mensagem que mostra a pasta e o padrão. |
| RF-3314 | Há limite de 500 arquivos por leitura, com erro claro acima disso. |

### Junção que multiplica

| ID | Requisito |
|---|---|
| RF-3320 | O Join avisa quando a chave repete em [R] e por isso linhas de [L] viram mais de uma no J, dizendo quantas linhas viraram quantas. |
| RF-3321 | O aviso diz quando a chave repete dos dois lados, caso em que somas quase sempre dobram. |
| RF-3322 | "Repetição da chave é esperada" silencia o aviso. O esquema do Join mostra a multiplicação. |

### Controles de conciliação

| ID | Requisito |
|---|---|
| RF-3330 | O Data Quality pode interromper o fluxo: em qualquer falha, ou quando falhar mais de X% das linhas. A caixa fica em erro, e as seguintes não executam. |
| RF-3331 | A caixa **Reconcile** compara controles entre duas tabelas: contagem de linhas, soma ou contagem de distintos de uma coluna de cada lado, com tolerância. |
| RF-3332 | A saída C traz uma linha por controle: valor de A, valor de B, diferença e situação. A saída O repassa B, para o que vem depois depender da conferência. |
| RF-3333 | Com "Interromper se não fechar", a caixa falha e lista os controles que não fecharam. Sem isso, só avisa. |

### Comparar com a execução anterior

| ID | Requisito |
|---|---|
| RF-3340 | A caixa **Compare Runs** guarda a tabela a cada dia de execução e compara a atual com a guardada de um dia anterior ou de um mês anterior. |
| RF-3341 | A saída T traz totais: linhas e soma de cada coluna numérica, antes, agora, diferença e variação. |
| RF-3342 | Com colunas-chave, a saída D lista o que é novo, o que saiu e o que mudou, com o valor de antes e o de agora por coluna. |
| RF-3343 | Na primeira execução não há base: a caixa avisa e as saídas de diferença vêm vazias. |
| RF-3344 | As tabelas guardadas ficam na pasta de dados do computador, nunca no arquivo do fluxo. Ficam os últimos 62 dias e o último de cada mês por 13 meses. |

### Subfluxos

| ID | Requisito |
|---|---|
| RF-3350 | A caixa **Subflow** executa outro fluxo da biblioteca como uma etapa. Mudar o fluxo de origem muda todos os que o usam. |
| RF-3351 | O fluxo de origem declara sua interface com as caixas **Subflow Input** e **Subflow Output**, numeradas de 1 a 3. |
| RF-3352 | Aberto sozinho, o fluxo de origem usa a tabela de teste ligada em cada Subflow Input. |
| RF-3353 | Erro dentro do subfluxo aparece na caixa Subflow com o nome da caixa interna que falhou. |
| RF-3354 | Subfluxo dentro de subfluxo vale até 5 níveis. Um fluxo que chama a si mesmo é erro. |
| RF-3355 | O Subflow refaz quando o fluxo de origem muda. O índice de uso registra quais fluxos usam cada subfluxo. |

### Ferramentas novas

| ID | Requisito |
|---|---|
| RF-3360 | **Fuzzy Match** casa textos parecidos (razão social, endereço) entre [L] e [R], com nota de 0 a 100 e nota mínima. Saídas J, L e R como no Join. |
| RF-3361 | O Fuzzy Match normaliza caixa, acentos, pontuação e, opcionalmente, sufixos de empresa. Uma coluna de bloco (UF, por exemplo) limita as comparações. Acima de 25 milhões de pares, falha pedindo o bloco. |
| RF-3362 | **Regex** extrai grupos para colunas, substitui ou marca as linhas que casam. Padrão inválido é erro com a posição. |
| RF-3363 | **Multi-Field Formula** aplica uma fórmula a várias colunas, com `[_Atual_]` no lugar da coluna da vez, trocando a coluna ou criando outra com prefixo ou sufixo. |
| RF-3364 | **Generate Rows** cria uma sequência de números ou um calendário entre duas datas, com ano, mês, dia e dia da semana. Limite de 5 milhões de linhas. |
| RF-3365 | **Mask** protege dados pessoais: máscara de CPF, CNPJ e e-mail, manter só o início ou o fim, texto fixo, ou código estável. |
| RF-3366 | O código estável do Mask usa uma chave gerada neste computador e guardada no cofre do Windows. A chave nunca vai para o fluxo, e o guia diz que o código muda de um computador para outro. |

### Excel em modelo

| ID | Requisito |
|---|---|
| RF-3370 | O Output Data em Excel pode gravar num **modelo**: um `.xlsx` já formatado, a planilha e a célula inicial. O modelo nunca é alterado: o resultado é uma cópia no destino. |
| RF-3371 | A gravação muda só o valor das células, mantendo formato, larguras e fórmulas do resto da planilha. Uma Tabela do Excel no intervalo é redimensionada. |
| RF-3372 | "Limpar linhas antigas" apaga o que sobrou de uma gravação maior. O rótulo de confidencialidade continua valendo. |
| RF-3373 | Modelo com gráfico ou imagem gera aviso: a biblioteca pode não preservar esses elementos. |

### Modelos de ML

| ID | Requisito |
|---|---|
| RF-3380 | O Model Trainer guarda o modelo treinado em disco, com versão, data, linhas de treino e métricas. |
| RF-3381 | No modo **Modelo fixo** (padrão), o modelo guardado é reutilizado mesmo que os dados mudem, e a caixa avisa de quando ele é. Aumentar a **Versão** treina de novo. |
| RF-3382 | No modo **Treinar sempre**, cada treino com dados diferentes vira uma versão nova, e a caixa avisa a mudança das métricas. |
| RF-3383 | Mudar alvo, variáveis ou algoritmo com modelo fixo é erro que pede versão nova. |
| RF-3384 | Os modelos ficam na pasta de dados do computador. Não vão no arquivo do fluxo, e só são lidos dali. |
| RF-3385 | Com um nome na biblioteca de modelos, o modelo do Model Trainer pode ser usado em qualquer fluxo deste computador. |
| RF-3386 | A caixa **Model Input** traz um modelo da biblioteca, sem treinar, e entrega as mesmas saídas M e I do Model Trainer. |
| RF-3387 | O modelo é exportado e importado num arquivo `.modelo`. O formato não é pickle: o arquivo só abre se tudo o que ele contém for de um tipo de modelo que o PRO.DATA treina. Qualquer outro conteúdo é recusado, e nada do arquivo é executado. |
| RF-3389 | O Model Trainer lista as versões guardadas, com data, linhas e qualidade, nos dois modos de treino. Dá para voltar a uma versão (modelo fixo) e apagar qualquer uma, menos a que está em uso. Em "Treinar sempre" ficam as 10 últimas. Salvar o arquivo `.modelo` e tirar o modelo da biblioteca também ficam no Model Trainer. |
| RF-3388 | O esquema do Model Trainer e do Model Input mostra a ficha do modelo: o que prevê, a qualidade em validação, quando e com quantas linhas foi treinado e de quais colunas precisa. |

### Gráficos automáticos

| ID | Requisito |
|---|---|
| RF-3390 | Os gráficos automáticos de Summarize no painel de gráficos passam a ser opcionais, desligados por padrão. O painel diz quantos estão escondidos. |

### Escala

| ID | Requisito |
|---|---|
| RF-3391 | Os resultados intermediários deixam de ficar todos na memória: acima de um limite, os menos usados ficam só em disco e voltam quando uma caixa precisa deles. |
| RF-3392 | O limite padrão é um quarto da memória do computador, ajustável por `PRODATA_CACHE_MEMORY_MB`. |

Motor preguiçoso de ponta a ponta fica fora: exige reescrever todas as ferramentas.

### SQL para o Fabric

| ID | Requisito |
|---|---|
| RF-3393 | A aba SQL oferece o código em Spark SQL e em T-SQL, convertidos do DuckDB. |
| RF-3394 | O código convertido sai marcado como **não conferido**, na tela e no arquivo. A conferência com os resultados continua valendo só para o DuckDB. |
| RF-3395 | Trecho que a conversão não entende vira mensagem naquele bloco, sem derrubar os demais. |

### ODBC

| ID | Requisito |
|---|---|
| RF-3396 | Conexão do tipo ODBC usa uma fonte de dados (DSN) configurada no Windows, com usuário e senha opcionais. A senha fica no cofre. |
| RF-3397 | A conexão é somente leitura: só SELECT ou WITH, e aberta em modo de leitura quando o driver aceita. |
| RF-3398 | Listar tabelas, prévia e leitura funcionam como nas outras conexões. Texto de conexão com senha embutida é recusado. |

### Guia

| ID | Requisito |
|---|---|
| RF-3399 | O índice do guia lista todos os capítulos, com a numeração certa, e um teste confere isso. |

### Esquemas visuais e tabela em tela cheia

Vieram de uma revisão do dono do produto: as caixas novas tinham nascido sem o "Como funciona" que o Join e a Multi-Row têm.

| ID | Requisito |
|---|---|
| RF-3400 | Input Folder, Generate Rows, Reconcile, Compare Runs, Subflow, Fuzzy Match, Regex, Multi-Field Formula, Mask, Model Trainer e Model Input têm esquema "Como funciona" no Configurar. |
| RF-3401 | Depois de executar, o esquema usa os dados da própria caixa. Antes, mostra um exemplo e diz que é exemplo. |
| RF-3402 | O esquema do Mask usa só exemplos inventados: dados pessoais de verdade nunca aparecem nele. |
| RF-3403 | Passar o mouse num arquivo do Input Folder, num par do Fuzzy Match ou numa linha do Regex destaca o que veio dele. |
| RF-3404 | O guia e o Manual trazem a captura de cada esquema novo, nos temas claro e escuro, feita pelo gerador de imagens. |
| RF-3405 | O botão **Tela cheia** da tabela de resultados a abre na janela inteira, com busca, filtros, perfil e páginas. Shift+F11 alterna, e Esc volta ao que estava. |

## Fora do escopo

- Agendador próprio: o Agendador do Windows já faz isso.
- Entrada e saída do subfluxo com mais de 3 portas, e parâmetros de subfluxo.
- Tradução para SQL das caixas novas, exceto Regex e Generate Rows quando for direta.
- Conferência do ODBC em Oracle, MySQL e ERPs: só há driver de teste local. O guia diz isso.
- Conferência do SQL convertido num Fabric de verdade.
