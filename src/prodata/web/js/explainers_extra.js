// Esquemas "Como funciona" das caixas da spec 033. Como nos do Join e do Summarize: usam a configuração e,
// depois de executar, uma amostra dos dados da própria caixa. Só ilustram: o resultado de verdade é o do motor.

import { api } from './api.js';
import { fmt, h } from './dom.js';
import { icon } from './icons.js';
import { nodeResult, store } from './store.js';

// Tabela pequena e seta do explainers.js, entregues por ele a cada desenho.
let mini;
let arrow;

const show = (v) => (v === null || v === undefined ? '—' : typeof v === 'number' ? fmt.number(v) : String(v));
const short = (text, n = 26) => (String(text).length > n ? `${String(text).slice(0, n - 1)}…` : String(text));

/** Linhas de uma saída da própria caixa, se ela já executou. */
function ownRows(n, port = 'out', limit = 8) {
  if (!nodeResult(n.id)?.anchors?.[port]) return Promise.resolve(null);
  return api.results(store.workflow.id, n.id, port, { limit }).then((p) => p.rows).catch(() => null);
}

/** Linhas que chegam numa entrada da caixa. */
function inputRows(n, port = 'in', limit = 40) {
  const edge = store.workflow.edges.find((e) => e.target === n.id && e.targetHandle === port);
  if (!edge || !nodeResult(edge.source)?.anchors?.[edge.sourceHandle]) return Promise.resolve(null);
  return api.results(store.workflow.id, edge.source, edge.sourceHandle, { limit }).then((p) => p.rows).catch(() => null);
}

const chip = (name, text, { link = null, tone = null } = {}) => h('span', {
  class: ['x-chip', tone && `x-chip-${tone}`], dataset: link ? { link } : undefined, title: text,
}, icon(name, 13), h('span', {}, text));
const chips = (title, items) => h('div', { class: 'x-chips' }, title ? h('div', { class: 'x-title' }, title) : null, items);
const stat = (value, label, tone) => h('div', { class: ['x-stat', tone && `x-stat-${tone}`] }, h('strong', {}, value), h('span', {}, label));

// ------------------------------------------------------------------ Input Folder

async function inputFolder(n, cfg) {
  const column = (cfg.file_column || '').trim();
  const real = nodeResult(n.id)?.extra?.folder_files;
  const rows = real ? await ownRows(n, 'out', 200) : null;
  const pattern = cfg.pattern || '*.xlsx';
  const files = real?.length ? real : ['01', '02', '03'].map((m) => pattern.replace('*', `2026-${m}`).replace(/\*/g, ''));
  let table;
  if (rows?.length) {
    const others = Object.keys(rows[0]).filter((c) => c !== column).slice(0, 2);
    // Uma linha de cada arquivo, para o esquema mostrar a pilha e não só o primeiro.
    const picked = column ? files.slice(0, 4).flatMap((f) => rows.filter((r) => r[column] === f).slice(0, 2)) : rows.slice(0, 6);
    table = mini('Depois: tudo numa tabela só', [...(column ? [{ text: column, kind: 'to' }] : []), ...others.map((c) => ({ text: c }))],
      (picked.length ? picked : rows.slice(0, 6)).map((r) => [
        ...(column ? [{ text: show(r[column]), link: `f:${r[column]}`, kind: 'from' }] : []),
        ...others.map((c) => ({ text: show(r[c]), link: column ? `f:${r[column]}` : null })),
      ]));
  } else {
    table = mini('Depois: tudo numa tabela só', [...(column ? [{ text: column, kind: 'to' }] : []), { text: 'uf' }, { text: 'valor' }],
      files.flatMap((f, i) => [['SP', 10 + i], ['RJ', 20 + i]].map(([uf, v]) => [
        ...(column ? [{ text: f, link: `f:${f}`, kind: 'from' }] : []), { text: uf, link: `f:${f}` }, { text: show(v), link: `f:${f}` },
      ])).slice(0, 6));
  }
  const more = files.length > 5 ? [h('span', { class: 'x-chip x-chip-muted' }, `+ ${files.length - 5} arquivo(s)`)] : [];
  return {
    body: [chips(`Na pasta, casam com ${pattern}`, [...files.slice(0, 5).map((f) => chip('file', f, { link: `f:${f}` })), ...more]), arrow('empilha as linhas'), table],
    caption: `Cada arquivo da pasta que casa com o padrão entra inteiro, um embaixo do outro, com as colunas alinhadas pelo nome.${column ? ` A coluna [${column}] diz de onde veio cada linha: passe o mouse num arquivo.` : ''}`,
    sample: Boolean(rows?.length),
  };
}

