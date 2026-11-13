# Plano da spec 034

## Dados

`OrganizationStore` (`services/organization.py`) guarda `organizacao.json` na pasta de dados:

- `folders`: lista ordenada de `{id, name, color}`, com cores fechadas (azul, verde, âmbar, roxo, vermelho, cinza) que viram tokens do tema na tela.
- `sources`: por chave da vista Dados (`file:…`, `query:…`, `api:…`, `jira:…`, `jiraconn:…`, `conn:…`, `const:…`), `{folder, label, description, owner, pinned}`.

Entradas vazias somem ao salvar. O arquivo estragado não trava a vista: começa vazio e registra no log. Textos passam por limpeza de caracteres de controle e têm limite de tamanho. Nenhum fluxo lê este arquivo.

## API

`/api/organization`: `GET`; `POST /folders`; `PUT /folders/{id}`; `POST /folders/{id}/move`; `DELETE /folders/{id}` (as fontes voltam para "Sem pasta"); `PUT /sources {keys, changes}` em lote; `POST /sources/forget {keys}`, chamado depois de excluir uma fonte. Toda resposta é a organização inteira.

## Tela

- `organization.js`: estado (`store.organization`), chamadas, janela de pasta com cor e prévia, menu "Mover para".
- `data_folders.js`: a lista. Modo Pastas ou Tipos, ordem, filtros com contagem, grupo Fixadas, pastas recolhíveis com menu, arrastar e soltar, Ctrl+clique com barra de marcadas, menu do botão direito, dica da primeira pasta. Sem nenhuma pasta, o modo Pastas continua agrupando por tipo.
- `data_meta.js`: título editável (nome de exibição), linha do nome original, chip da pasta, fixar, bloco de descrição e responsável.
- `store.js`: `sourceKey(valor)` e `displayName(chave)`; `sourceLabel` usa o nome de exibição na caixa nova.
- Painel Fontes do Designer agrupa por pasta quando há pastas; a escolha do Input Data mostra "Rótulo (arquivo)"; a paleta de comandos mostra o nome de exibição.
- "Mais recentes" junta a data do arquivo e a última abertura na vista, guardada no navegador deste computador.

## Guia

Seção "Organizar em pastas" no capítulo Trazendo dados, com três capturas novas (`dados-pastas`, `dados-nome-exibicao`, `dados-nova-pasta`) feitas por `docs/guia/imagens/organizar_dados.py`, e o alvo `organizar` no "Mostrar onde fica".
