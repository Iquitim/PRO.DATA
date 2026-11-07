# Tarefas — Spec 028 (versão 0.6)

A ordem vai do menor risco ao maior, e cada etapa fecha com testes verdes. Se o prazo apertar, as últimas etapas podem ir para a 0.6.1 sem deixar nada pela metade.

## Etapa 0 — Preparação
- [x] Dica do rótulo só com a saída onde foi aberta (RF-2853)
- [x] Teste de comparação com a 0.5.9 no repositório, para rodar em toda etapa (critério de compatibilidade)

## Etapa 1 — Abertura protegida
- [x] Registro de confiança na pasta de dados, com a biblioteca atual já confiável (RF-2825, RF-2826)
- [x] Modo protegido ao abrir arquivo não confirmado: o servidor recusa executar (RF-2821)
- [x] Faixa com o resumo do que o fluxo faz e os botões Confiar e executar e Só olhar (RF-2822, RF-2823)
- [x] Confiança por conteúdo: arquivo mudado fora do programa volta ao modo protegido (RF-2824)
- [x] Testes em Python e no navegador

## Etapa 2 — Vista Dados
- [x] Telas desenhadas e aprovadas antes de programar: lista em cartões, detalhe, vista vazia e mapa de uso
- [x] Vista no seletor do topo, com lista agrupada, busca e detalhe (RF-2801, RF-2802)
- [x] Cartões com tipo, situação e "usada em N fluxos"; vista vazia didática; "Como funciona" por tipo (RF-2808..2810)
- [x] Detalhe de arquivo: prévia, perfil, tamanho, atualização e vínculo (RF-2803)
- [x] Cadastro de consulta, de API e de conexão dentro da vista (RF-2804); os atalhos do Configurar abrem o mesmo formulário num diálogo
- [x] Dividir `apiEditor` e `queryEditor` em funções de menos de 80 linhas (RF-2851), feito na etapa 6 junto com `formulaEditor`
- [x] Enviar, vincular, cadastrar, editar e excluir só na vista; painel lateral só com busca, arrasto e Abrir em Dados (RF-2805, RF-2806)
- [x] Bateria no navegador cobrindo tudo o que o painel fazia

## Etapa 3 — Onde cada fonte é usada
- [x] Índice das fontes usadas por fluxo da biblioteca, atualizado ao salvar (RF-2811, RF-2814)
- [x] Lista no detalhe da fonte, com clique abrindo a caixa no Designer (RF-2811..2813)
- [x] Mapa de uso no desenho do canvas, com o trajeto aceso ao passar o mouse (RF-2815)
- [x] Aviso ao excluir fonte em uso (RF-2807)
- [x] Teste de desempenho com 500 fluxos

## Etapa 4 — Data Quality
- [x] Telas desenhadas e aprovadas: cartões de regra e esquema "Como funciona"
- [x] Ferramenta com as regras prontas, opções por tipo de coluna e saídas P e F com motivo (RF-2831..2833, RF-2837)
- [x] Regras em cartões com exemplo do que passa e do que falha (RF-2838)
- [x] Esquema "Como funciona" com antes, regras e saídas, e aviso no canvas quando há falhas (RF-2834, RF-2835)
- [x] Tradução para SQL, conferida com o motor (RF-2836)
- [x] Testes com casos de borda de cada regra
- [x] Seção no guia (RF-2839): capítulo 7, "Dados que dá para confiar"
- [x] Valor permitido mais claro (RF-2840): lista digitada com etiquetas e "trazer da coluna", ou uma coluna da entrada L, com SQL, testes e guia

## Etapa 5 — Constantes
- [x] Modelo com os dois alcances, nomes únicos e validação antes de executar (RF-2841, RF-2845)
- [x] Constantes compartilhadas na vista Dados, com cartão, detalhe e mapa de uso (RF-2848, RF-2816)
- [x] Painel do fluxo com os dois alcances (RF-2855)
- [x] Uso em fórmulas, Filter básico, nome do Output Data e parâmetros fixos de API (RF-2842)
- [x] Botão Constante e cor própria no editor de fórmula (RF-2843); dividir `formulaEditor` ficou para a etapa 6 (RF-2851)
- [x] Reexecução só das caixas afetadas e confirmação ao mudar uma compartilhada (RF-2844, RF-2849)
- [x] Valor gravado no fluxo e aviso quando falta o cadastro (RF-2850)
- [~] Tradução para SQL (RF-2846): parcial. O valor entra no código no lugar da referência e o cabeçalho lista "-- Constantes usadas: nome = valor". Trocar num lugar só pede uma CTE de constantes, que fica para depois da 0.6

## Etapa 6 — Fechamento
- [x] `canvas.js` (631) e `app.css` (661) abaixo de 700 linhas (RF-2852)
- [x] Guia, README, `contexto-ia.md` e notas da versão (RF-2847)
- [x] Comparação com a 0.5.9, pytest, ruff, mypy, baterias (604 OK), PDF (38 páginas) e executável
