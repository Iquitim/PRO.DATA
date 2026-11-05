# Spec 026 — Versão 0.5.9: ordenação, operações por tipo, rótulos e segurança

Status: Implementada · Criada: 2026-11-05 · Versão alvo: 0.5.9

## Contexto (o que foi medido no programa)

| Ponto | Situação encontrada |
|-------|---------------------|
| Order by | A caixa Sort ordena por várias colunas, mas não aparece ao buscar "order by". A Multi-Row depende de um Sort antes dela. |
| Summarize | Oferece todas as operações para qualquer coluna. Somar texto dá erro técnico do motor. |
| Rótulos | Não existem. |
| Destinos de API | `localhost`, `10.x`, `192.168.x` e `169.254.169.254` são chamados sem restrição. Um site público pode redirecionar para a rede interna, e a resposta é lida. |
| Credenciais | Token, senha e o segredo do OAuth seguem em `http` sem criptografia, só com aviso na tela. |
| Vazamento | Se a API ecoar o cabeçalho de usuário e senha, o valor em base64 aparece na mensagem de erro. |
| API Loop | Com limite de 20 chamadas e paginação, foram 2.000 pedidos reais. Com todas as respostas 401, faz todas as chamadas sem parar. |
| HTML | Avisa antes de salvar, mas não tem rótulo, senha nem registro. |

## Requisitos funcionais

### Ordenação e Summarize

| ID | Requisito |
|----|-----------|
| RF-2601 | A Multi-Row Formula tem o campo **Ordenar por**, com uma ou mais colunas: o cálculo e a saída seguem essa ordem, também na aba SQL. Vazio mantém a ordem que chega. |
| RF-2602 | A caixa Sort aparece ao buscar "order by". |
| RF-2603 | No Summarize, a lista de operações segue o tipo da coluna. Texto e data não oferecem soma, média, mediana nem desvio padrão. |
| RF-2604 | Uma configuração inválida de um fluxo antigo não muda sozinha: o campo fica marcado, e a execução explica o que corrigir. |

### Rótulos de confidencialidade

| ID | Requisito |
|----|-----------|
| RF-2611 | Níveis: Público, Interno (padrão), Confidencial e Restrito. O Output Data e o dashboard têm a seleção. |
| RF-2612 | No Excel, o rótulo fica nas propriedades do arquivo, no cabeçalho e rodapé de impressão e na cor da aba, sem tocar nas células. Ao adicionar uma planilha, vale o nível mais restrito. |
| RF-2613 | CSV, Parquet, JSON e Arrow não guardam rótulo: em Confidencial e Restrito, o nível entra no nome do arquivo. |
| RF-2614 | A imagem PNG e o HTML mostram o rótulo em faixa visível. |
| RF-2615 | É um rótulo do PRO.DATA. Não é o rótulo de sensibilidade da Microsoft (Purview), que depende de configuração da empresa. |

### Destinos e credenciais de API

| ID | Requisito |
|----|-----------|
| RF-2621 | O destino é classificado pelo endereço real. Endereço público: livre. Rede interna: só se estiver na lista autorizada. Metadados de nuvem: nunca. |
| RF-2622 | A lista fica em `%ProgramData%\\PRO.DATA\\politica.json`, que exige administrador para alterar, e aceita nomes, curingas (`*.empresa.local`), endereços e faixas (`10.1.0.0/16`). Sem o arquivo, nenhum destino interno é chamado. |
| RF-2623 | A regra vale para cada redirecionamento, para o token do OAuth e para a paginação. |
| RF-2624 | Credencial em `http` é recusada, salvo na própria máquina ou em servidor da lista. |
| RF-2625 | Mensagens de erro ocultam o segredo também em base64 e codificado para URL. |

### API Loop

| ID | Requisito |
|----|-----------|
| RF-2631 | O limite conta pedidos reais, com páginas e novas tentativas. Ao atingi-lo, a caixa para, e o que faltou sai em E, com o motivo. |
| RF-2632 | A caixa para depois de N falhas seguidas (padrão 10; 0 desliga), e o que faltou sai em E. |
| RF-2633 | O esquema mostra quantas linhas entram e o limite, antes de executar. O resultado mostra quantos pedidos foram feitos. |

