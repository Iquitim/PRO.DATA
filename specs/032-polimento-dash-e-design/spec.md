# Spec 032: polimento do dashboard, do designer e das fórmulas

Pontos vistos no uso da 0.7.1.

## Correções

| ID | Requisito |
|---|---|
| RF-3201 | Ligar ou desligar uma opção num painel rolado não desloca a tela. A causa era o campo invisível do interruptor, que não acompanhava a rolagem e fazia o navegador rolar a página inteira ao receber o foco. |
| RF-3202 | O dashboard não treme quando a barra de rolagem aparece e some. A área reserva o espaço da barra e só é redesenhada quando a largura muda. |

## Dashboard

| ID | Requisito |
|---|---|
| RF-3210 | Ao mover, o item encaixa quando o espaço até o vizinho fica igual a um espaço já usado na mesma faixa, ou quando fica no meio de dois vizinhos. Os espaços iguais são marcados com a medida. |
| RF-3211 | Ao redimensionar, o item encaixa na largura ou altura de outro. Todos os itens com a mesma medida são marcados. Alt continua soltando o encaixe. |
| RF-3212 | "Copiar formato" no painel e no menu de contexto liga o pincel: cada clique em outra caixa aplica o formato, e Esc, clique no vazio ou o mesmo botão encerra. Cada aplicação é um passo de desfazer. |
| RF-3213 | O pincel leva só os campos que existem nas duas caixas. Não leva título, subtítulo, nomes trocados, títulos e limites de eixo, que são do próprio visual. Campo que a origem deixou no padrão volta ao padrão no destino. |
| RF-3214 | A lista de cor por categoria fica sempre à vista nos gráficos com mais de uma cor possível, mostrando a cor que está em uso. |
| RF-3215 | Mudar a cor de uma categoria passa o gráfico para "Uma cor por categoria" e mantém a paleta anterior nas demais, em "Demais categorias". |
| RF-3216 | Funil e Pareto respeitam a cor de cada categoria. Linha e área de série única avisam que têm uma cor só. |

## Valores vazios

| ID | Requisito |
|---|---|
| RF-3220 | Fórmulas têm `IsNotNull(valor)` e `IsNotEmpty(valor)`. |
| RF-3221 | `[coluna] = Null`, `== Null`, `!= Null` e `<> Null` funcionam como o teste de nulo, em vez de nunca serem verdadeiros. |
| RF-3222 | A caixa Filter tem "está vazio" (nulo ou em branco) e "está preenchido", também no SQL gerado. |
| RF-3223 | O filtro de lista do dashboard tem "Só preenchidos", que marca tudo menos (vazio). Não aparece quando a lista veio cortada. |

## Designer

| ID | Requisito |
|---|---|
| RF-3230 | A barra do canvas tem Navegar e Selecionar. Em Navegar, tudo funciona como antes. |
| RF-3231 | Em Selecionar, arrastar no vazio desenha o retângulo de seleção; Shift ou Ctrl soma à seleção atual. O botão do meio continua movendo a tela. |
| RF-3232 | As teclas H e V trocam de modo, e a escolha fica guardada. |

## Fora do escopo

Copiar o tamanho junto com o formato. "Mesma largura e altura" continua em Alinhar.
