# Spec 020 — Versão 0.5: aba SQL

Status: Implementada · Criada: 2026-11-02 · Versão alvo: 0.5.0

## Contexto

O PRO.DATA é onde a pessoa constrói rápido e experimenta, mas a morada final da lógica é o lake da
empresa (Microsoft Fabric). Hoje, levar um fluxo para produção significa reescrevê-lo, e é nessa
reescrita que nascem as diferenças de resultado. A aba SQL mostra o fluxo escrito em SQL e prova que o
código dá o mesmo resultado, para que a passagem ao time de dados seja uma revisão.

Um fluxo com várias saídas é, na prática, vários programas que compartilham etapas. Por isso o centro
da aba é a **saída**: cada uma tem seu próprio código, com só o que existe entre as entradas e ela, e
várias podem ser unificadas num código em que as etapas comuns aparecem uma vez.

Esta versão gera SQL do DuckDB. Spark SQL e T-SQL do Fabric, o notebook e o pacote para o Teams ficam
para a versão seguinte.

## Histórias de usuário

- **Analista:** quero ver em SQL o que construí, entender cada etapa e copiar o código de uma saída.
- **Analista:** quero saber, sem interpretar selos, se aquela saída pode ser levada para o banco.
- **Engenheiro de dados:** recebo um arquivo `.sql`, sem abrir o PRO.DATA, e quero saber o que ele
  produz, de que fontes precisa, o que foi conferido e o que ficou de fora.

## Requisitos funcionais

### Limite da mudança

| ID | Requisito |
|----|-----------|
| RF-2001 | Designer e Dashboard continuam idênticos. Fora da aba SQL, as únicas novidades são o botão **SQL** ao lado de Designer e Dashboard e o item **Ver SQL** no menu do botão direito da caixa, que abre a aba no caminho daquela caixa. |
| RF-2002 | A aba é só leitura. Editar o SQL não altera o fluxo, e a aba nunca grava em banco ou arquivo. |

### Saídas e caminhos

| ID | Requisito |
|----|-----------|
| RF-2003 | São saídas: cada Output Data; cada visual de BI (Chart, KPI, Table, Venn); e cada saída de uma caixa sem nenhuma conexão depois dela. Saída solta de uma caixa com outra saída conectada não entra na lista. |
| RF-2004 | O caminho de uma saída é calculado por **porta**: se ela só usa o J do Join, L e R ficam de fora; se só usa o T do Filter, o F fica de fora. Caixas e etapas desligadas seguem a regra do motor. |
| RF-2005 | Uma saída gera uma única consulta (`WITH ... SELECT`) que roda sozinha num DuckDB limpo. |
| RF-2006 | Várias saídas geram um código unificado: cada etapa aparece uma vez, em ordem de dependência, com as seções "Etapas compartilhadas", "Só de <saída>" e "Saídas". |
| RF-2007 | Uma etapa tem o mesmo nome e o mesmo SQL em qualquer código onde apareça. Editar uma caixa não renomeia as outras etapas. |
| RF-2008 | O SQL acompanha as alterações do fluxo sem executá-lo e sem travar a interface. |

### A tela

| ID | Requisito |
|----|-----------|
| RF-2009 | A tela tem duas colunas: à esquerda, as saídas e a **trilha** do fluxo; à direita, o código. A coluna esquerda segue a largura e o visual dos painéis atuais, com os mesmos ícones, cores de categoria e contagens de linhas das caixas. |
| RF-2010 | A trilha mostra as caixas em ordem vertical, ligadas por linhas com ramificações, em tamanho fixo e com rolagem, de modo que um fluxo grande continue legível sem zoom. Todas as caixas têm sempre o mesmo tamanho e a mesma posição: trocar de saída só acende o caminho e esmaece o resto, sem nada encolher ou pular. |
| RF-2011 | Clicar numa saída troca a seleção. A caixa de marcar ao lado soma outras saídas, e "Todas as tabelas" seleciona as tabelas. Passar o mouse numa saída prevê o caminho sem mudar a seleção. Com uma saída só, o seletor não aparece. |
| RF-2012 | Os visuais ficam recolhidos em "Visuais". Só aparecem primeiro se o fluxo não tiver nenhuma tabela de saída. |
| RF-2013 | Passar o mouse numa caixa da trilha destaca o trecho de código, e vice-versa. Clicar numa caixa do caminho rola até o código dela. Clicar numa caixa fora do caminho mostra o código até aquela caixa, com um aviso que permite fechar. |
| RF-2014 | A trilha explica em português o que cada caixa faz, a partir da configuração real ("Mantém status diferente de INATIVO"). O código fica sempre limpo, e o que se copia é o que se vê. |
| RF-2015 | Etapas usadas por mais de uma saída selecionada têm a marca "usada por N". |
| RF-2016 | **Fluxo completo**: dentro da aba, uma visão só leitura do fluxo nas posições do usuário, inteira, centralizada e sem distorcer a proporção do desenho, com o caminho aceso. Clicar numa caixa volta ao código dela. |
| RF-2017 | Ao abrir a aba com uma caixa selecionada no Designer, a saída mais próxima dela já vem selecionada. A seleção fica guardada por fluxo. |
| RF-2018 | Texto selecionável, navegação por teclado, foco visível, Ctrl+F no código, modo escuro, densidade para telas menores e respeito a "menos movimento". Fluxos de 100 caixas continuam fluidos. |