// ------------------------------------------------------------------ Generate Rows

const WEEK = ['domingo', 'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado'];

async function generateRows(n, cfg) {
  const name = (cfg.column || '').trim() || (cfg.mode === 'numbers' ? 'numero' : 'data');
  const rows = await ownRows(n, 'out', 4);
  let head;
  let body;
  if (rows?.length) {
    const cols = Object.keys(rows[0]).filter((c) => [name, 'ano_mes', 'nome_dia', 'fim_de_semana'].includes(c));
    head = cols.map((c) => ({ text: c, kind: c === name ? 'to' : null }));
    body = rows.map((r) => cols.map((c) => ({ text: show(r[c]) })));
  } else if (cfg.mode === 'numbers') {
    head = [{ text: name, kind: 'to' }];
    body = [0, 1, 2].map((i) => [{ text: show((cfg.start ?? 1) + i * (cfg.step ?? 1)) }]);
  } else {
    const start = /^\d{4}-\d{2}-\d{2}$/.test(cfg.start_date || '') ? new Date(`${cfg.start_date}T12:00:00`) : new Date('2026-01-01T12:00:00');
    head = [{ text: name, kind: 'to' }, ...(cfg.calendar === false ? [] : [{ text: 'ano_mes' }, { text: 'nome_dia' }])];
    body = [0, 1, 2].map((i) => {
      const d = new Date(start.getTime() + i * 86400000);
      const iso = d.toISOString().slice(0, 10);
      return [{ text: iso }, ...(cfg.calendar === false ? [] : [{ text: iso.slice(0, 7) }, { text: WEEK[d.getDay()] }])];
    });
  }
  body.push(head.map(() => ({ text: '…', kind: 'alone' })));
  const every = { day: 'dia', week: 'semana', month: 'mês', quarter: 'trimestre', year: 'ano' }[cfg.every || 'day'];
  const limits = cfg.mode === 'numbers'
    ? [chip('hash', `de ${show(cfg.start ?? 1)}`), chip('hash', `até ${show(cfg.end ?? 10)}`), chip('repeat', `de ${show(cfg.step ?? 1)} em ${show(cfg.step ?? 1)}`)]
    : [chip('clock', `de ${cfg.start_date || '?'}`), chip('clock', `até ${cfg.end_date || 'hoje'}`), chip('repeat', `uma linha por ${every}`)];
  return {
    body: [chips('Você informa', limits), arrow('gera as linhas'), mini('A caixa cria', head, body)],
    caption: cfg.mode === 'numbers'
      ? 'A caixa não lê nada: cria uma linha para cada número da sequência.'
      : 'A caixa não lê nada: cria uma linha para cada data do intervalo. Com um Join pela data, dias sem venda passam a aparecer com zero.',
    sample: Boolean(rows?.length),
  };
}

// ------------------------------------------------------------------ Reconcile

