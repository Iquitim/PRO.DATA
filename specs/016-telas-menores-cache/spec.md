# Spec 016 — Telas menores e indicativo do ponto de cache

Status: Implementada · Criada: 2026-10-30

## Contexto

- Em monitores menores (1280 × 720, 1366 × 768, ou telas maiores com escala de 125–150% no Windows)
  os painéis têm tamanho fixo em pixels (300 + 460 + 280) e o canvas fica com cerca de 515 × 290 px.
- O ponto de cache guarda só o resultado da própria caixa; as anteriores não executam enquanto nada
  mudar antes dele. Hoje elas só ficam um pouco apagadas, o que não explica o que aconteceu.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1601 | Os tamanhos dos painéis valem para a janela em que foram escolhidos; numa janela menor encolhem na mesma proporção (com mínimos), sem mudar a preferência salva. Redimensionar a janela reajusta na hora. |
| RF-1602 | **Densidade compacta**: liga sozinha com largura < 1440 ou altura < 800 (fontes, barras, botões e espaçamentos menores). O menu Painéis permite escolher Automática, Confortável ou Compacta. |
| RF-1603 | No dashboard compacto, os botões do cabeçalho mostram só o ícone (o nome fica na dica), menos o principal. |
| RF-1604 | O bloco "Como funciona" do Configurar pode ser recolhido; a escolha é lembrada. |
| RF-1605 | Caixas puladas por um ponto de cache: borda tracejada dourada, fundo dourado claro e o texto "Pulada pelo cache"; a dica diz qual ponto de cache tem o resultado. As ligações entre elas e até o ponto de cache ficam tracejadas em dourado. Selecionar o ponto de cache destaca as caixas que ele dispensa. |
| RF-1606 | O aviso do ponto de cache diz que só o resultado dele é guardado e quantas (e quais) caixas anteriores não executam, com o botão "Mostrar as N puladas" (seleciona no canvas). A barra de status mostra "N pulada(s) pelo cache". |

## Critérios de aceite

- Em 1280 × 720, o canvas ganha espaço em relação à 0.3.5 e nada fica cortado no cabeçalho.
- Cachear o Join da demonstração e executar de novo: 5 caixas aparecem como "Pulada pelo cache"
  (Transações continua executando porque outros visuais usam a saída dela) e a barra de status
  mostra "5 pulada(s) pelo cache".
