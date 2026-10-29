# Spec 009 — Edição no canvas, fonte única de dados e destinos escolhidos pelo usuário

Status: Implementada · Criada: 2026-10-29

## Contexto

Pedidos do usuário após a versão 0.2.0:

1. Excluir uma caixa exige selecionar e apertar Delete ou abrir um menu; falta
   um ícone de lixeira na própria caixa.
2. Não há copiar/colar de caixas, e o menu do botão direito tem poucas opções.
3. Exportações vão sempre para `storage/exports` e fluxos sempre para
   `storage/workflows`; o usuário quer escolher as pastas.
4. Consultas SQL só existem dentro do nó *Database Input*. O usuário quer
   escrever a consulta na aba **Dados**, junto com os arquivos, e usar uma
   única ferramenta de entrada que leia qualquer fonte cadastrada ali.

## Histórias de usuário

- **H1** — Como analista, quero excluir uma caixa com um clique no ícone dela.
- **H2** — Como analista, quero copiar, recortar e colar caixas (inclusive uma
  etapa inteira) e ter as ações mais comuns no botão direito.
- **H3** — Como analista, quero escolher a pasta onde o Output Data grava o
  arquivo e salvar/abrir o fluxo em qualquer pasta (rede, OneDrive, projeto).
- **H4** — Como analista, quero cadastrar consultas de banco na aba Dados e
  usá-las no **Input Data** do mesmo jeito que uso um arquivo.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-901 | Cada caixa no canvas mostra, ao passar o mouse ou quando selecionada, um botão de lixeira que a exclui (com desfazer). A tecla Delete continua funcionando. |
| RF-902 | `Ctrl+C` copia a caixa selecionada; com uma caixa de organização selecionada, copia a etapa com os nós de dentro e as ligações entre eles. `Ctrl+X` recorta. `Ctrl+V` cola com novos IDs, perto do cursor (ou deslocado do original), preservando configurações e ligações internas. |
| RF-903 | A área de transferência sobrevive à troca de fluxo e ao reinício do programa (fica no navegador do usuário, nunca no arquivo do fluxo). |
| RF-904 | Botão direito numa caixa: Configurar, Executar até aqui, Ver resultados, Copiar, Recortar, Colar, Duplicar, Renomear, Habilitar/Desabilitar, Excluir. No canvas vazio: Colar aqui, Adicionar ferramenta, Nova caixa de organização, Ajustar à tela. Na caixa de organização: Renomear, Ajustar, Ligar/Desligar, Copiar etapa, cores, Excluir (mantendo ou com os nós). |
| RF-905 | O Output Data ganha o campo **Pasta de destino** (vazio = pasta padrão de exportações). No aplicativo de desktop, o botão "Escolher…" abre o seletor de pastas do Windows. A pasta precisa existir; o nome do arquivo continua saneado e a extensão segue o formato. |
| RF-906 | Após exportar para uma pasta escolhida, o Inspector mostra o caminho completo e, no desktop, oferece "Abrir pasta". |
| RF-907 | **Salvar como…** grava o fluxo num arquivo `.prodata.json` escolhido pelo usuário; **Abrir arquivo…** abre um `.prodata.json` de qualquer pasta. Depois disso, `Ctrl+S` salva no mesmo arquivo. Fluxos abertos recentemente de fora da biblioteca aparecem no diálogo Abrir. |
| RF-908 | A aba Dados ganha a seção **Consultas de banco**: cada consulta tem nome, conexão, tabela **ou** SQL livre e a opção "Reaproveitar resultado". É criada e editada num editor com prévia; senhas continuam só no cofre do Windows. |
| RF-909 | O **Input Data** lê qualquer fonte da aba Dados: arquivos e consultas aparecem num único seletor, agrupados. Opções de leitura de arquivo só aparecem para arquivos. Arrastar uma consulta da aba Dados para o canvas cria um Input Data. |
| RF-910 | Editar uma consulta na aba Dados invalida o cache dos Input Data que a usam; sem "Reaproveitar resultado", o banco é consultado a cada execução (mesma regra do RF-508). |
| RF-911 | O *Database Input* sai da paleta. Fluxos antigos continuam executando, e o Inspector oferece "Converter para Input Data", que cria a consulta equivalente na aba Dados. |
| RF-912 | Consultas continuam somente leitura (RF-507). Excluir uma conexão avisa quantas consultas dependem dela. |

## Critérios de aceite

- Clicar na lixeira de uma caixa a remove; `Ctrl+Z` a traz de volta.
- Copiar uma etapa com 3 nós ligados e colar gera 3 nós novos, ligados entre
  si, dentro de uma nova caixa; o original não muda.
- Um Output Data com pasta `D:\Relatorios` grava `D:\Relatorios\resultado.xlsx`;
  pasta inexistente gera erro claro no nó, sem gravar nada.
- "Salvar como" em `D:\Projetos\vendas.prodata.json` cria o arquivo; reabrir o
  programa e usar "Abrir arquivo" o carrega igual.
- Uma consulta criada na aba Dados aparece no seletor do Input Data; executar
  traz as linhas do banco; mudar o SQL na aba Dados e executar de novo traz o
  resultado novo.
- O arquivo `queries.json` não contém senhas.