async function reconcile(n, cfg) {
  const rows = await ownRows(n, 'check', 12);
  const failed = nodeResult(n.id)?.status === 'error';
  const data = rows?.length ? rows : (cfg.controls?.length ? cfg.controls : [{ measure: 'count' }]).slice(0, 4).map((c, i) => {
    const name = c.measure === 'sum' ? `Soma de ${c.column_a || 'valor'}` : c.measure === 'n_unique' ? `Valores distintos de ${c.column_a || 'id'}` : 'Linhas';
    const a = [1200, 98450.3, 310][i % 3];
    return { controle: name, valor_a: a, valor_b: i === 1 ? a - 120.5 : a, diferenca: i === 1 ? -120.5 : 0, situacao: i === 1 ? 'não fecha' : 'fecha' };
  });
  const table = mini('Cada controle, calculado nos dois lados',
    [{ text: 'controle' }, { text: 'A', kind: 'from' }, { text: 'B', kind: 'to' }, { text: 'diferença' }, { text: '' }],
    data.map((r) => {
      const ok = r.situacao === 'fecha';
      return [{ text: r.controle, title: r.controle }, { text: show(r.valor_a) }, { text: show(r.valor_b) },
        { text: show(r.diferenca), kind: ok ? null : 'bad' }, { text: ok ? '✓' : '✗', title: ok ? 'fecha' : 'não fecha', kind: ok ? 'match' : 'bad' }];
    }));
  const bad = data.filter((r) => r.situacao !== 'fecha').length;
  const outcome = cfg.on_fail === 'warn'
    ? chip('alert', bad ? 'avisa e segue com os dados de [B]' : 'tudo fecha: segue com os dados de [B]', { tone: bad ? 'warn' : 'ok' })
    : chip(bad || failed ? 'x' : 'check', bad || failed ? 'não fechou: o fluxo para aqui' : 'tudo fecha: segue com os dados de [B]', { tone: bad || failed ? 'bad' : 'ok' });
  return {
    body: [h('div', { class: 'x-flow' }, chips('', [chip('table', '[A] referência', { tone: 'from' })]), arrow('mesma conta'), chips('', [chip('table', '[B] a conferir', { tone: 'to' })])), table, chips('', [outcome])],
    caption: 'O mesmo número é calculado em [A] e em [B]. Se a diferença passa do aceito, o controle não fecha.'
      + (cfg.on_fail === 'warn' ? '' : ' Com "Interromper o fluxo aqui", nada depois desta caixa executa.')
      + (failed && !rows ? ' Na última execução, a conferência não fechou: os números estão no erro acima.' : ''),
    sample: Boolean(rows?.length),
  };
}

// ------------------------------------------------------------------ Compare Runs

const day = (iso) => (iso ? String(iso).split('-').reverse().join('/') : '');

async function compareRuns(n, cfg) {
  const res = nodeResult(n.id);
  const [totals, diff] = await Promise.all([ownRows(n, 'T', 6), ownRows(n, 'D', 200)]);
  const base = res?.extra?.compare_baseline;
  const real = Boolean(totals?.length && base);
  const keys = cfg.keys || [];
  const count = (kind) => (real ? (diff || []).filter((r) => r.situacao === kind).length : { novo: 12, saiu: 3, mudou: 27 }[kind]);
  const changedKeys = real ? new Set((diff || []).filter((r) => r.situacao === 'mudou').map((r) => keys.map((k) => r[k]).join('|'))).size : 18;
  const data = real ? totals : [
    { medida: 'linhas', antes: 1200, agora: 1209, variacao_pct: 0.75 },
    { medida: 'soma de valor', antes: 98450.3, agora: 101220.1, variacao_pct: 2.81 },
  ];
  const table = mini('Saída T: totais', [{ text: 'medida' }, { text: 'antes', kind: 'from' }, { text: 'agora', kind: 'to' }, { text: 'var.' }],
    data.map((r) => [{ text: r.medida, title: r.medida }, { text: show(r.antes) }, { text: show(r.agora) },
      { text: r.variacao_pct === null || r.variacao_pct === undefined ? '—' : `${fmt.number(r.variacao_pct, 1)}%` }]));
  const line = h('div', { class: 'x-flow' },
    chip('database', real ? `guardada em ${day(base)}` : cfg.baseline === 'month' ? 'guardada no mês anterior' : 'guardada num dia anterior', { tone: 'from' }),
    arrow('compara'), chip('clock', 'execução de agora', { tone: 'to' }));
  const stats = keys.length ? h('div', { class: 'x-stats' },
    stat(fmt.int(count('novo')), 'entraram', 'ok'), stat(fmt.int(count('saiu')), 'saíram', 'bad'), stat(fmt.int(changedKeys), 'mudaram', 'warn'))
    : chips('', [chip('info', 'Sem colunas-chave: só os totais. Escolha as colunas que identificam cada linha para ver o que entrou, saiu e mudou.', { tone: 'muted' })]);
  const first = res && !base && res.status !== 'error';
  return {
    body: [line, table, keys.length ? h('div', { class: 'x-title' }, `Saída D: linha a linha, por ${keys.map((k) => `[${k}]`).join(' e ')}`) : null, stats].filter(Boolean),
    caption: first
      ? 'Primeira execução: a tabela de hoje ficou guardada. A comparação aparece na próxima execução, em outro dia.'
      : 'A cada dia de execução, a caixa guarda a tabela neste computador. A de agora é comparada com a guardada: T traz os totais e D, o que entrou, saiu e mudou.',
    sample: real,
  };
}

