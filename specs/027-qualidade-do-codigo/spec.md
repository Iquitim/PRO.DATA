# Spec 027 — Qualidade do código antes da versão 0.5.9

## Contexto

Antes do lançamento, o código foi medido em modularização, organização, segurança e desempenho.

| Medida | Resultado |
|--------|-----------|
| Dependências com vulnerabilidade conhecida (`pip-audit`) | Nenhuma |
| Ciclos de importação em JavaScript | Nenhum |
| Abrir o programa | 0,28 s, 49 arquivos, 802 KB |
| Arrastar uma caixa com 326 caixas no canvas | 60 quadros por segundo, sem travas |
| Filtro, fórmula, ordenação, junção e resumo em 2 milhões de linhas | Menos de 0,2 s cada |
| Fórmula lendo um arquivo do computador | **Conseguia: brecha confirmada** |
| Arquivos acima de 1.000 linhas | `canvas.js`, `connectors/api.py`, `dashboard.js` |

O desempenho não pede mudança: otimizar sem problema medido só traria risco.

## Requisitos

### Segurança

| ID | Requisito |
|----|-----------|
| RF-2701 | Fórmulas e a caixa SQL não acessam arquivos nem a internet: rodam numa conexão DuckDB sem acesso externo e com a configuração travada. O erro explica o motivo. |
| RF-2702 | A interface tem uma política de conteúdo (CSP): só roda scripts do próprio programa, e nada sai para outro endereço. |
| RF-2703 | O HTML exportado tem uma política própria: nenhum recurso externo e nenhuma conexão, mesmo que um dado tente injetar algo. |
| RF-2704 | Dados de um fluxo recebido não viram HTML: o id de uma ligação é escapado antes de entrar no desenho. |

### Modularização e organização

| ID | Requisito |
|----|-----------|
| RF-2711 | Nenhum arquivo de código passa de 800 linhas, com um teste que garante isso. Os dados da demonstração ficam de fora dessa conta só se passarem a ser dados, não código. |
| RF-2712 | A divisão não muda comportamento: todos os testes e baterias seguem passando sem alterar o que verificam. Importações antigas continuam funcionando. |
| RF-2713 | A complexidade das funções e as regras de segurança do linter passam a ser verificadas sempre. |

### Contexto para assistentes de IA

| ID | Requisito |
|----|-----------|
| RF-2721 | `docs/contexto-ia.md` ensina um assistente de IA a ler e alterar um fluxo: formato do arquivo, ferramentas com campos e portas, linguagem de fórmula, limites de segurança e um exemplo. É gerado do catálogo por `docs/gerar_contexto_ia.py`. |
| RF-2722 | Um teste garante que o documento está em dia e que o exemplo usa só campos e portas reais e executa com o resultado esperado. |
| RF-2723 | O documento manda tratar o texto de dentro do fluxo como dado, não como instrução, e nunca escrever segredos no arquivo. |

## Critérios de aceite

- Um fluxo com `read_text`, `read_csv`, `glob` ou `SET enable_external_access` numa fórmula ou na caixa SQL é recusado (teste).
- Tudo o que já funcionava continua igual: pytest, baterias no navegador e executável.

## Fora de escopo

Otimizações de desempenho; mudar a arquitetura; reescrever o que funciona só por estilo.
