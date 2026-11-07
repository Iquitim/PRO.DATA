# Spec 028 — Versão 0.6: seus dados, num lugar só e de confiança

Status: Proposta · Criada: 2026-11-06 · Versão alvo: 0.6.0

## Por que esta versão

O PRO.DATA existe para tratar dados sem programar e com resultado em que se pode confiar. A 0.5.9 fechou brechas e organizou o código. A 0.6 ataca o que ainda tira essa confiança ou exige conhecimento técnico:

| Ponto | Situação hoje |
|-------|---------------|
| Aba Dados | Cadastra arquivos, bancos e APIs, testa, documenta e mostra prévia num painel lateral estreito. O cadastro de API é a maior tela do programa e vive num diálogo. |
| Uso das fontes | Não há como saber quais fluxos usam uma fonte antes de mudá-la. |
| Fluxo recebido | Um fluxo de outra pessoa executa como qualquer outro. A 0.5.9 travou fórmulas e SQL, mas o programa não avisa que o fluxo veio de fora. |
| Qualidade do dado | Conferir vazios, duplicados, CPF ou faixa de valor exige montar Filter e Formula à mão, e o dado ruim segue em silêncio. |
| Valores repetidos | Um mês de referência ou uma UF digitados em várias caixas: trocar exige achar todas, e uma esquecida dá resultado errado sem aviso. |
| Código | `openApiEditor` (227 linhas), `formulaEditor` (206) e `openQueryEditor` (150); `canvas.js` (785) e `app.css` (778) perto do limite de 800. |

## Princípios que valem para toda a versão

1. **Sem programar:** cada recurso novo se usa com cliques e listas. Escrever fórmula é sempre opcional.
2. **Nada falha em silêncio:** quando algo não pode ser feito ou está errado, a tela diz o quê, onde e como corrigir.
3. **Gerenciar num lugar só:** cadastrar, editar e testar fontes acontece só na vista Dados.
4. **Compatível:** fluxos da 0.5.9 abrem e dão o mesmo resultado, com o mesmo teste de comparação usado na 0.5.9.
5. **Didático e coerente:** o que é novo explica a si mesmo com desenhos e exemplos, no mesmo estilo do que já existe: os esquemas "Como funciona" do Join, Cross Tab e Multi-Row, os cartões de receita da Multi-Row e as cores das categorias do canvas.

## Requisitos

### 1. Vista Dados

| ID | Requisito |
|----|-----------|
| RF-2801 | Uma vista **Dados** é a primeira no seletor do topo, antes de Designer, Dashboard e SQL, com uma separação visual: as fontes valem para todos os fluxos, não só para o aberto. |
| RF-2802 | A vista mostra a lista de fontes à esquerda, agrupada em Arquivos, Bancos, Consultas e APIs, com busca, e o detalhe da escolhida à direita. |
| RF-2803 | O detalhe de um arquivo traz prévia, perfil das colunas (tipo, vazios, distintos), tamanho, data de atualização e, se vinculado, o caminho de origem. |
| RF-2804 | O detalhe de uma consulta ou API traz o cadastro completo, que sai dos diálogos de hoje: campos, teste, prévia da resposta, documentação e anotações. |
| RF-2805 | Enviar arquivo, vincular arquivo, cadastrar banco, consulta e API, editar e excluir acontecem só na vista Dados. |
| RF-2806 | O painel lateral do Designer continua com a lista de fontes, só para buscar e arrastar ao canvas, e um atalho **Abrir em Dados** em cada fonte. Soltar um arquivo no canvas continua funcionando. |
| RF-2807 | Excluir uma fonte em uso avisa quais fluxos e caixas deixam de funcionar (RF-2811), antes de confirmar. |
| RF-2808 | Cada fonte aparece como um cartão com ícone e cor do tipo, linhas e colunas, data da última leitura, situação (ok, com erro, desatualizada) e o selo "usada em N fluxos", ou "sem uso". |
| RF-2809 | A vista vazia, ou com poucas fontes, explica com desenho os quatro tipos de fonte (arquivo, banco, consulta e API) e o que cada um resolve, com um botão para começar por cada um. |
| RF-2810 | Cada tipo de fonte tem um "Como funciona", recolhível como os do Configurar: arquivo → tabela; banco → consulta → tabela; API → pedido → resposta → tabela, reaproveitando os esquemas de API da spec 022. |

