# Spec 030 — Versão 0.7: da fonte ao replay

Status: Proposta, aguardando revisão · Criada: 2026-11-08 · Versão alvo: 0.7.0

## Por que esta versão

O PRO.DATA é um ETL visual com dashboards. A 0.7 o leva a um ambiente sem código de integração, análise no tempo e comunicação de dados: **Fonte → Preparação → Validação → Análise → Replay → Compartilhamento**.

| Ponto | Situação hoje |
|-------|---------------|
| Jira | Só dá para ler pelo cadastro genérico de API: é preciso conhecer endereço, paginação e o formato das respostas. |
| Passado | Uma tabela mostra o estado de agora. "Qual era o backlog em março?" não tem resposta sem reconstruir o histórico à mão. |
| Dashboard | Mostra um momento. Filtros mudam o recorte, mas a evolução no tempo depende de vários gráficos. |
| Compartilhamento | Imagem e HTML mostram o resultado; não contam a história de como se chegou lá. |
| Aprendizado | O Manual explica, mas ninguém conduz a primeira experiência. |

## Princípios que valem para toda a versão

1. **Só lê:** nada altera o Jira. Nenhum recurso desta versão grava na origem.
2. **Sem surpresa de custo:** a conexão usa a API oficial, sem consumir créditos Rovo.
3. **O passado é reconstruído, não presumido:** estados antigos vêm de eventos de alteração ou de snapshots registrados. O que não tem histórico é marcado, nunca preenchido com o valor atual.
4. **Sem pipeline a cada quadro:** o Replay e os GIFs usam dados já processados.
5. **Rótulos valem para tudo:** toda exportação nova respeita o rótulo de confidencialidade.
6. **Telas aprovadas antes do código**, nos dois temas e com animação reduzida.
7. **Exemplos sobre processos, não sobre pessoas:** nada na tela, no guia ou nos exemplos compara o desempenho de indivíduos.

## Requisitos

### 1. Conexão com o Jira Cloud

| ID | Requisito |
|----|-----------|
| RF-3001 | **Adicionar > Jira** na vista Dados. A pessoa cola o endereço do Jira, clica em **Criar meu token**, que abre a página da Atlassian no navegador, e volta com o token e o e-mail. |
| RF-3002 | A tela diz quais permissões de leitura marcar. O token com escopo de leitura é o caminho indicado; o token comum é aceito, com o aviso de que ele poderia alterar dados e a recomendação de trocar. |
| RF-3003 | O programa descobre sozinho o endereço que cada tipo de token exige (o token com escopo usa o `cloudId`). |
| RF-3004 | Testa na hora e mostra "Conectado como Fulano · N projetos". Token e e-mail ficam no cofre do Windows; nunca em fluxos, arquivos ou registros. |
| RF-3005 | Token vencido ou revogado vira um aviso claro, com o caminho para criar outro. |
| RF-3006 | Só Jira Cloud. A conexão é desenhada para aceitar outra forma de autenticação depois, sem refazer as consultas. |

### 2. Consulta Jira, sem código

| ID | Requisito |
|----|-----------|
| RF-3011 | Uma **Consulta Jira** é uma fonte da vista Dados, reutilizável, lida pelo Input Data e presente no mapa de uso, no mesmo modelo das consultas de banco. |
| RF-3012 | A pessoa escolhe o que trazer: **Demandas**, **Histórico de alterações** ou **Comentários**. Cada consulta entrega uma tabela. |
| RF-3013 | Seleção visual de projetos e colunas: resumo, tipo, status, prioridade, responsável, relator, datas e campos personalizados pelo nome que aparecem no Jira. |
| RF-3014 | Filtros em cartões (projeto, tipo, status, responsável, período) geram o JQL, mostrado ao lado. Há o modo **JQL avançado**, com validação antes de executar. |
| RF-3015 | Prévia das primeiras linhas e contagem antes de importar. |
| RF-3016 | Paginação automática, com andamento na tela. Limites de chamada respeitam o `Retry-After`, com novas tentativas controladas, e são explicados na tela. Uma carga interrompida continua de onde parou. |
| RF-3017 | Descrições e comentários no formato do Jira viram texto simples. Datas ficam com fuso conhecido. |
| RF-3018 | Comentários são opcionais e desligados por padrão: costumam ter dados pessoais. A tela diz isso ao ligar. |
| RF-3019 | O registro de execução diz o que foi lido, quantas chamadas e quanto tempo, sem token e sem conteúdo de demanda. |

