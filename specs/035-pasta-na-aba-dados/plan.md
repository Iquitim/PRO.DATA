# Plano da spec 035

## Cadastro

`ingestion/folders.py` define `FolderSource` (herda as opções de leitura de `ReadOptions`: nome, pasta, padrão, coluna do arquivo) e `FolderSources`, guardado em `<datasets>_pastas.json`, ao lado da lista de arquivos vinculados. O `DatasetStore` ganha `folders`, então o motor, a linha de comando e os subfluxos já o recebem sem fiação nova.

A listagem dos arquivos (`folder_files`) e o empilhamento (`read_folder`) saíram da caixa Input Folder para esse módulo; a caixa antiga e o Input Data usam o mesmo código.

## No motor

- O Input Data reconhece `folder:<id>`: lê os arquivos com as opções do cadastro e o limite da caixa.
- `DatasetStore.signature("folder:<id>")` junta o resumo do cadastro com nome, tamanho e data de cada arquivo. Com isso, o cache da caixa, a assinatura dos subfluxos e a dos pontos de cache acompanham a pasta sem código próprio.
- Na aba SQL, a pasta vira uma tabela de destino, como as fontes de banco.
- A abertura protegida lista a pasta como `padrão em pasta` e marca quando ela não está cadastrada.

## API

`/api/folders`: `GET` (com a situação: arquivos, mais recente, pasta sumida), `POST`, `PUT /{id}`, `DELETE /{id}` (só esquece o cadastro) e `POST /preview`, que lista os arquivos, marca os de colunas diferentes (até 60 conferidos) e devolve as primeiras linhas empilhadas, lendo um pedaço de até 20 arquivos.

## Tela

- `folder_sources.js`: cadastro em duas colunas, com o desenho "arquivos → 1 tabela" e a lista ao vivo; visão geral do detalhe (números, arquivos, qualidade e prévia); adicionar ao fluxo; esquecer; e a conversão da caixa antiga.
- `data_stats.js`: números e barras de qualidade, agora usados pelo detalhe do arquivo e da pasta.
- Tipo `folder` em `data_sources.js` (situação no cartão, filtro "Com problema"), no menu Adicionar, no painel Fontes, no seletor do Input Data e no "Como funciona".
- `io.input_folder` fica `hidden`: sai da paleta e da contagem de ferramentas, continua executando, e o Configurar oferece "Levar para a vista Dados". Se já houver uma fonte com a mesma pasta e padrão, a conversão a reutiliza.

## Dois modos no cadastro

Ao adicionar, a pessoa escolhe **Uma tabela só** (a fonte `folder:<id>` descrita acima) ou **Um por arquivo**. O segundo usa `POST /api/folders/link-each`, que lista os arquivos do padrão e chama `DatasetStore.link_many`: cada arquivo vira um arquivo vinculado, os já vinculados são pulados e nome repetido ganha número. A tela depois cria (ou reaproveita) uma pasta da organização com o nome da pasta, com `ensureFolder`, e move as fontes novas para ela. O cadastro desenha os dois casos, sugere "Um por arquivo" quando há colunas diferentes, marca os arquivos já vinculados e avisa que esse modo vale só para os arquivos de hoje.

## Guia

Seção "Uma pasta inteira" no capítulo Trazendo dados, com `dados-pasta.png`; o capítulo do fechamento usa `dados-pasta-cadastro.png` e explica a conversão. A contagem passa a 43. O print `explain-folder.png` foi retirado.
