# Spec 010 — Abas de fluxos, editor de fórmulas e fechamento seguro

Status: Implementada · Criada: 2026-10-29 · Corrige: spec 009 (RF-907)

## Contexto

1. **Defeito (spec 009):** no executável, "Salvar como…" não abria o diálogo. O
   filtro de arquivo tinha um ponto na descrição ("Fluxos do PRO.DATA"), que o
   pywebview recusa; o erro não chegava ao usuário.
2. Só um fluxo fica aberto por vez; o usuário quer abas.
3. Ao excluir uma caixa de BI, o gráfico continuava no Dashboard até a próxima
   execução completa.
4. O campo de fórmula é um texto simples: sem cores, sem sugestões, e a fonte
   desenha `!=` como "≠" (ligadura), o que confunde quem vai digitar.
5. Fechar um fluxo com alterações só oferecia "Descartar"; fechar a janela do
   programa não perguntava nada.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1001 | "Salvar como…" e "Abrir arquivo…" abrem os diálogos nativos no executável; qualquer falha do diálogo vira mensagem visível. |
| RF-1002 | Uma barra de abas mostra os fluxos abertos (nome, indicador de não salvo, fechar). Cada aba guarda o próprio fluxo, resultado da última execução, desfazer/refazer, seleção e posição do canvas. |
| RF-1003 | Novo fluxo, abrir da biblioteca e abrir arquivo abrem em nova aba; se o fluxo já está aberto, a aba dele é ativada. Uma aba vazia e intocada é reaproveitada. |
| RF-1004 | As abas salvas (biblioteca ou arquivo) são reabertas ao iniciar o programa, com a última ativa selecionada. |
| RF-1005 | Visuais de BI de caixas excluídas ou desativadas somem do Dashboard e do painel de gráficos imediatamente. |
| RF-1006 | O campo de expressão (Formula, Filter) colore a sintaxe enquanto se digita: colunas, funções, palavras de controle (IF/THEN/ELSE/ENDIF), operadores lógicos (AND/OR/NOT), operadores de comparação e aritméticos, textos e números. Colunas inexistentes e parênteses sem par são destacados. |
| RF-1007 | Autocompletar: ao digitar letras, sugere funções e palavras-chave; ao digitar `[`, sugere as colunas da entrada. Setas navegam, Enter/Tab aceitam, Esc fecha, `Ctrl+Espaço` abre. Funções entram com os parênteses e o cursor dentro. |
| RF-1008 | Dentro dos parênteses de uma função, uma dica mostra a assinatura e destaca o argumento atual. |
| RF-1009 | Assistente de inserção: botões de coluna, função (por categoria, com descrição e exemplo, com busca) e operadores (`=`, `!=`, `>`, `>=`, `<`, `<=`, `AND`, `OR`, `NOT`, `IF…ENDIF`), inseridos na posição do cursor. |
| RF-1010 | O código é exibido sem ligaduras: `!=`, `>=` e `<=` aparecem como digitados. `!=` é o operador de diferente sugerido em todo lugar (`<>` continua aceito). |
| RF-1011 | O catálogo de funções (nome, assinatura, categoria, descrição, exemplo) vem da API; todo exemplo documentado é uma expressão válida. |
| RF-1012 | Fechar uma aba com alterações pergunta **Salvar / Não salvar / Cancelar**. |
| RF-1013 | Fechar a janela do programa com qualquer aba alterada pergunta o mesmo (Salvar tudo / Fechar sem salvar / Cancelar). No navegador, vale o aviso padrão do navegador. |

## Critérios de aceite

- No executável, Salvar como abre o diálogo do Windows e grava o arquivo.
- Abrir dois fluxos, editar o primeiro, trocar de aba e voltar: a edição e o
  desfazer do primeiro continuam lá; o segundo não foi afetado.
- Excluir o nó Chart: o gráfico some do Dashboard sem executar de novo.
- Digitar `IF [uf] != 'SP' THEN Rou` sugere `Round`; Enter insere `Round()`
  com o cursor dentro; `[` lista as colunas.
- Fechar a janela com uma aba alterada mostra o diálogo; "Cancelar" mantém o
  programa aberto.
