# Tarefas — Spec 020: aba SQL

## Motor

1. Bloco, saídas e caminho por porta, com testes de porta não usada (RF-2003, RF-2004).
2. Nomes estáveis e escape de identificadores e textos (RF-2007, RF-2032).
3. `to_sql` no `@tool`, com a tradução caindo em "sem tradução" por padrão (RF-2025).
4. Tradução das ferramentas de maior uso, cada uma com teste de equivalência: Input Data, Text Input, Browse, Select, Filter, Formula, Cleanse, Sort, Summarize, Join, Union (RF-2031).
5. Tradução das demais: Unique, Sample, Record ID, Running Total, Text To Columns, Cross Tab, Transpose, Append Fields, SQL, Database Input, Output Data (RF-2027).
6. Consulta por trás dos visuais (RF-2003).
7. Consulta única, código unificado, preâmbulo de macros e cabeçalho (RF-2005, RF-2006, RF-2029).
8. Conferência por etapa e de ponta a ponta, em segundo plano e cancelável (RF-2019 a RF-2024).
9. Teste de honestidade: SQL errado de propósito resulta em "Não bate" (RF-2023).
10. Rotas da API, `.zip` e testes de segurança (RF-2028, RF-2030).

## Interface

11. Capturas de referência de Designer e Dashboard, antes de qualquer mudança (RF-2001).
12. Botão SQL, visão `sql` e item "Ver SQL" (RF-2001).
13. Lista de saídas, com seleção, soma, prévia e visuais recolhidos (RF-2011, RF-2012).
14. Trilha, com faixas automáticas, explicações, contagens e marcas (RF-2009, RF-2010, RF-2014, RF-2015).
15. Código com destaque, sincronia com a trilha e saída temporária (RF-2013).
16. Estado da saída, interrupção na trilha e caixas sem tradução em vermelho (RF-2019, RF-2025, RF-2026, RF-2033).
17. Fluxo completo (RF-2016).
18. Copiar e baixar (RF-2028).
19. Seleção guardada, abertura pela caixa selecionada e atualização ao editar (RF-2008, RF-2017).
20. Teclado, tema escuro, telas menores e desempenho com 100 caixas (RF-2018).

## Encerramento

21. Baterias de navegador novas e antigas, e comparação das capturas (RF-2001).
22. Ruff, mypy e pytest limpos; fluxo da 0.3.8 gerando SQL.
23. README, guia e PDF; versão 0.5.0.
24. Build e teste do executável extraído do zip.
25. Commit, push e release, cada um com o OK do usuário.