### Fidelidade

| ID | Requisito |
|----|-----------|
| RF-2019 | Cada saída tem **um estado**: Conferido, Conferido com ressalvas (diz quais), Parcial, Não bate ou Ainda não conferido. Marcas nas etapas só aparecem quando há algo a dizer. |
| RF-2020 | Conferência por etapa: roda o SQL da etapa com as entradas já calculadas pela última execução e compara com a saída da caixa. Não consulta banco nem relê arquivos. |
| RF-2021 | Conferência de ponta a ponta: roda o código da saída a partir das fontes em arquivo. "Conferido" exige as duas conferências. Fontes de banco não são consultadas, e o estado diz isso. |
| RF-2022 | A comparação olha nomes de coluna, tipos compatíveis e o conjunto de linhas com repetições, com tolerância em decimais. A ordem só é exigida quando faz parte do resultado. |
| RF-2023 | Se a tabela for grande demais ou o fluxo tiver mudado, o estado diz "Ainda não conferido", nunca "conferido". "Não bate" mostra quantas linhas e colunas diferem, com exemplos. |
| RF-2024 | A conferência roda em segundo plano, é cancelada quando o fluxo muda e nunca grava nada. |

### Sem tradução

| ID | Requisito |
|----|-----------|
| RF-2025 | Ferramenta sem equivalente (AutoML, Predictor, Train/Test Split) deixa a saída como **Parcial**: a trilha marca o ponto da interrupção e o motivo, e o código vai até a última etapa traduzível, terminando com um comentário claro. O SQL nunca é inventado. |
| RF-2033 | Caixas sem tradução SQL ficam **em vermelho**, sempre, na trilha e no Fluxo completo, mesmo fora do caminho selecionado, com a etiqueta "sem SQL" para não depender só da cor. A ligação que chega até elas no caminho também fica vermelha, e o aviso de interrupção no código também. |
| RF-2026 | Uma saída parcial não impede as outras de rodarem no código unificado. |
| RF-2027 | Ressalvas conhecidas aparecem na etapa e no cabeçalho: dependência da ordem das linhas, colunas vindas dos dados (Cross Tab), amostra aleatória não reproduzível. |

### Entrega

| ID | Requisito |
|----|-----------|
| RF-2028 | **Copiar SQL** copia a seleção atual. **Baixar** oferece a seleção num arquivo ou um `.zip` com um `.sql` por saída mais o unificado. |
| RF-2029 | O arquivo abre com um cabeçalho para quem não conhece o PRO.DATA: fluxo, versão, data, dialeto, saídas, fontes necessárias, estado da conferência, etapas sem tradução e ressalvas. A tela também mostra o dialeto. |

### Segurança

| ID | Requisito |
|----|-----------|
| RF-2030 | Senhas e dados de conexão nunca entram no SQL, nos logs ou nos arquivos. Caminhos absolutos de arquivos vinculados são trocados pelo nome do dataset. |
| RF-2031 | Text Input vira `VALUES` e leva os dados digitados para o SQL: a etapa e o cabeçalho avisam. Nenhum outro dado entra no código. |
| RF-2032 | Identificadores e textos são escapados: colunas com espaços, aspas, acentos e palavras reservadas não quebram nem alteram o SQL; nomes em comentários ficam em uma linha só. Só uma consulta por caixa entra no código: gerar nunca executa um comando. A conferência usa conexão separada, em memória. |

### Proteção do programa (encontradas na revisão da versão)

| ID | Requisito |
|----|-----------|
| RF-2034 | A API local só responde aos endereços do próprio computador, e pedidos que alteram algo vindos de outro site são recusados. Publicar na rede continua sendo escolha explícita em `PRODATA_HOST`. |
| RF-2035 | A caixa SQL e as fórmulas executam um único comando de consulta. Um fluxo recebido de outra pessoa executa ao abrir, e não pode gravar nem alterar nada por ali. |
| RF-2036 | Os resultados dos fluxos são comparados com a versão anterior em teste permanente, cobrindo todas as ferramentas de dados. |

## Critérios de aceite

- No fluxo de demonstração, em dois cliques, o usuário escolhe uma saída, vê o caminho aceso e copia um SQL que roda sozinho num DuckDB limpo.
- Em qualquer combinação de saídas, o código unificado não repete etapas, e cada saída dá o mesmo resultado que seu código individual e que o fluxo.
- "Exportar", que depende do modelo, aparece como Parcial, com a interrupção no Treino e o motivo.
- Para cada ferramenta traduzível, testes com dados incômodos (nulos, vazios, espaços, acentos, chaves repetidas, tabela vazia, nomes estranhos) comparam o SQL com o resultado do motor.
- Um SQL errado de propósito resulta em "Não bate". Nenhum estado afirma uma conferência que não aconteceu.
- Capturas de tela de Designer e Dashboard, antes e depois, são iguais, exceto pelo botão SQL no topo. O item "Ver SQL" só aparece no menu aberto.
- Fluxos de versões anteriores abrem e geram SQL sem migração.

## Fora de escopo

Editar o SQL e refletir no fluxo; escrita em banco; Spark SQL, T-SQL, notebook e pacote para o Teams;
fontes e destinos de produção; linhagem de colunas; destaque do "que mudou"; IA generativa.