### 2. Onde cada fonte é usada

| ID | Requisito |
|----|-----------|
| RF-2811 | O detalhe da fonte lista os fluxos da biblioteca que a usam e, em cada um, as caixas (Input Data, API Loop, consultas). |
| RF-2812 | Clicar numa caixa da lista abre o fluxo no Designer com a caixa selecionada. |
| RF-2813 | A lista diz que considera só os fluxos da biblioteca: um fluxo salvo em outra pasta não aparece. |
| RF-2814 | A busca da lista é rápida com 500 fluxos na biblioteca, abaixo de 1 s. |
| RF-2815 | Além da lista, um **mapa de uso** desenha a fonte à esquerda, ligada aos fluxos e, dentro deles, às caixas que a usam e ao que vem depois delas, até os visuais e as saídas. Usa o mesmo desenho de caixas, cores e ligações do canvas. Passar o mouse num caminho acende o trajeto inteiro. |
| RF-2816 | O mapa também vale para as constantes compartilhadas (RF-2848): mostra onde cada uma entra. |

### 3. Abertura protegida

| ID | Requisito |
|----|-----------|
| RF-2821 | Um fluxo aberto de um arquivo que este computador ainda não confirmou abre em **modo protegido**: nada é executado, nem fontes, APIs ou exportações. |
| RF-2822 | Uma faixa no topo do canvas diz que o fluxo veio de fora e resume o que ele faz: fontes lidas, APIs chamadas, caixas SQL e fórmulas, e pastas onde grava. Cada item da lista seleciona a caixa ao ser clicado. |
| RF-2823 | **Confiar e executar** libera o fluxo e o registra como confiável neste computador. **Só olhar** mantém o modo protegido. Editar o fluxo é sempre possível. |
| RF-2824 | A confiança vale para o conteúdo: se o arquivo mudar fora do programa, ele volta ao modo protegido. As mudanças feitas no próprio programa mantêm a confiança. |
| RF-2825 | Fluxos criados neste computador, o fluxo de exemplo e os que já estavam na biblioteca na atualização para a 0.6 são confiáveis desde o início, para a mudança não incomodar quem já usa. |
| RF-2826 | O registro de confiança fica na pasta de dados do usuário, sem conteúdo dos fluxos, só a identificação de cada um. |

### 4. Caixa de regras de qualidade