// ------------------------------------------------------------------ Subflow

async function subflow(n, cfg) {
  const child = cfg.workflow ? await api.workflow(cfg.workflow).catch(() => null) : null;
  const tool = (type) => store.tools[type];
  const inner = child ? child.nodes.filter((k) => !k.disabled) : [];
  const inputs = child ? inner.filter((k) => k.type === 'flow.input').map((k) => k.config?.number || 1).sort() : [1];
  const outputs = child ? inner.filter((k) => k.type === 'flow.output').map((k) => k.config?.number || 1).sort() : [1];
  const steps = child ? inner.filter((k) => !k.type.startsWith('flow.') || k.type === 'flow.subflow') : [];
  const stepChips = child
    ? [...steps.slice(0, 6).map((k) => chip(tool(k.type)?.icon || 'workflow', k.label || tool(k.type)?.name || k.type)),
      ...(steps.length > 6 ? [h('span', { class: 'x-chip x-chip-muted' }, `+ ${steps.length - 6} caixa(s)`)] : [])]
    : ['Limpeza', 'Padroniza CNPJ', 'Regras'].map((t) => chip('workflow', t));
  const box = h('div', { class: 'x-subflow' },
    h('div', { class: 'x-title' }, child ? `Fluxo ${child.name}` : cfg.workflow ? `Fluxo ${cfg.workflow} (não está na biblioteca daqui)` : 'O fluxo de origem'),
    h('div', { class: 'x-chips' }, stepChips));
  return {
    body: [chips('O que você liga nesta caixa', inputs.map((i) => chip('download', `Entrada ${i} → Subflow Input ${i}`, { tone: 'from' }))),
      arrow('executa lá dentro'), box, arrow('devolve'),
      chips('O que sai desta caixa', outputs.map((i) => chip('upload', `Subflow Output ${i} → Saída ${i}`, { tone: 'to' })))],
    caption: child
      ? `Esta caixa executa as ${steps.length} caixa(s) do fluxo ${child.name}, salvo na biblioteca. Mudou o fluxo de origem, mudam todos os que o usam.`
      : 'Esta caixa executa outro fluxo da biblioteca como uma etapa. O fluxo de origem começa em Subflow Input e termina em Subflow Output.',
    sample: Boolean(child),
  };
}

// ------------------------------------------------------------------ Fuzzy Match

function cleanText(text, cfg) {
  let t = String(text).toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '').replace(/[^a-z0-9]+/g, ' ').trim();
  if (cfg.company !== false) t = t.replace(/(\s+(ltda|limitada|eireli|epp|me|mei|sa|s a|cia|companhia))+$/, '').trim();
  if (cfg.method === 'words') t = t.split(' ').sort().join(' ');
  return t;
}

async function fuzzy(n, cfg) {
  const rows = await ownRows(n, 'J', 5);
  const score = (cfg.score_column || '').trim() || 'nota';
  const right = rows?.length ? [cfg.right, `${cfg.right_prefix ?? 'r_'}${cfg.right}`].find((c) => c in rows[0] && c !== cfg.left) : null;
  const real = Boolean(rows?.length && cfg.left in rows[0] && right);
  const pairs = real ? rows.map((r) => [r[cfg.left], r[score], r[right]]) : [
    ['Padaria Pão Quente LTDA', 100, 'PADARIA PAO QUENTE'], ['Mercado Bom Preço S.A.', 100, 'Mercado Bom Preco'], ['Transportadora Rápido Sul', 96.5, 'Transp. Rapdio Sul'],
  ];
  const sample = pairs[0][0];
  const clean = h('div', { class: 'x-flow' }, chip('edit', short(sample, 30)), arrow('limpa'), chip('check', cleanText(sample, cfg) || '(vazio)', { tone: 'ok' }));
  const table = mini('Saída J: cada linha de [L] com o seu melhor par', [{ text: cfg.left || 'esquerda', kind: 'from' }, { text: score }, { text: cfg.right || 'direita', kind: 'to' }],
    pairs.map(([l, s, r], i) => [{ text: show(l), title: show(l), link: `p${i}` }, { text: show(s), kind: Number(s) >= 100 ? 'match' : 'g1', link: `p${i}` }, { text: show(r), title: show(r), link: `p${i}` }]));
  const done = nodeResult(n.id)?.extra;
  return {
    body: [h('div', { class: 'x-title' }, 'Antes de comparar, os dois lados são limpos'), clean, arrow(`nota ≥ ${cfg.threshold ?? 88}`), table],
    caption: 'A nota vai de 0 a 100: 100 é igual depois de limpar acentos, maiúsculas e pontuação. Abaixo da nota mínima, o par não entra, e a linha sai em L ou R.'
      + (done?.fuzzy_pairs !== undefined ? ` Na última execução: ${fmt.int(done.fuzzy_pairs)} comparações, ${fmt.int(done.fuzzy_matched)} pares.` : ''),
    sample: real,
  };
}

