# Spec 022 — Versão 0.5.6: caixas de volta, API pública no exemplo e API didática

Status: Implementada · Criada: 2026-11-05 · Versão alvo: 0.5.6

## Contexto (o que foi verificado no código)

| # | Pedido | Situação encontrada |
|---|--------|---------------------|
| 1 | Caixas sem cor e sem aspecto de caixa | **Defeito da 0.5.5.** A reescrita do tema apagou as regras que ligam cada família à sua cor. No escuro, o fundo da caixa ficou quase igual ao do canvas. |
| 2 | Consumo de uma API pública no exemplo | O fluxo de demonstração só lê arquivos. A API de localidades do IBGE é pública, sem chave, em português e tem as UFs usadas na demonstração. |
| 3 | API mais didática | O editor de API e o API Loop são só formulários. Cross Tab, Transpose, Join e Summarize já têm o esquema "Como funciona". |

## Requisitos funcionais

### Caixas do fluxo

| ID | Requisito |
|----|-----------|
| RF-2201 | Cada caixa mostra a cor da família: faixa lateral, ícone cheio, borda e sombra, nos dois temas, com o tamanho de antes. |
| RF-2202 | Um teste falha se uma família perder a cor, se o contraste da caixa cair ou se o CSS usar uma variável inexistente. |

### API pública no exemplo

| ID | Requisito |
|----|-----------|
| RF-2211 | O fluxo de demonstração ganha a etapa "5 · API pública do IBGE": estados, API Loop com os municípios de cada estado, contagem por estado, junção com os clientes e gráfico de MRR por região. |
| RF-2212 | As duas APIs do exemplo já vêm cadastradas na aba Dados, sem segredo, e podem ser abertas para estudo. |
| RF-2213 | **Abrir o exemplo não chama a internet.** A etapa espera o clique em Executar e diz isso na tela. Vale para uma nova opção de qualquer API: "Só chamar quando eu clicar em Executar". |
| RF-2214 | Sem rede, só essa etapa falha, com mensagem clara. As demais etapas e o dashboard continuam iguais. |
| RF-2215 | Quem já tem a demonstração salva recebe a etapa nova sem perder o que alterou nela. |
| RF-2216 | O gráfico da etapa fica fora da página do dashboard: o dashboard do exemplo não muda, nem depende de rede. |

### Cadastro de API didático

| ID | Requisito |
|----|-----------|
| RF-2221 | "Começar de um exemplo" preenche o formulário com APIs públicas que mostram cada caso: lista simples, `{coluna}`, resposta aninhada com paginação e registro único. |
| RF-2222 | "O que será enviado" mostra o pedido montado enquanto se digita, com cores para endereço, parâmetros e `{coluna}`, e a credencial sempre oculta. |
| RF-2223 | Autenticação e Páginas têm um esquema próprio, com os nomes configurados: onde a credencial vai, e a sequência de pedidos até parar. |
| RF-2224 | Antes de testar, o painel direito explica o caminho pedido, resposta e tabela com um exemplo. |
| RF-2225 | Depois de testar, o painel mostra a resposta real ao lado da tabela que ela gerou. Passar o mouse num campo destaca a coluna, e clicar numa lista da resposta escolhe de onde vêm as linhas, ou qual lista abrir em linhas. |
| RF-2226 | A amostra da resposta só existe na tela: não é gravada e é cortada em tamanho. |

### API Loop didático

| ID | Requisito |
|----|-----------|
| RF-2231 | O API Loop ganha o esquema "Como funciona", como o Cross Tab: tabela de entrada, chamadas montadas com os valores destacados, saída com as colunas de origem e da resposta. Passar o mouse num valor destaca o caminho dele. |
| RF-2232 | Usa a amostra real da entrada e, depois de executar, das respostas. Sem isso, mostra um exemplo e diz que é exemplo. |
| RF-2233 | Mostra as saídas R e E com as contagens, com clique para ver as linhas, e avisa quando falta coluna na entrada ou quando valores iguais evitam chamadas. |

## Critérios de aceite

- Caixas com cor por família nos dois temas (teste de CSS e de navegador).
- Abrir o exemplo não faz nenhuma chamada de API, e os testes automáticos nunca saem para a rede (teste).
- Executar o exemplo chama o IBGE de verdade e mostra o resultado (teste no navegador).
- Sem rede, só a etapa 5 fica com erro (teste).
- Uma demonstração salva e alterada recebe a etapa sem perder as alterações (teste).
- A amostra da resposta é cortada e não vai para arquivos (teste).
- O esquema do API Loop e o clique na resposta funcionam (teste no navegador).

## Fora de escopo

Assistente passo a passo separado do editor; catálogo de APIs públicas além dos exemplos; dados do IBGE embutidos no programa.
