# Spec 035: pasta de arquivos como fonte da aba Dados

A regra do PRO.DATA é: o que vem de fora é cadastrado na aba Dados, e o fluxo lê com o Input Data. A caixa Input Folder
(spec 033) foge dela: guarda o caminho da pasta e o padrão do nome dentro do fluxo. Por isso a pasta não aparece no mapa
de uso, no filtro "Com problema", na organização da spec 034, nem tem prévia ou qualidade das colunas. E é a fonte do
fechamento do mês, que roda pelo Agendador do Windows: justamente onde saber de onde vêm os dados mais importa.

## Histórias

- Como analista, quero cadastrar a pasta do fechamento uma vez e usar em vários fluxos.
- Como analista, quero ver, antes de executar, quais arquivos entram, e qual deles tem colunas diferentes.
- Como quem já usa a caixa Input Folder, quero levar a pasta para a aba Dados sem refazer o fluxo.

## Requisitos

### Cadastro

| ID | Requisito |
|---|---|
| RF-3501 | A aba Dados tem um tipo novo de fonte, "Pasta de arquivos": nome, pasta (caminho completo), padrão do nome (`vendas_*.xlsx`), coluna com o nome do arquivo e, para Excel, a aba. |
| RF-3502 | No cadastro, a lista dos arquivos que casam com o padrão aparece enquanto a pessoa digita, com tamanho e data, e avisa quando nenhum casa. No programa instalado, um botão escolhe a pasta. |
| RF-3503 | A pasta é só lida: o PRO.DATA nunca grava, move ou apaga nada nela. Vale a mesma lista de extensões dos arquivos, sem subpastas, até 500 arquivos, ignorando os temporários do Excel (`~$`). |
| RF-3504 | Excluir a fonte só esquece o cadastro: a pasta e os arquivos ficam intactos. |
| RF-3505 | Ao adicionar uma pasta, a pessoa escolhe entre **Uma tabela só** (os arquivos empilhados numa fonte, e os que chegarem depois entram sozinhos) e **Um por arquivo** (cada arquivo vira uma fonte separada). O cadastro explica com um desenho o que cada opção faz e sugere "Um por arquivo" quando os arquivos têm colunas diferentes. |
| RF-3506 | Em "Um por arquivo", cada arquivo que casa com o padrão é vinculado onde está, sem cópia. Arquivo já vinculado não é vinculado de novo, e nome repetido ganha um número. Por padrão, as fontes novas entram numa pasta da organização (spec 034) com o nome da pasta, que a pessoa pode mudar ou desligar. |
| RF-3507 | "Um por arquivo" é feito uma vez: arquivos que chegarem depois não entram sozinhos, e o cadastro diz isso antes de vincular. |

### Detalhe

| ID | Requisito |
|---|---|
| RF-3510 | A visão geral mostra quantos arquivos entram, o mais recente, a lista dos arquivos com tamanho e data, e marca os que têm colunas diferentes do primeiro. |
| RF-3511 | A prévia mostra as primeiras linhas já empilhadas, com a coluna do nome do arquivo, e a qualidade das colunas. |
| RF-3512 | O cartão e o detalhe avisam quando a pasta não existe mais ou quando nenhum arquivo casa com o padrão; os dois casos entram no filtro "Com problema". |
| RF-3513 | "Como funciona" desenha vários arquivos virando uma tabela só. |

### No fluxo

| ID | Requisito |
|---|---|
| RF-3520 | O Input Data lê a pasta como qualquer fonte: arrastar do painel Fontes, escolher na lista ou "Adicionar ao fluxo" no detalhe. |
| RF-3521 | A caixa refaz quando entra, sai ou muda um arquivo da pasta, ou quando o cadastro muda; senão, aproveita o resultado guardado. Vale também para subfluxos e para a linha de comando. |
| RF-3522 | A pasta tem mapa de uso, nome de exibição, pasta da organização e descrição, como as outras fontes. |
| RF-3523 | Num computador sem o cadastro, a caixa explica que a pasta precisa ser cadastrada na aba Dados. A abertura protegida lista a pasta entre as fontes que o fluxo lê. |

### A caixa antiga

| ID | Requisito |
|---|---|
| RF-3530 | A caixa Input Folder sai da paleta. Fluxos que a usam continuam executando igual. |
| RF-3531 | No Configurar dela, o botão "Levar para a aba Dados" cria a fonte com a mesma configuração e troca a caixa por um Input Data no mesmo lugar, com os mesmos fios. |
| RF-3532 | A contagem de ferramentas no guia, no Manual e no contexto para IA passa a ser 43. |

### Guia

| ID | Requisito |
|---|---|
| RF-3540 | O guia e o Manual explicam a pasta de arquivos na seção de arquivos, com captura do detalhe e do cadastro, e o capítulo do fechamento passa a usar a fonte em vez da caixa. |

## Fora do escopo

- Subpastas.
- Copiar os arquivos para dentro do PRO.DATA.
- Ler a pasta pela aba SQL: lá ela vira uma tabela de destino, como as fontes de banco.