// ------------------------------------------------------------------ Regex

async function regex(n, cfg) {
  const rows = await inputRows(n);
  const real = Boolean(rows?.length && cfg.column && cfg.column in rows[0]);
  const values = real ? [...new Set(rows.map((r) => r[cfg.column]).filter((v) => v !== null && v !== undefined).map(String))].slice(0, 5)
    : ['NF 10/2026', 'NF 03/2025', 'sem data'];
  const pattern = cfg.pattern || '(\\d{2})/(\\d{4})';
  let re = null;
  try { re = new RegExp(pattern, cfg.ignore_case ? 'iu' : 'u'); } catch { re = null; }
  const mode = cfg.mode || 'extract';
  const names = (cfg.names || []).filter((x) => x.trim());
  const groups = re ? Math.max(1, new RegExp(`${pattern}|`).exec('').length - 1) : 1;
  const head = mode === 'match' ? [{ text: (cfg.output || '').trim() || 'casou', kind: 'to' }]
    : mode === 'replace' ? [{ text: (cfg.output || '').trim() || cfg.column || 'resultado', kind: 'to' }]
      : Array.from({ length: groups }, (_, i) => ({ text: names[i] || `grupo_${i + 1}`, kind: 'to' }));
  const table = mini('Cada linha, antes e depois', [{ text: cfg.column || 'texto', kind: 'from' }, ...head], values.map((v, i) => {
    const m = re ? re.exec(v) : null;
    let out;
    if (mode === 'match') out = [{ text: m ? 'verdadeiro' : 'falso', kind: m ? 'match' : 'alone' }];
    else if (mode === 'replace') out = [{ text: re ? v.replace(new RegExp(pattern, cfg.ignore_case ? 'giu' : 'gu'), cfg.replacement || '') : '?' }];
    else out = head.map((_, g) => ({ text: m ? show(m.length > 1 ? m[g + 1] : m[0]) : '—', kind: m ? 'match' : 'alone' }));
    return [{ text: v, title: v, link: `r${i}` }, ...out.map((c) => ({ ...c, link: `r${i}` }))];
  }));
  return {
    body: [chips('O padrão', [chip('search', pattern, { tone: re ? 'from' : 'bad' })]), arrow({ extract: 'cada grupo vira uma coluna', replace: 'troca o que casar', match: 'marca quem casa' }[mode]), table],
    caption: (re ? '' : 'Este padrão não é uma expressão regular válida. ')
      + { extract: 'Cada par de parênteses do padrão é um grupo, e cada grupo vira uma coluna nova. Linha que não casa fica vazia.',
        replace: 'Tudo o que casar com o padrão é trocado. $1, $2… repetem os grupos no texto novo.',
        match: 'A coluna nova diz, linha a linha, se o texto casa com o padrão.' }[mode]
      + ' O esquema usa o navegador para ilustrar; o resultado de verdade é o do motor.',
    sample: real,
  };
}

// ------------------------------------------------------------------ Multi-Field Formula

