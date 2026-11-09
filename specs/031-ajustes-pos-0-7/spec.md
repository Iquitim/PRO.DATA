# Spec 031: ajustes depois da 0.7

Três pontos vistos no uso da 0.7.0.

## Requisitos

| ID | Requisito |
|---|---|
| RF-3101 | Em janela reduzida, o botão Baixar do dashboard mostra os dois ícones sem apertar. O selo "Parado" não cobre os botões do gráfico. |
| RF-3102 | Excluir conexão de banco, conexão do Jira ou API com credencial apaga o segredo do cofre do Windows, e a tela diz isso antes de excluir. |
| RF-3103 | A consulta do Jira é montada em passos numerados: o que trazer, de quais projetos, filtros e conferência. |
| RF-3104 | Os projetos têm busca. Só aparecem na tela os primeiros resultados, e o texto diz quantos faltam. |
| RF-3105 | Tipos e status aparecem só depois de escolher um projeto, e somente os que existem nos projetos escolhidos. Os status ficam agrupados em A fazer, Em andamento e Concluído. |
| RF-3106 | Marcar um tipo restringe os status aos daquele tipo. Escolha que deixa de existir no projeto sai da seleção. |
| RF-3107 | Se o Jira não informar os status de um projeto, a tela mostra os do Jira inteiro e avisa. |
| RF-3108 | Uma frase em português resume o que será trazido. JQL e campos personalizados ficam em Mais opções. |
| RF-3109 | A cada atualização, o Jira informa quais demandas atendem à consulta agora. O que excluiu, mudou de filtro ou passou do período sai da tabela, inclusive com JQL à mão e em histórico e comentários. |
| RF-3110 | Demanda que volta à consulta sem ter mudado, como depois de recuperar uma permissão, é buscada de novo. |
| RF-3111 | Se a resposta não trouxer as chaves, nada é removido naquela carga. |

## Fora do escopo

Limite de chamadas, retomada e colunas das tabelas continuam como na spec 030.
