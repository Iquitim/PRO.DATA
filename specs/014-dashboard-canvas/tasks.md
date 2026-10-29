# Tarefas 014

Ordem pensada para entregar valor cedo: primeiro o canvas, a organização automática e
o PNG sobre os visuais de hoje; depois a formatação; por fim os tipos novos.

## Fase 1 — Canvas, organizar e PNG

- [x] T01 Emenda da constituição 1.3.0 (destino `.png`)
- [x] T02 `Dashboard`/`DashItem` no domínio, validação, saneamento de SVG; testes (RF-1405, RF-1406, RF-1441)
- [x] T03 `dashboard/layouts.py` + `POST /api/dashboard/arrange`: automático + 5 layouts prontos, com obstáculos; testes pytest (RF-1460..RF-1463)
- [x] T04 Migração de fluxos sem layout e posicionamento de visuais novos (RF-1406, RF-1408)
- [x] T05 `dashboard.js` + `dash_model.js`: página escalada, modos Visualizar/Editar, arrastar e redimensionar com grade de 8 px (RF-1401..RF-1403)
- [x] T06 Guias de alinhamento, seleção múltipla, alinhar e distribuir, camadas, setas (RF-1403, RF-1404). Copiar, colar e duplicar ficam para T12: um visual é ligado a uma única caixa de BI, então só faz sentido para textos, imagens e formas.
- [x] T07 Desfazer/refazer, estado não salvo, "Visuais fora da página" (RF-1405, RF-1407)
- [x] T08 Botão Organizar com galeria de miniaturas (RF-1460..RF-1463)
- [x] T09 Baixar imagem PNG da página e de um visual; `DesktopApi.save_png` (RF-1450..RF-1453)

## Fase 2 — Formatação

- [ ] T10 Modelos de formato + `GET /api/dashboard/formats`; widgets `color` e `palette` (RF-1410)
- [ ] T11 Painel Formato: cartão, cores com aviso de contraste, legenda, rótulos, eixos (RF-1411..RF-1413)
- [ ] T12 Elementos livres: texto, imagem (com logo pronto), formas; copiar, colar e duplicar (RF-1440..RF-1442, RF-1404)

## Fase 3 — Visuais novos

- [ ] T13 KPI: comparação com meta ou período anterior, variação e tendência no motor; testes (RF-1420..RF-1423)
- [ ] T14 Big number rico e medidor no front (RF-1421..RF-1423, RF-1432)
- [ ] T15 Chart com segunda dimensão: empilhado, agrupado, 100%, multi-linha, área; testes (RF-1430)
- [ ] T16 Pareto: acumulado e destaque no motor, eixo duplo no front; testes (RF-1435)
- [ ] T17 Ferramenta Venn: regiões nos dois modos, geometria proporcional para 2 conjuntos; testes (RF-1436, RF-1437)
- [ ] T18 Dispersão e funil (RF-1431, RF-1432)
- [ ] T19 Ferramenta Table + formatação condicional (RF-1433, RF-1414)
- [ ] T20 Insights e modo tabela com os tipos novos (RF-1434)

## Fechamento

- [ ] T21 Testes Playwright: layout persiste, organizar sem sobreposição, PNG igual à tela
- [ ] T22 Fluxo de demonstração com dashboard montado (big numbers com variação, Pareto, Venn, empilhado, texto e logo)
- [ ] T23 README, guia (novo capítulo "Montando o dashboard" com prints), versão 0.3.0, build e release