### 3. Atualização incremental

| ID | Requisito |
|----|-----------|
| RF-3021 | Depois da primeira carga, só o que mudou é buscado, e as demandas ficam guardadas localmente. O mesmo vale para o histórico. |
| RF-3022 | Demandas excluídas no Jira não aparecem numa busca por alteração: uma releitura completa, sob demanda e sugerida após 30 dias, as remove. A tela diz quando foi a última. |
| RF-3023 | Mudar projetos, filtros ou colunas invalida o guardado e avisa antes de refazer a carga. |
| RF-3024 | O guardado local segue a pasta de dados do programa e pode ser apagado pela vista Dados. |

### 4. Ferramenta Estado por período

| ID | Requisito |
|----|-----------|
| RF-3031 | Ferramenta nova que transforma eventos em fotos: recebe uma tabela de itens e uma de eventos, e devolve **uma linha por item e por período** (dia, semana ou mês), com o estado no fim do período. Serve para qualquer tabela de eventos, não só a do Jira. |
| RF-3032 | Colunas calculadas: estado, dias naquele estado e dias desde a criação. |
| RF-3033 | Item sem histórico até uma data fica como "sem histórico", nunca com o valor atual. A caixa conta quantos ficaram assim e avisa. |
| RF-3034 | Esquema "Como funciona", com eventos antes e fotos depois, no estilo do Join. |
| RF-3035 | Limite claro de tamanho, com aviso antes de explodir itens × períodos. Tem tradução para SQL ou diz que não tem. |

### 5. Linha do tempo no Dashboard (Replay)

| ID | Requisito |
|----|-----------|
| RF-3041 | O dashboard pode ter uma **linha do tempo**: a pessoa escolhe a coluna de data e o passo (dia, semana, mês). |
| RF-3042 | Reproduzir, pausar, velocidade e seleção de período. Arrastar leva a qualquer momento. |
| RF-3043 | Visuais, indicadores e tabelas com a coluna acompanham juntos, sem executar o fluxo. Os que não têm a coluna ficam parados, com uma marca que diz por quê. |
| RF-3044 | Dois modos, com explicação na tela: **acumulado até o momento** e **só naquele período**. |
| RF-3045 | Filtros continuam valendo durante a reprodução. |
| RF-3046 | Parar num momento e abrir os registros daquele ponto, como já acontece ao clicar num visual. |
| RF-3047 | **Destaques**: picos, mudanças de tendência e valores fora do padrão marcados na linha do tempo. Cada um diz o critério ("2,3 desvios acima da média das últimas 8 semanas"). |
| RF-3048 | Exemplo de demonstração sem Jira: tabelas fictícias de demandas e eventos no programa, mostrando **envelhecimento do backlog** e **tempo parado em cada status**. |

### 6. Gráficos animados

| ID | Requisito |
|----|-----------|
| RF-3051 | Transições suaves em barras, linhas, áreas e dispersão ao mudar de momento. |
| RF-3052 | **Corrida de barras**: ranking que muda de posição no tempo. Tipo novo, para categorias como projeto, tipo ou status. |
| RF-3053 | **Bolhas animadas**: a dispersão ganha tamanho, categoria e evolução no tempo. |
| RF-3054 | **Sankey**: fluxos entre estados, com a passagem no tempo. Tipo novo. |
| RF-3055 | Animação configurável em cada visual, com opção de desligar. Com o sistema pedindo menos movimento, os valores mudam sem transição. |

### 7. Storytelling

| ID | Requisito |
|----|-----------|
| RF-3061 | **História**: uma sequência de cenas, cada uma guardando momento, filtros e visual em destaque. |
| RF-3062 | Título, anotação e destaque em cada cena. |
| RF-3063 | Modo apresentação: anterior, próxima e reprodução. |
| RF-3064 | De cada cena dá para chegar à caixa e aos dados de origem. |

### 8. Exportação