async function multiField(n, cfg) {
  const [before, after] = await Promise.all([inputRows(n, 'in', 4), ownRows(n, 'out', 4)]);
  const cols = (cfg.columns || []).slice(0, 3);
  const target = (c) => (cfg.target === 'new' ? `${cfg.prefix || ''}${c}${cfg.suffix ?? '_novo'}` : c);
  const real = Boolean(before?.length && after?.length && cols.length && cols.every((c) => c in before[0] && target(c) in after[0]));
  const names = cols.length ? cols : ['nome', 'cidade'];
  const example = [['  ana ', ' recife'], ['BRUNO', 'Natal ']];
  const expr = cfg.expression || 'Trim(Uppercase([_Atual_]))';
  const left = mini('Antes', names.map((c) => ({ text: c, kind: 'from' })),
    (real ? before : example).slice(0, 3).map((r, i) => names.map((c, k) => ({ text: show(real ? r[c] : r[k % 2]), link: `c${k}r${i}` }))));
  const right = mini(cfg.target === 'new' ? 'Depois: uma coluna nova para cada uma' : 'Depois: as mesmas colunas, com valores novos',
    names.map((c) => ({ text: target(c), kind: 'to' })),
    (real ? after : example.map((r) => r.map((v) => v.trim().toUpperCase()))).slice(0, 3)
      .map((r, i) => names.map((c, k) => ({ text: show(real ? r[target(c)] : r[k % 2]), link: `c${k}r${i}` }))));
  return {
    body: [left, h('div', { class: 'x-formula mono' }, expr.replace(/\[_(atual|currentfield)_\]/gi, '[cada coluna]')), arrow('a mesma fórmula em cada coluna'), right],
    caption: `[_Atual_] é a coluna da vez: a fórmula roda uma vez para cada uma das ${cols.length || 'colunas'} escolhida(s), sem você repetir a conta.`,
    sample: real,
  };
}

// ------------------------------------------------------------------ Mask

const digits = (v) => v.replace(/[^a-z0-9]/gi, '');
const MASKS = {
  cpf: ['123.456.789-09', (v) => `***.${digits(v).slice(3, 6)}.${digits(v).slice(6, 9)}-**`],
  cnpj: ['12.345.678/0001-95', (v) => `**.${digits(v).slice(2, 5)}.${digits(v).slice(5, 8)}/****-**`],
  email: ['ana.souza@empresa.com.br', (v) => `${v[0]}***@${v.split('@')[1]}`],
  keep_last: ['4111 1111 1111 1234', (v, cfg) => '*'.repeat(Math.max(0, v.length - cfg.keep)) + (cfg.keep ? v.slice(-cfg.keep) : '')],
  keep_first: ['Ana Souza Lima', (v, cfg) => v.slice(0, cfg.keep) + '*'.repeat(Math.max(0, v.length - cfg.keep))],
  fixed: ['qualquer valor', (_v, cfg) => cfg.text ?? '***'],
  code: ['123.456.789-09', () => 'a3f91c07be5d2248'],
};

async function mask(_n, cfg) {
  const method = cfg.method in MASKS ? cfg.method : 'cpf';
  const [sample, fn] = MASKS[method];
  const settings = { keep: cfg.keep ?? 4, text: cfg.text };
  const cols = (cfg.columns || []).slice(0, 3);
  const rows = [sample, ...(method === 'cpf' ? ['987.654.321-00'] : method === 'email' ? ['b.lima@loja.com'] : method === 'code' ? ['987.654.321-00', '123.456.789-09'] : [])];
  const codes = { '123.456.789-09': 'a3f91c07be5d2248', '987.654.321-00': '5d02b7e1c94a6f30' };
  const table = mini('Exemplos fictícios', [{ text: cols.join(', ') || 'coluna', kind: 'from' }, { text: 'depois', kind: 'to' }],
    rows.map((v, i) => [{ text: v, link: `m${method === 'code' ? v : i}` }, { text: method === 'code' ? codes[v] : fn(v, settings), link: `m${method === 'code' ? v : i}`, kind: 'match' }]));
  return {
    body: [table, method === 'code' ? chips('', [chip('lock', 'chave guardada no cofre do Windows deste computador', { tone: 'muted' })]) : null].filter(Boolean),
    caption: (method === 'code'
      ? 'O mesmo valor dá sempre o mesmo código: dá para cruzar e contar sem expor o dado. Sem a chave, não dá para voltar ao valor, e em outro computador o código é outro.'
      : 'O valor verdadeiro sai da tabela: o que segue no fluxo é só a versão protegida. O que não tem o formato esperado vira ***.')
      + ' O esquema usa exemplos inventados, nunca os seus dados.',
    sample: false,
    note: 'exemplo',
  };
}

// ------------------------------------------------------------------ modelo (Model Trainer e Model Input)