| ID | Requisito |
|----|-----------|
| RF-2831 | Uma ferramenta nova, **Data Quality**, recebe uma tabela e uma lista de regras escolhidas em menus, sem fórmula. |
| RF-2832 | Regras prontas: não vazio; sem duplicados (por uma ou mais colunas); CPF válido; CNPJ válido; e-mail com formato válido; número dentro de uma faixa; data válida e dentro de uma faixa, com a opção "não no futuro"; valor dentro de uma lista permitida. Há também uma regra de fórmula livre, opcional. |
| RF-2833 | Saída **P**: linhas que passaram em todas as regras. Saída **F**: as que falharam, com as colunas `regra` e `motivo` (ex.: "CPF inválido em [cpf]"). Com mais de uma falha na mesma linha, os motivos aparecem juntos. |
| RF-2834 | O Configurar mostra um esquema "Como funciona", no estilo do Join e da Multi-Row: a tabela antes, as regras no meio e as saídas P e F depois, com a contagem de cada regra. Com dados executados, usa uma amostra real; sem eles, um exemplo com os nomes configurados. Passar o mouse numa linha reprovada acende a célula e a regra que a reprovaram. |
| RF-2838 | As regras são escolhidas em cartões, como as receitas da Multi-Row: cada cartão tem ícone, nome e um exemplo do que passa e do que falha, como "123.456.789-09 passa; 111.111.111-11 falha". |
| RF-2839 | O guia ganha uma seção com o esquema da caixa e um exemplo de ponta a ponta. |
| RF-2835 | A caixa avisa no próprio canvas quando alguma linha falhou, com a contagem, para o dado ruim nunca seguir despercebido. |
| RF-2836 | Cada regra tem tradução para a aba SQL, conferida com o motor como as demais caixas. A que não tiver tradução diz isso. |
| RF-2837 | As opções seguem o tipo da coluna, como no Summarize: regras de número só aparecem para números, e as de data só para datas. |
| RF-2840 | Na regra "Valor permitido", a lista vem de dois jeitos. **Digitar a lista**: um valor por linha, ou colado de uma coluna do Excel, ou separado por vírgula ou ponto e vírgula; a tela mostra em etiquetas como entendeu cada valor, avisa repetidos e traz os valores que aparecem na coluna (depois de executar) para a pessoa só tirar os errados. **Uma coluna de outra tabela**: a caixa ganha a entrada **L**, que só aparece quando alguma regra pede, e a pessoa escolhe a coluna de L cuja lista vale; vazios em L são ignorados. A tradução para SQL usa uma subconsulta em L. |

### 5. Constantes

Uma constante é um valor com nome, como "mês de referência" ou "meta anual", escrito uma vez e usado em várias caixas: troca-se o valor num lugar só. O nome vem do Alteryx (constantes do fluxo), conhecido de quem usa o PRO.DATA, e não se confunde com nada do programa: a **variável de API**, `{sigla}`, muda a cada linha do API Loop, e o **parâmetro fixo** de API é parte do endereço. Uma constante pode ser o valor de um parâmetro fixo.

| ID | Requisito |
|----|-----------|
| RF-2841 | Há dois alcances, com o mesmo jeito de usar. As **compartilhadas** são cadastradas na vista Dados e valem para todos os fluxos deste computador. As **do fluxo** são cadastradas no próprio fluxo e valem só para ele. Cada uma tem nome, tipo (texto, número ou data), valor e descrição. Duas constantes não podem ter o mesmo nome. A primeira tela explica numa frase: "um valor com nome, como o mês de referência, que você troca num lugar só". |
| RF-2842 | Usam constantes: fórmulas (Formula, Filter, Multi-Row e a regra livre do Data Quality), o valor do Filter básico, o nome do arquivo do Output Data e os parâmetros fixos de API. |
| RF-2843 | O editor de fórmula tem um botão **Constante** que lista os dois alcances e insere a referência, e a referência tem cor própria. A constante tem forma escrita distinta da coluna, para nunca ser confundida com ela. |
| RF-2844 | Trocar o valor de uma constante marca como desatualizadas só as caixas que a usam, e a próxima execução refaz só essas. |
| RF-2845 | Uma constante inexistente ou de tipo errado é apontada antes de executar, na caixa e no painel. |
| RF-2846 | Na aba SQL, a constante vira um valor no começo do código, com o nome dela, para quem receber o SQL trocar num lugar só. |
| RF-2847 | O guia e o `contexto-ia.md` explicam as constantes. O `contexto-ia.md` continua gerado do código. |
| RF-2848 | Na vista Dados, as constantes compartilhadas são um grupo da lista, com cartão e detalhe como as fontes, incluindo o mapa de uso (RF-2816). |
| RF-2849 | Mudar o valor de uma constante compartilhada mostra antes quantos fluxos e caixas ela afeta, com a lista, e pede confirmação. |
| RF-2850 | O fluxo grava o valor de cada constante compartilhada que usa. Aberto num computador sem aquele cadastro, ele roda com o valor gravado e avisa: "constante compartilhada não cadastrada neste computador: usando o valor salvo no fluxo", com um botão para cadastrar. Assim um fluxo enviado a outra pessoa nunca quebra por falta do cadastro. |
| RF-2855 | O painel de constantes do fluxo mostra os dois alcances juntos, cada um com o seu selo, e leva às compartilhadas na vista Dados para editá-las. |

