// Receitas da Multi-Row Formula (spec 026): a pessoa escolhe o que quer fazer e a fórmula sai pronta.
// A fórmula continua sendo a única regra que o motor executa; a receita só a escreve.

const NUMBER = (v) => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? null : Number(v));

export const RECIPES = [
  {
    id: 'fill', icon: 'arrow-down', name: 'Preencher para baixo', hint: 'O vazio recebe o valor de cima',
    target: 'existing', suffix: 'preenchido', offset: -1, fixedDistance: true,
    formula: (c, k, t) => `IF IsNull([${c}]) THEN [Row-1:${t}] ELSE [${c}] ENDIF`,
    calc: ({ value, before }) => (value === null || value === undefined ? before : value),
    explain: (c) => `Quando [${c}] está vazio, a linha repete o valor de cima, mesmo em vários vazios seguidos.`,
  },
  {
    id: 'diff', icon: 'trending-up', name: 'Diferença', hint: 'Esta linha menos a anterior', numeric: true,
    target: 'new', suffix: 'diferenca', offset: -1,
    formula: (c, k) => `[${c}] - [Row-${k}:${c}]`,
    calc: ({ value, neighbor }) => (NUMBER(value) === null || NUMBER(neighbor) === null ? null : NUMBER(value) - NUMBER(neighbor)),
    explain: (c, k) => `Cada linha mostra [${c}] menos o valor de ${k === 1 ? 'uma linha' : `${k} linhas`} antes.`,
  },
  {
    id: 'pct', icon: 'gauge', name: 'Variação %', hint: 'Quanto mudou sobre a anterior', numeric: true,
    target: 'new', suffix: 'variacao_pct', offset: -1,
    formula: (c, k) => `IF IsNull([Row-${k}:${c}]) OR [Row-${k}:${c}] = 0 THEN Null ELSE ([${c}] - [Row-${k}:${c}]) / [Row-${k}:${c}] * 100 ENDIF`,
    calc: ({ value, neighbor }) => (NUMBER(value) === null || !NUMBER(neighbor) ? null : ((NUMBER(value) - NUMBER(neighbor)) / NUMBER(neighbor)) * 100),
    explain: (c, k) => `Cada linha mostra, em %, quanto [${c}] mudou em relação a ${k === 1 ? 'uma linha' : `${k} linhas`} antes.`,
  },
  {
    id: 'prev', icon: 'arrow-up', name: 'Valor anterior', hint: 'Traz o valor da linha de cima',
    target: 'new', suffix: 'anterior', offset: -1,
    formula: (c, k) => `[Row-${k}:${c}]`,
    calc: ({ neighbor }) => neighbor ?? null,
    explain: (c, k) => `Uma coluna nova com [${c}] de ${k === 1 ? 'uma linha' : `${k} linhas`} antes, para comparar lado a lado.`,
  },
  {
    id: 'next', icon: 'arrow-down', name: 'Próximo valor', hint: 'Traz o valor da linha de baixo',
    target: 'new', suffix: 'seguinte', offset: 1,
    formula: (c, k) => `[Row+${k}:${c}]`,
    calc: ({ neighbor }) => neighbor ?? null,
    explain: (c, k) => `Uma coluna nova com [${c}] de ${k === 1 ? 'uma linha' : `${k} linhas`} depois.`,
  },
  {
    id: 'changed', icon: 'refresh', name: 'Mudou?', hint: 'Marca quando o valor muda',
    target: 'new', suffix: 'mudou', offset: -1,
    formula: (c, k) => `IF IsNull([Row-${k}:${c}]) THEN 'Início' ELSEIF [${c}] == [Row-${k}:${c}] THEN 'Igual' ELSE 'Mudou' ENDIF`,
    calc: ({ value, neighbor, hasNeighbor }) => (!hasNeighbor || neighbor === null || neighbor === undefined ? 'Início' : value === neighbor ? 'Igual' : 'Mudou'),
    explain: (c) => `Cada linha diz se [${c}] mudou em relação à anterior.`,
  },
  { id: 'custom', icon: 'function', name: 'Escrever a minha', hint: 'Fórmula livre, com ajuda para olhar outras linhas' },
];

export const recipeOf = (id) => RECIPES.find((r) => r.id === id) || RECIPES.at(-1);
export const isGuided = (cfg) => recipeOf(cfg.recipe).id !== 'custom';
export const distanceOf = (cfg) => Math.min(100, Math.max(1, Math.round(Number(cfg.distance) || 1)));
export const targetOf = (cfg) => (cfg.target === 'existing' ? cfg.existing : cfg.column) || '';

const AUTO_NAME = new RegExp(`^(nova_coluna|.*_(${RECIPES.filter((r) => r.suffix).map((r) => r.suffix).join('|')}))?$`);

/** Fórmula da receita para a configuração de agora; vazia até escolher a coluna. */
function formulaFor(cfg) {
  const recipe = recipeOf(cfg.recipe);
  if (recipe.id === 'custom' || !cfg.base) return '';
  return recipe.formula(cfg.base, distanceOf(cfg), targetOf(cfg) || cfg.base);
}

/** O que muda na caixa quando um campo da receita muda. Nome digitado pela pessoa nunca é trocado. */
export function recipePatch(cfg, field) {
  const recipe = recipeOf(cfg.recipe);
  if (recipe.id === 'custom') return {};
  const next = { ...cfg };
  if (field === 'recipe') next.target = recipe.target;
  if (field === 'recipe' || field === 'base') {
    if (next.target === 'existing' && next.base && (field === 'base' || !next.existing)) next.existing = next.base;
    if (next.target === 'new' && next.base && AUTO_NAME.test(next.column || '')) next.column = `${next.base}_${recipe.suffix}`;
  }
  if (field === 'target' && next.target === 'new' && next.base && AUTO_NAME.test(next.column || '')) next.column = `${next.base}_${recipe.suffix}`;
  if (field === 'target' && next.target === 'existing' && !next.existing) next.existing = next.base;
  next.expression = formulaFor(next);
  return Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== cfg[k]));
}