### HTML e registro

| ID | Requisito |
|----|-----------|
| RF-2641 | O HTML pode ter senha, obrigatória em Confidencial e Restrito, com pelo menos 8 caracteres. Os dados ficam cifrados (AES-256-GCM, chave derivada por PBKDF2), e nada é legível sem ela. A senha não é guardada e não pode ser recuperada. |
| RF-2642 | Toda exportação entra em `logs/exportacoes.log`: data, usuário do Windows, tipo, arquivo, rótulo, linhas, colunas e se tem senha. Nunca os dados. |

### Ajustes pedidos ao conferir a versão

| ID | Requisito |
|----|-----------|
| RF-2651 | Ao arrastar uma ligação, uma caixa ou uma caixa de organização até a borda do canvas, a tela anda sozinha naquela direção, mais rápido quanto mais perto da borda. Ao puxar uma ligação, ela para pouco depois do fim das caixas, para ninguém se perder num canvas vazio. |
| RF-2652 | A Multi-Row Formula começa pela pergunta "O que você quer fazer?", com receitas prontas: preencher para baixo, diferença, variação %, valor anterior, próximo valor e "mudou?". A receita escreve a fórmula; a pessoa só escolhe a coluna. Colunas de texto não aparecem nas receitas numéricas. |
| RF-2653 | "Escrever a minha" mantém a fórmula livre, com botões para inserir `[Row-1:coluna]` e `[Row+1:coluna]`. Fluxos antigos abrem nesse modo, sem mudar nada. |
| RF-2654 | A Multi-Row tem um esquema visual, como o do Join e o do Cross Tab: antes e depois, com os grupos em cores, e passar o mouse no resultado acende as células que ele usou. |
| RF-2655 | Os filtros do dashboard ficam numa faixa própria: valores à mostra como botões e, em número e data, um controle deslizante, sem precisar abrir nada. |
| RF-2656 | Clicar numa barra ou fatia filtra a página por aquele valor; Ctrl+clique soma mais valores; clicar de novo tira. O próprio gráfico continua mostrando as outras categorias apagadas, para dar para trocar de valor. Vale em colunas, barras, rosca e Pareto; nos empilhados, o clique filtra e o gráfico fica só com a categoria. Funciona no programa e no HTML. No HTML, só nas colunas que já têm filtro, porque o arquivo só leva essas colunas. |
| RF-2657 | O rótulo é escolhido numa lista com ícone e cor em cada nível, no dashboard, no diálogo do HTML e no Output Data. |
| RF-2658 | Uma dica por cima da tela diz o que o rótulo faz em cada saída: aparece ao escolher um rótulo que pede cuidado e ao passar o mouse no rótulo e nos botões de exportar, que também ganham um selo. |
| RF-2659 | A imagem PNG e o Excel não têm como pedir senha: a dica diz isso com todas as letras, em vez de deixar a pessoa supor que estão protegidos. |

## Limites assumidos

O programa roda no computador de cada pessoa, sem servidor central: estes controles evitam engano e distração, não um usuário decidido a burlar. A consulta de endereço e a conexão são momentos separados, então um servidor de nomes malicioso poderia responder diferente em cada um. Quem abre um HTML com a senha pode copiar o que vê.

## Critérios de aceite

- Cada caso medido no contexto passa a ser recusado ou limitado (teste).
- APIs públicas seguem funcionando sem nenhuma configuração (teste no navegador, com o IBGE).
- Fluxos antigos abrem e executam, com a regressão contra a 0.4.1 igual (teste).
- O Excel gerado traz o rótulo nas propriedades e na aba, com as células iguais (teste).
- O HTML com senha não contém os dados legíveis, abre com a senha certa e recusa a errada (teste no navegador).

## Fora de escopo

Rótulos da Microsoft (Purview); lista central de servidores; bloquear a cópia dos dados depois de aberto.
