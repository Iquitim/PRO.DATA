# Spec 025 — Versão 0.5.8: conectores, animações discretas e guia

Status: Implementada · Criada: 2026-11-05 · Versão alvo: 0.5.8

## Contexto (o que foi verificado no código e no PDF)

| Ponto | Situação encontrada |
|-------|---------------------|
| Conectores | Curvas cinza finas, iguais em todo o fluxo, sem indicar a direção. |
| Animações | Só o brilho da caixa em execução. Nada mostra o dado andando nem a conclusão de uma caixa. |
| Guia em PDF | 42 páginas, cerca de 10 muito vazias: capturas altas demais, legendas separadas das imagens e sobras de uma linha. Faltam ferramentas novas, e há informações desatualizadas. |

## Requisitos funcionais

### Conectores

| ID | Requisito |
|----|-----------|
| RF-2501 | O fio faz uma transição da cor da família da caixa de origem para a da caixa de destino, nos dois temas. |
| RF-2502 | O fio tem uma pequena seta na chegada, mostrando a direção. Fios tracejados (modelo e cache) e o fio selecionado mantêm o significado. |
| RF-2503 | Ao passar o mouse, o fio engrossa e as portas das duas pontas acendem. |

### Animações (discretas)

| ID | Requisito |
|----|-----------|
| RF-2511 | Durante a execução, o dado corre pelos fios que chegam à caixa em execução. Nada se move depois que a execução termina. |
| RF-2512 | Ao terminar, cada caixa dá um pulso curto na cor de "pronto". |
| RF-2513 | Um fio novo se desenha da origem ao destino, e uma caixa nova surge com um leve crescimento. Abrir um fluxo não anima nada. |
| RF-2514 | Quem desativou animações no sistema não vê nenhuma destas. Em fluxos com mais de 300 ligações, o fluxo animado nos fios é desligado para preservar o desempenho. |

### Guia

| ID | Requisito |
|----|-----------|
| RF-2521 | O guia fala primeiro do que muda para quem usa: antes e depois, casos de uso e um primeiro fluxo guiado com os dados de exemplo. Só afirma o que o produto faz: nada de números de ganho inventados ou depoimentos. |
| RF-2522 | Cada capítulo principal diz o que a pessoa vai conseguir fazer e traz um "Experimente" com passos reais no fluxo de demonstração. |
| RF-2523 | Nenhuma página fica só com um título, uma legenda ou uma sobra de poucas linhas. Uma verificação mede os vazios do PDF gerado. |
| RF-2524 | O conteúdo fica atualizado com a versão: todas as ferramentas, APIs, HTML, filtros, referências e limitações. |

## Critérios de aceite

- Fios com a cor das famílias e seta, nos dois temas (teste no navegador).
- Durante uma execução real, há animação nos fios da caixa em execução; ao terminar, nenhuma (teste no navegador).
- Abrir um fluxo não dispara animação de entrada; criar uma caixa e uma ligação, sim (teste no navegador).
- Redesenhar um fluxo grande continua rápido (medido no navegador).
- O PDF passa na verificação de vazios.

## Fora de escopo

Animações contínuas com o programa parado; fio animado ao passar o mouse; reorganizar as caixas automaticamente.
