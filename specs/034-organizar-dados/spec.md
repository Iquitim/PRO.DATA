# Spec 034: organizar a vista Dados

A vista Dados agrupa as fontes pelo tipo técnico (arquivos, consultas, APIs…). Quem trabalha numa área pensa por
assunto: "tudo de numerário", "tudo de vendas". Com 30 ou 40 fontes, a lista por tipo fica longa e sem significado, e
o nome do arquivo (`extrato_cc_0412_v3.xlsx`) raramente diz o que ele é.

## Histórias

- Como analista, quero agrupar as fontes por assunto, misturando arquivos, consultas e APIs da mesma área.
- Como analista, quero dar a uma fonte um nome que diga o que ela é, sem quebrar os fluxos que a usam.
- Como quem recebe a base de outra pessoa, quero ler numa frase o que a fonte contém, de onde vem e quem cuida dela.
- Como responsável pela biblioteca, quero achar rápido o que está com problema e o que ninguém usa.

## Requisitos

### Pastas

| ID | Requisito |
|---|---|
| RF-3401 | A pessoa cria pastas com nome e cor. Uma pasta reúne fontes de qualquer tipo. Há um nível de pasta, sem subpastas. |
| RF-3402 | Cada fonte fica em uma pasta ou em "Sem pasta". Arrastar o cartão até a pasta move a fonte; o menu da fonte e o detalhe também movem. |
| RF-3403 | Ctrl+clique marca várias fontes. Uma barra mostra quantas estão marcadas e move ou fixa todas de uma vez. Arrastar uma marcada leva todas. |
| RF-3404 | A lista alterna entre "Pastas" e "Tipos". Em "Tipos", fica como antes. A escolha é lembrada. |
| RF-3405 | Pasta vazia mostra onde soltar. Excluir uma pasta devolve as fontes para "Sem pasta" e não apaga nenhuma fonte. |
| RF-3406 | Pastas recolhem e expandem, e o estado é lembrado. |
| RF-3407 | Com cinco fontes ou mais e nenhuma pasta, a lista sugere criar a primeira, com um exemplo do que é uma pasta. A sugestão pode ser dispensada. |

### Nome de exibição

| ID | Requisito |
|---|---|
| RF-3410 | Qualquer fonte pode ganhar um nome de exibição, editado no título do detalhe. O nome original (o do arquivo, da consulta, da constante) continua igual, e nenhum fluxo muda. |
| RF-3411 | Com nome de exibição, a tela mostra o nome original logo abaixo, em letra menor, na lista, no detalhe e no painel lateral. |
| RF-3412 | O nome de exibição aparece também no painel Dados do Designer, na escolha de fonte do Input Data e como nome da caixa criada a partir da fonte. |
| RF-3413 | Apagar o nome de exibição volta ao nome original. |

### Descrição

| ID | Requisito |
|---|---|
| RF-3420 | Cada fonte tem descrição (o que contém, de onde vem, quando atualiza) e responsável. Sem descrição, o detalhe convida a escrever uma, com um exemplo. |
| RF-3421 | A busca encontra fontes pelo nome de exibição, pelo nome original, pela descrição, pelo responsável e pela pasta. |

### Achar o que importa

| ID | Requisito |
|---|---|
| RF-3430 | Acima da lista, filtros com contagem: Todas, Com problema (arquivo não encontrado, conexão sem senha, segredo faltando, carga parada), Sem uso e Fixadas. |
| RF-3431 | A lista ordena por nome, por mais usadas ou pelas mais recentes. "Mais recentes" junta a data de modificação do arquivo e a última vez que a fonte foi aberta na vista Dados, neste computador. |
| RF-3432 | Fontes fixadas aparecem num grupo próprio no topo, com estrela no cartão. |

### Guarda

| ID | Requisito |
|---|---|
| RF-3440 | A organização fica num arquivo da pasta de dados do computador, não nos fluxos. Não guarda dados das fontes nem segredos. |
| RF-3441 | Excluir uma fonte apaga a organização dela. |
| RF-3442 | Nomes, descrições e responsáveis são texto puro, com limite de tamanho, e nunca viram HTML na tela. |

### Guia

| ID | Requisito |
|---|---|
| RF-3450 | O guia e o Manual explicam pastas, nome de exibição e descrição, com captura da lista organizada e do detalhe. |

## Fora do escopo

- Subpastas e etiquetas múltiplas por fonte.
- Pastas compartilhadas entre computadores.
- Renomear de verdade o arquivo de uma fonte.