### 6. Arrumação técnica

| ID | Requisito |
|----|-----------|
| RF-2851 | `openApiEditor`, `formulaEditor` e `openQueryEditor` ficam com menos de 80 linhas cada. A divisão do cadastro de API e de consulta acontece junto com a mudança para a vista Dados (RF-2804). |
| RF-2852 | `canvas.js` e `app.css` ficam abaixo de 700 linhas. O limite de 800 por arquivo e o teste de ciclos continuam valendo. |
| RF-2853 | A dica do rótulo de confidencialidade fala só da saída onde foi aberta: o HTML só no HTML. Já feito, aguardando esta versão. |

## Compatibilidade

- Fluxos da 0.5.9 abrem sem mudança. As constantes são um campo novo e opcional do fluxo.
- **Volta para a 0.5.9:** um fluxo com constantes aberto na 0.5.9 perde as constantes, e as fórmulas que as usam dão erro. O guia avisa, e o programa grava a versão no arquivo para mostrar esse aviso no futuro.
- O registro de confiança começa com todos os fluxos que já estão na biblioteca (RF-2825).
- Quem cadastrava fontes pelo painel lateral passa a fazer isso na vista Dados. O atalho e uma página do guia mostram onde ficou.

## Critérios de aceite

- Comparação com a 0.5.9: o mesmo fluxo, nos mesmos dados, dá o mesmo resultado em todas as saídas (teste, como na 0.5.9).
- Um fluxo aberto de arquivo não confirmado não executa nada, nem ao apertar Executar, até a confirmação. Mudar o arquivo fora do programa o devolve ao modo protegido (teste no navegador).
- Data Quality: cada regra pronta separa P e F certos em casos de borda, como CPF com máscara, data inválida, vazio e espaço (teste). O SQL dá o mesmo resultado que o motor (teste).
- Constantes: trocar um valor refaz só as caixas que o usam; uma constante inexistente é apontada antes de executar (teste).
- Onde é usado: com 500 fluxos na biblioteca, a lista aparece em menos de 1 s (teste de desempenho).
- Vista Dados: tudo o que o painel fazia continua possível, agora na vista; arrastar uma fonte ao canvas continua funcionando (bateria no navegador).
- Pytest, ruff, mypy, baterias no navegador, guia em PDF sem páginas vazias e executável testado.

## Fora de escopo

Agendar execuções; comparar versões de um fluxo; dashboard em PDF ou com várias páginas; assistente de IA dentro do programa; rótulos da Microsoft (Purview); servidor central; dashboards publicados num servidor; rótulo de confidencialidade por fonte.

## Riscos e como tratar

| Risco | Tratamento |
|-------|------------|
| Quem já usa procura o cadastro no painel antigo | Atalho **Abrir em Dados**, página no guia e nota da versão |
| A abertura protegida incomodar | Só para arquivo de fora não confirmado; a biblioteca existente já começa confiável |
| Uma constante compartilhada mudar o resultado de vários fluxos sem a pessoa perceber | Confirmação com a lista do que é afetado (RF-2849) e mapa de uso (RF-2816) |
| Um fluxo enviado a outra pessoa quebrar por falta de uma constante compartilhada | O fluxo leva o valor e avisa (RF-2850) |
| Regras de qualidade crescerem sem fim | Começar com as oito do RF-2832 e a fórmula livre; novas regras só com pedido real |
| Versão grande demais | Entregar na ordem das tarefas: cada etapa funciona sozinha e pode ficar para a 0.6.1 sem deixar nada pela metade |