const ALGO = { random_forest: 'Random Forest', gradient_boosting: 'Gradient Boosting', linear: 'Linear / Logística' };

async function modelCard(n, cfg) {
  const res = nodeResult(n.id);
  const isInput = n.type === 'ml.model_input';
  let card = res?.extra?.ml_card || null;
  if (!card && isInput && cfg.model) card = (await api.models().catch(() => [])).find((m) => m.name === cfg.model) || null;
  if (!card && !isInput && res?.extra?.ml_model) {
    const model = res.extra.ml_model;
    const m = res.extra.ml_metrics || {};
    card = { task_type: m.task, algorithm: m.algorithm, target_column: cfg.target_column, metrics: m, trained_at: model.trained_at, rows: model.rows, version: model.version, feature_columns: cfg.feature_columns || [] };
  }
  const m = card?.metrics || {};
  const quality = !card ? 'depois de treinar' : m.task === 'classification' || card.task_type === 'classification'
    ? `acurácia ${fmt.number(m.accuracy_pct)}% · F1 ${fmt.number(m.f1_pct)}%` : `R² ${fmt.number(m.r2, 3)} · erro médio ${fmt.number(m.mae)}`;
  const row = (label, value) => h('div', { class: 'x-kv' }, h('span', {}, label), h('strong', {}, value));
  const features = card?.feature_columns?.length ? card.feature_columns : null;
  const published = isInput ? cfg.model : (cfg.publish_as || '').trim();
  const sheet = h('div', { class: 'x-card' },
    h('div', { class: 'x-title' }, isInput ? `Modelo ${cfg.model || '(escolha na lista)'}` : 'O modelo desta caixa'),
    row('Prevê', card?.target_column ? `[${card.target_column}]` : cfg.target_column ? `[${cfg.target_column}]` : 'a coluna alvo'),
    row('Tarefa', { classification: 'classificação', regression: 'regressão' }[card?.task_type || cfg.task_type] || '—'),
    row('Algoritmo', ALGO[card?.algorithm || cfg.algorithm] || '—'),
    row('Qualidade, em dados que ele não viu', quality),
    row('Treinado', card?.trained_at ? `em ${new Date(card.trained_at).toLocaleDateString('pt-BR')}, com ${fmt.int(card.rows)} linhas${card.version ? ` (v${card.version})` : ''}` : 'ainda não'),
    features ? h('div', { class: 'x-chips' }, h('div', { class: 'x-title' }, 'Precisa destas colunas para prever'), features.slice(0, 8).map((f) => chip('columns', f)),
      features.length > 8 ? h('span', { class: 'x-chip x-chip-muted' }, `+ ${features.length - 8}`) : null) : null);
  const path = h('div', { class: 'x-chips x-path' },
    chip('brain', 'Model Trainer treina', { tone: isInput ? 'muted' : 'from' }), icon('chevron-right', 14),
    chip('database', published ? `biblioteca: ${published}` : 'biblioteca de modelos', { tone: published ? 'ok' : 'muted' }), icon('chevron-right', 14),
    chip('brain', 'Model Input traz', { tone: isInput ? 'from' : 'muted' }), icon('chevron-right', 14),
    chip('wand', 'Predictor aplica', { tone: 'to' }));
  return {
    body: [path, sheet],
    caption: isInput
      ? 'Esta caixa não treina: traz um modelo pronto da biblioteca deste computador. Ligue [M] num Predictor, e os dados precisam ter as colunas que o modelo conhece.'
      : published
        ? `Com o nome ${published}, este modelo fica na biblioteca: a caixa Model Input usa em qualquer fluxo, e o arquivo pode ser exportado para outro computador.`
        : 'O modelo fica guardado para esta caixa. Dê um nome em "Nome na biblioteca de modelos" para usar em outros fluxos com a caixa Model Input.',
    sample: Boolean(card),
  };
}

const EXTRA = {
  input_folder: inputFolder, generate_rows: generateRows, reconcile, compare_runs: compareRuns, subflow, fuzzy,
  regex, multi_field: multiField, mask, model_card: modelCard,
};

export const hasExtraExplainer = (name) => name in EXTRA;

export function extraExplain(name, n, cfg, kit) {
  ({ mini, arrow } = kit);
  return EXTRA[name](n, cfg);
}
