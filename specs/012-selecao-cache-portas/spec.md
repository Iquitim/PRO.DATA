# Spec 012 — Seleção múltipla, ponto de cache e dados de entrada por porta

Status: Implementada · Criada: 2026-10-29

## Contexto

- O assistente de fluxo era só um conjunto de regras (2 modelos prontos). Ligá-lo a
  uma IA real exige provedor, chave e aprovação da TI: ele foi **removido** por ora.
- Só uma caixa pode ser selecionada por vez; mover, apagar ou organizar várias
  caixas é repetitivo.
- Entradas lentas (consultas a banco, arquivos grandes) rodam de novo a cada
  execução. O Alteryx resolve isso com "Cache and Run Workflow".
- Clicar numa saída mostra os dados dela; não há como ver o que **chega** numa
  entrada.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1201 | O assistente de fluxo (botão, `Ctrl+K`, rota `/api/workflows/assistant`) deixa de existir. |
| RF-1202 | Seleção múltipla: `Shift`/`Ctrl` + clique adiciona ou tira uma caixa; `Shift` + arrastar no vazio desenha um retângulo de seleção; `Ctrl+A` seleciona todas; `Esc` limpa. |
| RF-1203 | Com várias caixas selecionadas: arrastar move todas; `Delete`, copiar, recortar e colar valem para todas (com as ligações entre elas); soltar dentro de uma caixa de organização desligada desativa as que entraram. |
| RF-1204 | Menu e painel da seleção: alinhar em linha, alinhar em coluna, distribuir, **criar caixa de organização com as selecionadas**, **tirar da caixa de organização** (as caixas saem para baixo dela, mantendo a disposição), habilitar/desabilitar e excluir. |
| RF-1205 | Ponto de cache: "Cachear até aqui" numa caixa executa o fluxo e congela o resultado dela. Nas execuções seguintes, ela entrega o resultado guardado e as caixas anteriores não executam (a não ser que outro ramo precise delas). |
| RF-1206 | O cache é invalidado sozinho quando qualquer caixa anterior ou ligação entre elas muda (configuração, ligação, habilitação). "Atualizar cache" força nova leitura; "Remover ponto de cache" desfaz. |
| RF-1207 | O resultado congelado fica em disco e sobrevive a fechar o programa (modelos de ML só na sessão). |
| RF-1208 | No canvas, o ponto de cache tem um selo; as caixas anteriores aparecem como "em cache" (não executadas). O Inspector mostra quando o cache foi criado. |
| RF-1209 | Clicar numa porta de **entrada** mostra, na tabela, os dados que chegam por ela (a saída da caixa ligada), com o título "Entrada [porta] de <caixa> ← <origem>". Clicar numa saída continua mostrando a saída. |

## Critérios de aceite

- Selecionar 3 caixas com `Shift`+arrastar e movê-las: as 3 se movem juntas; um
  `Ctrl+Z` desfaz o movimento inteiro.
- "Criar caixa com as selecionadas" envolve exatamente as selecionadas.
- Cachear até um Join; executar de novo: as entradas e preparações antes dele não
  executam; mudar o filtro antes do Join e executar: tudo antes dele roda de novo.
- Fechar e reabrir o programa: o ponto de cache continua valendo.
- Clicar na entrada [R] do Join mostra a tabela que chega pela direita.
