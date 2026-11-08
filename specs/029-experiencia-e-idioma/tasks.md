# Tarefas — Spec 029 (versão 0.6.1)

Cada etapa visual começa com as telas desenhadas e aprovadas, e fecha com testes verdes nos dois temas e em 1024 px.

## Etapa 0 — Preparação
- [x] Teste de comparação com a 0.6.0 no repositório (`tests/test_compat.py`, fluxos da 0.5.9 e da 0.6.0)
- [x] Bateria de capturas das quatro vistas (claro, escuro, 1024 px) para comparar antes e depois

## Etapa 1 — Data de hoje
- [x] `[#hoje]` como constante do sistema, nome reservado, data injetável nos testes (RF-2995, RF-2997)
- [x] Refazer só quem usa quando o dia muda (RF-2996)
- [x] Botão Constante com "do sistema" e SQL com `Today()` no lugar da referência (RF-2997, RF-2998)

## Etapa 2 — Idioma e nomes
- [x] Regra de idioma no guia e no `contexto-ia.md` (RF-2961)
- [x] Varredura de vazamentos de inglês e teste com lista proibida (RF-2962)
- [x] "Caixa" em todo texto visível e "etapa" para o agrupador; tipos de coluna em português em toda a tela (RF-2912, RF-2921 em parte)
- [x] Telas aprovadas: abas renomeadas e dica de primeira abertura
- [x] Abas Fontes e Resultado, com a dica (RF-2911, RF-2913)

## Etapa 3 — Leitura e cor
- [x] Tokens de tamanho de letra e mínimo de 12 px, com teste (RF-2971)
- [x] Contraste das dicas, do verde e do laranja de aviso no claro, com teste (RF-2972)
- [x] Uma cor de ação principal por tema: no escuro, laranja como o Executar (RF-2963)

## Etapa 4 — Espaço para o fluxo
- [x] Telas aprovadas: modo foco, resultado recolhido e barra do canvas encaixada
- [x] Modo foco (RF-2901), resultado recolhido em tela pequena (RF-2902), barra encaixada (RF-2903), arranjo lembrado (RF-2904)

## Etapa 5 — Tabela de resultado e caixas
- [x] Telas aprovadas: cabeçalho de coluna e caixa com nome longo
- [x] Tipos e vazios no cabeçalho, barrinha só quando informa (RF-2921, RF-2922)
- [x] Nome de arquivo cortado no meio e nome da caixa em até duas linhas (RF-2931, RF-2932)

## Etapa 6 — Configurar
- [x] Telas aprovadas: editor de fórmula grande e listas de opção
- [x] Abrir grande (RF-2941)
- [x] Listas de opção no estilo do programa, com teclado (RF-2942)

## Etapa 7 — Dashboard
- [x] Telas aprovadas: cabeçalho, cartão de indicador e ações
- [x] Cabeçalho único, cartão compacto e ações agrupadas (RF-2951..2953)

## Etapa 8 — Topo, busca e espera
- [x] Telas aprovadas: menus do topo (tema à vista) e busca de comandos
- [x] Menus Arquivo e Exibir, com o tema à vista (RF-2981)
- [x] Busca de comandos com Ctrl+K (RF-2982)
- [x] Esqueletos de carregamento e transições curtas (RF-2991, RF-2992)

## Etapa 9 — Manual dentro do programa
- [x] Tela aprovada: manual ao lado do trabalho, sumário, busca e links interativos
- [x] Geração do manual a partir do `guia.html`, no instalador, com imagens nos dois temas (RF-2983, RF-2984)
- [x] Mostrar onde fica, Experimentar e links de ferramenta (RF-2985..2987)
- [x] Ajuda conforme a tela e capítulos na busca de comandos (RF-2988)
- [x] Teste dos links interativos (RF-2989)

## Etapa 10 — Fechamento
- [x] Guia, README, `contexto-ia.md` e notas da versão
- [x] Comparação com a 0.6.0, pytest, ruff, mypy, baterias, PDF e executável
