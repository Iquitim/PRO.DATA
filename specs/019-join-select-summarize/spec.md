# Spec 019 — Versão 0.4.1: Join com seleção de colunas, Summarize visual, moda e desvio padrão

Status: Implementada · Criada: 2026-10-30 · Versão: 0.4.1

## Contexto

| # | Pedido | Situação encontrada |
|---|--------|---------------------|
| 1 | Join: escolher se as chaves vêm dos dois lados, só da esquerda ou só da direita | Desde a 0.4.0 o J sempre mantém as duas chaves (antes da 0.4.0, só a da esquerda). |
| 2 | Join com um "Select" embutido, como no Alteryx | Para escolher, renomear ou converter colunas do J era preciso um Select depois do Join. |
| 3 | Summarize com esquema visual, como o Join | Só Cross Tab, Transpose e Join têm esquema. |
| 4 | Moda e desvio padrão nas funções da Formula e no Summarize | Não existem. |
| 5 | Fluxo salvo na 0.3.8 abre na 0.4.1? | Sim: o formato do fluxo não mudou; campos novos de cada ferramenta recebem o padrão ao abrir. O J do Join ganha a chave da direita (comportamento da 0.4.0), a menos que se escolha "Só da esquerda". |

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1901 | Join → "Colunas da chave no J": **As duas** (padrão, como na 0.4.0), **Só da esquerda** (como até a 0.3.8) ou **Só da direita**. Quando sobra só um lado, a chave fica com o nome original (sem prefixo). |
| RF-1902 | Join → tabela "Colunas do J" no Configurar, igual à do Select: cada coluna da saída J com a origem (L ou R), manter/descartar, renomear, converter tipo e reordenar (arrastar ou setas), com Todas/Nenhuma/Inverter/Ordem original. As saídas L e R não mudam. |
| RF-1903 | Summarize → esquema "Como funciona": antes (amostra das linhas, colorida por grupo) → depois (uma linha por grupo com cada agregação calculada na amostra). Passar o mouse num grupo destaca as linhas de origem. |
| RF-1904 | Summarize: operações **Moda** (valor mais frequente; empate → o menor) e **Desvio padrão** (amostral). |
| RF-1905 | Formula: `Mode(valor1, valor2, …)` e `StdDev(valor1, valor2, …)` entre colunas da mesma linha (vazios ignorados). |
| RF-1906 | Um fluxo salvo na 0.3.8 abre e executa sem erro (teste com o fluxo de demonstração da 0.3.8). |

## Critérios de aceite

- Join com "Só da esquerda" e chaves de mesmo nome: J igual ao da 0.3.8 (teste).
- Join com "Só da direita": a chave da direita aparece sem prefixo (teste).
- Join descartando, renomeando e convertendo uma coluna do J, com ordem escolhida (teste).
- Summarize com Moda e Desvio padrão por grupo (teste).
- `Mode([a], [b], [c])` e `StdDev([a], [b], [c])` (teste).
- Fluxo da 0.3.8 executa sem erros (teste).
- Configurar do Join mostra a tabela de colunas do J com a origem; Summarize mostra o esquema (navegador).
- Guia com as imagens refeitas na 0.4.1.

## Implementação

| Item | Onde |
|------|------|
| Lado das chaves e Select do J | `nodes/transform.py` (`keys_mode`, `fields`, `order`, `_keep_key_side`), `nodes/prep.py` (`apply_select`, compartilhado com o Select) |
| Tabela "Colunas do J" | `web/js/fields.js` (`joinColumns` prevê as colunas do J com a mesma regra do motor; etiqueta L/R), `web/js/inspector.js` (redesenha ao mudar chaves, lado ou prefixo) |
| Esquema do Summarize | `web/js/explainers.js` (`summarize`), cores por grupo em `web/css/app.css` |
| Moda e desvio padrão | `nodes/transform.py` (`mode`, `std`), `engine/formula.py` (`Mode`, `StdDev` via `list_mode` e `list_stddev_samp`) |
| Compatibilidade | `tests/data/fluxo_0_3_8.prodata.json` (fluxo de demonstração gerado pelo código da 0.3.8) |

Na tabela "Colunas do J", a ordem e as regras usam o nome da coluna como sai do Join (com o prefixo
das repetidas), antes de renomear — igual ao Select.

Testes: `tests/test_v041.py` e a bateria de navegador da versão. Imagens do guia refeitas na 0.4.1.
