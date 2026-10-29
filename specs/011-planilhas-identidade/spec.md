# Spec 011 — Abas e recorte de planilhas; identidade visual Grupo Protege

Status: Implementada · Criada: 2026-10-29

## Contexto

1. Planilhas costumam ter várias abas e tabelas que não começam em A1 (título,
   logotipo ou colunas de apoio antes dos dados). A escolha de aba existia, mas só
   aparecia depois de abrir a prévia; não havia como pular colunas.
2. O programa será usado no Grupo Protege e deve seguir a identidade visual da
   empresa (cores, logotipo, fonte).

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1101 | Ao enviar um Excel pela aba Dados (ou soltá-lo no canvas), a prévia abre sozinha para escolher a aba e o recorte. |
| RF-1102 | A prévia mostra as abas da planilha como guias clicáveis acima da tabela; a escolhida vira a aba do Input Data. |
| RF-1103 | "Pular linhas iniciais" no Excel conta desde a linha 1 da planilha (cabeçalho na linha 4 → pular 3); no CSV, desde o início do arquivo. |
| RF-1104 | Nova opção "Pular colunas iniciais" (CSV e Excel) descarta as N primeiras colunas da tabela lida; pular todas é erro explícito. |
| RF-1105 | A detecção automática de delimitador/decimal do CSV ignora as linhas puladas. |
| RF-1106 | Identidade Grupo Protege: barra superior azul-marinho com filete dourado, escudo oficial (variante clara sobre fundo escuro), fonte Open Sans, cor de destaque marinho (azul claro no tema escuro), favicon, cabeçalho do Dashboard com a marca, ícone do executável/instalador e editora "Grupo Protege". |
| RF-1107 | A paleta de gráficos usa o azul e o dourado da marca nas posições de mesma família de cor e passa no validador (daltonismo, contraste, luminosidade) nos dois temas. |

## Critérios de aceite

- Excel com abas "Capa" e "Dados", título em A1 e tabela em A4 com uma coluna de
  apoio: escolher "Dados", pular 3 linhas e 1 coluna lê só a tabela.
- CSV com título e linha em branco: pular 2 linhas detecta `;` corretamente.
- A barra superior mostra o escudo e "Grupo Protege"; o ícone do `.exe` é o escudo.
