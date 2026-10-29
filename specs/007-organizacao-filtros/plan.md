# Plano 007

## Correção de painéis
`layout.js` guarda referências fixas aos elementos dos painéis no `initLayout` e
`apply()` move cada painel para sua posição (ou depósito) sem `querySelector`.

## Caixa de organização
- Paleta: grupo "Organização" fixo no topo, com item arrastável
  (`application/x-prodata-container`). O canvas cria a caixa no ponto de soltura;
  se houver nós sob a área, a caixa os envolve (`fitContainer`).
- `Container` ganha `description` e `opacity` (modelo Pydantic, com padrão, sem
  quebrar arquivos existentes).
- `inspector.js`: painel de caixa quando `selection.containerId` está definido;
  `main.js` abre a aba Configurar também para caixas.

## Filtros exploratórios
- API: `GET /api/results/...?filters=<json>` com
  `[{column, op, value, value2}]`. `engine/results.py` monta expressões Polars
  (whitelist de operadores, coerção pelo tipo da coluna, erro 400 para coluna
  inexistente). Com filtros, o perfil é calculado sobre a visão filtrada.
- `results.js`: barra de filtros (chips editáveis), popover de condição, menu de
  cabeçalho e de célula, "Criar nó Filter" (gera expressão no estilo do motor de
  fórmulas e insere o nó ligado à porta inspecionada).
