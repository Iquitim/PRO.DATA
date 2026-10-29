# Spec 007 — Caixa de organização na paleta e filtros exploratórios

Status: Implementada · Criada: 2026-10-29 · Corrige: spec 006 (RF-602)

## Contexto

1. **Defeito (spec 006):** ao trocar dois painéis de lugar, o painel deslocado
   saía do documento e passava a ser procurado com `querySelector`, que não o
   encontrava — ele sumia e não podia mais ser reexibido.
2. A caixa de organização (contêiner de etapa) só podia ser criada por atalho,
   botão no canvas ou menu de contexto; o usuário não a encontrou e não havia
   onde customizá-la.
3. A tabela de resultados só tinha busca textual. O analista quer explorar os
   dados com filtros por coluna sem alterar o fluxo.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-701 | Trocar, ocultar e reexibir painéis nunca perde um painel nem o seu conteúdo (correção do RF-602). |
| RF-702 | A paleta tem a categoria **Organização** com o item **Caixa de organização**: clique cria no centro; arrastar cria onde soltar; soltar sobre nós já existentes envolve esses nós. |
| RF-703 | Selecionar uma caixa abre **Configurar** com: nome, descrição, cor (paleta + cor livre), opacidade do fundo, "Ajustar aos nós de dentro", "Desabilitar/Habilitar nós de dentro", lista dos nós contidos e excluir. |
| RF-704 | A descrição da caixa aparece abaixo do título no canvas. |
| RF-705 | Resultados ganham **filtros exploratórios**: lista de condições (coluna, operador, valor) combinadas com E, aplicadas no servidor sobre a saída inspecionada. Não alteram o fluxo nem o arquivo salvo. |
| RF-706 | Operadores por tipo: texto (igual, diferente, contém, não contém, começa com, termina com, está em lista); número/data (=, ≠, >, ≥, <, ≤, entre); todos (é nulo, não é nulo). Valores sugeridos a partir dos valores mais frequentes da coluna. |
| RF-707 | O contador mostra "X de Y linhas"; o **Perfil** reflete os filtros ativos. |
| RF-708 | Atalhos: menu do cabeçalho da coluna com "Filtrar esta coluna…"; clique direito numa célula com "Filtrar = valor" / "Excluir valor". |
| RF-709 | "Criar nó Filter" transforma os filtros ativos em um nó Filter conectado à saída inspecionada (ponte entre exploração e fluxo). |
| RF-710 | Os filtros pertencem à saída inspecionada: cada saída lembra os seus durante a sessão (inclusive ao reexecutar o fluxo) e eles nunca são salvos no arquivo do fluxo. |
| RF-711 | O grupo Organização da paleta segue o mesmo padrão dos demais grupos (recolhível, com seta e contador). |
| RF-712 | Interruptor liga/desliga da caixa (no título, no canvas, e no Configurar). Desligar desativa todos os nós de dentro; ligar reativa. A caixa desligada fica esmaecida, o estado é salvo no fluxo (`Container.disabled`) e um nó arrastado para dentro de uma caixa desligada também é desativado. |

## Critérios de aceite

- Trocar Resultados ↔ Gráficos várias vezes e ocultar/reexibir ambos mantém os dois
  painéis com conteúdo.
- Arrastar "Caixa de organização" sobre os nós Clientes e Limpeza cria uma caixa
  que os envolve.
- Filtro `uf = SP` e `mrr_mensal ≥ 3000` em Clientes mostra a contagem filtrada e o
  Perfil recalculado; "Criar nó Filter" gera `[uf] == 'SP' AND [mrr_mensal] >= 3000`.
