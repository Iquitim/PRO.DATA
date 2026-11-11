# Constituição do PRO.DATA

Princípios não negociáveis do projeto. Toda spec, plano e PR deve ser compatível
com eles; quando um princípio precisar mudar, altere este arquivo primeiro, em PR
separado, com justificativa.

Versão: 1.5.0 · Ratificada: 2026-10-28 · Emendada: 2026-11-09 (princípio IV: cofre do SO, conectores somente leitura; destinos escolhidos pelo usuário — spec 009; imagens PNG do dashboard — spec 014; arquivos de origem vinculados — spec 017; pasta lida, modelo de Excel e estado das caixas — spec 033)

## I. Spec antes do código (SDD)

Mudanças de comportamento começam em `specs/NNN-nome/`:

1. `spec.md` — o **quê** e o **porquê**: histórias de usuário, requisitos
   funcionais numerados (`RF-xxx`), critérios de aceite verificáveis.
   Sem decisões de implementação.
2. `plan.md` — o **como**: arquitetura, contratos (API, formatos), riscos.
3. `tasks.md` — tarefas pequenas e ordenadas, cada uma ligada a um `RF`.

Correções de bug e refatorações sem mudança de comportamento dispensam spec,
mas não dispensam teste.

## II. Motor desacoplado da interface

- O motor (`prodata.engine`, `prodata.nodes`, `prodata.ingestion`) não importa
  FastAPI nem conhece HTTP. Deve ser utilizável a partir de um script Python.
- A API (`prodata.api`) é uma camada fina: valida entrada, chama serviços,
  serializa saída.
- O frontend fala apenas com a API REST documentada em `/docs`.

## III. Ferramentas são declarativas

Cada ferramenta (nó) declara em um único lugar: metadados, portas, modelo de
configuração Pydantic e função de execução. O formulário do Inspector é gerado
a partir desse modelo — não existe formulário escrito à mão por ferramenta,
exceto widgets especializados reutilizáveis.

## IV. Segurança por padrão

- Nenhum caminho de arquivo vindo do cliente é usado sem ser resolvido e
  confinado ao diretório de dados (`resolve_inside`). Exceção única: destinos
  escolhidos explicitamente pelo usuário — a pasta do Output Data, arquivos de
  fluxo `.prodata.json` e imagens `.png` exportadas do dashboard — desde que o caminho seja absoluto, o diretório já
  exista, a extensão seja fixa e o nome do arquivo seja saneado.
- Arquivos de origem **vinculados** pelo usuário (spec 017) podem ser lidos fora do diretório de
  dados: caminho absoluto, arquivo existente no momento do vínculo, extensão da lista permitida.
  São somente leitura: o PRO.DATA nunca grava, move ou apaga o arquivo vinculado.
- A pasta do Input Folder e o modelo de Excel do Output Data (spec 033) seguem a mesma regra dos arquivos
  vinculados: caminho absoluto escolhido pelo usuário, existente, extensão da lista permitida, somente
  leitura. A abertura protegida mostra os dois a quem recebe o fluxo.
- O que uma caixa guarda entre execuções (modelos de ML, tabelas do Compare Runs) fica na pasta de dados do
  computador, num caminho montado com o ID do fluxo e da caixa. Nunca vai no arquivo do fluxo, e um arquivo
  de modelo só é lido dali, depois de conferido o seu SHA-256.
- Uploads têm lista de extensões permitidas e tamanho máximo.
- Segredos (senhas de banco, chaves de API) nunca são salvos em workflows,
  arquivos do projeto ou logs, nem devolvidos pela API. Ficam no cofre do
  sistema operacional (`keyring`) ou em variáveis de ambiente.
- Conectores de banco são somente leitura, salvo spec explícita em contrário.
- CORS restrito às origens configuradas.

## V. Falhas são explícitas

- Nenhum `except Exception: pass`. Erros são registrados em log e devolvidos ao
  usuário com mensagem acionável.
- Um nó com falha marca seus descendentes como `skipped`, nunca os executa com
  entradas faltantes.
- Ciclos no grafo são erro de validação, não comportamento indefinido.

## VI. Honestidade funcional

Recursos simulados são rotulados como tal na interface e na documentação
(ex.: provedor de IA `local-heuristic`). Métricas de modelo são calculadas em
dados de validação, não nos dados de treino.

## VII. Testes e qualidade

- `uv run pytest` e `uv run ruff check` passam antes de qualquer merge (CI).
- Todo requisito funcional do motor tem ao menos um teste automatizado.
- Tipagem estática em todo código Python novo (`mypy` sem erros em `src/`).