| ID | Requisito |
|----|-----------|
| RF-3071 | **GIF por gráfico**, nunca do dashboard inteiro: duração, resolução, quadros por segundo, período e repetição, com o tamanho estimado antes de gerar. |
| RF-3072 | O GIF usa os dados já processados, sem executar o fluxo a cada quadro. |
| RF-3073 | GIF não tem senha: em **Restrito** é bloqueado; em **Confidencial** pede confirmação, como a imagem. |
| RF-3074 | PNG continua como está. O **HTML** ganha a linha do tempo, a reprodução e a história, com filtros, senha e rótulo como hoje. |
| RF-3075 | Limites para evitar arquivo enorme e travamento, ditos na tela. |

### 9. Lições guiadas

| ID | Requisito |
|----|-----------|
| RF-3081 | Lições passo a passo dentro do Manual: **Seu primeiro fluxo**, **Juntar duas tabelas**, **Conferir a qualidade** e **Montar um dashboard**. |
| RF-3082 | Cada passo acende onde clicar e avança quando a ação acontece. Dá para sair a qualquer momento, e o programa lembra o que foi concluído. |
| RF-3083 | Rodam num fluxo próprio, sem mexer no da pessoa. Um teste percorre cada lição até o fim. |

### 10. Arrumação técnica

| ID | Requisito |
|----|-----------|
| RF-3091 | `dashboard.js` (758), `charts.js` (678) e `fields.js` (784) são divididos antes de crescer. O limite de 800 linhas e o teste de ciclos continuam valendo. |
| RF-3092 | O dashboard usa no programa o mesmo cálculo no navegador do HTML exportado, conferido com o motor número a número. Sem isso, cada quadro do Replay iria ao servidor. |
| RF-3093 | Guia, Manual, README e `contexto-ia.md`, com imagens novas nos dois temas. |

## Como testar

- **Jira simulado no repositório**, em Python, feito a partir de respostas reais anonimizadas: login, paginação por `nextPageToken`, limite com `Retry-After`, token vencido, histórico longo e volume.
- **Conferência num Jira Cloud real de teste** antes de publicar: permissões exatas do token e o histórico em lote, com o caminho por demanda como reserva caso o endpoint em lote mude.

## Compatibilidade

- Fluxos da 0.5.9, 0.6.0 e 0.6.1 abrem e dão o mesmo resultado (teste de comparação).
- A linha do tempo e as histórias são campos novos e opcionais do dashboard. Um dashboard sem eles fica como está.
- **Volta para a 0.6.1:** um fluxo com Consulta Jira ou com história abre sem esses recursos, com aviso.

## Critérios de aceite

- Conectar ao Jira, escolher projetos e importar sem escrever JQL (bateria no navegador, sobre o simulador).
- Nenhuma chamada de escrita sai do conector (teste que recusa qualquer método ou rota de alteração).
- Token nunca aparece em arquivo, fluxo ou registro (teste, como nas demais credenciais).
- Interromper e retomar uma carga dá o mesmo resultado de uma carga inteira; a incremental também (teste).
- Estado por período confere com casos montados à mão, inclusive item sem histórico (teste).
- Replay igual ao motor em cada momento, número a número; nenhum quadro executa o fluxo (teste).
- GIF respeita rótulo e limites (teste).
- Cada lição percorrida até o fim (bateria).
- Pytest, ruff, mypy, baterias, guia em PDF e executável testado.

## Fora de escopo

Autenticação pelo MCP da Atlassian ou OAuth; Jira Server/Data Center; GIF do dashboard inteiro; MP4 e WebM; comparação de períodos ou cenários simulados; qualquer gravação no Jira; ranking ou comparação de pessoas; agendamento.

## Riscos e como tratar

| Risco | Tratamento |
|-------|------------|
| Versão maior que a 0.6 | Etapas independentes. Se apertar, saem nesta ordem: lições, Sankey, história, destaques |
| API do Jira mudar | Toda chamada num único módulo; o endpoint de histórico em lote tem caminho alternativo |
| Replay lento com muitos dados | Limite de linhas por visual, passo maior sugerido e teste de desempenho |
| Explosão de itens × períodos | Estimativa e aviso antes de executar (RF-3035) |
| Dados pessoais vindos do Jira | Comentários desligados por padrão; rótulos valem em toda saída; exemplos sobre processos |
