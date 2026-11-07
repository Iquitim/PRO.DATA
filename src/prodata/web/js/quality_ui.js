// Data Quality no Configurar (spec 028): a pergunta em cartões, as regras escolhidas e o esquema "Como funciona".

import { button, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { fits, RULES, ruleOf, sampleFailures } from './quality_rules.js';

/** Cartões de regra e a lista do que foi escolhido. `renderFields` vem de fields.js, que monta cada regra. */
export function qualityRulesField(field, value, set, ctx, { renderFields }) {
  const rules = Array.isArray(value) ? value : [];
  const cols = ctx.columns?.('in') || [];
  const add = (kind) => {
    const column = cols.find((c) => fits(kind, c.type))?.name || '';
    set([...rules, { ...structuredClone(field.item_default), kind, column }]);
  };
  const cards = h('div', { class: 'dq-cards', role: 'group', 'aria-label': 'Regras prontas' }, RULES.map((r) => {
    const count = rules.filter((x) => x.kind === r.kind).length;
    return h('button', {
      type: 'button', class: ['dq-card', count && 'active'], dataset: { kind: r.kind }, title: `Adicionar a regra ${r.name}`,
      onclick: () => add(r.kind),
    },
    h('span', { class: 'dq-card-head' }, icon(r.icon, 14), h('b', {}, r.name), count ? h('span', { class: 'dq-card-count' }, String(count)) : null),
    h('small', { class: 'dq-pass' }, `✓ ${r.pass}`),
    h('small', { class: 'dq-fail' }, `✗ ${r.fail}`));
  }));
  const fields = field.item_fields.filter((f) => f.name !== 'kind');
  const list = rules.map((rule, i) => {
    // A coluna conferida vem da entrada I; a da lista permitida, da L (RF-2840).
    const itemCtx = { ...ctx, columns: (port) => (ctx.columns?.(port || 'in') || []).filter((c) => fits(rule.kind, c.type)) };
    const body = renderFields(fields, rule, (path, v) => set(v, [i, ...path]), itemCtx);
    body.classList.add('list-item-fields');
    return h('div', { class: 'list-item dq-rule' },
      h('div', { class: 'list-item-head' },
        h('span', { class: 'list-item-index' }, `${i + 1}`),
        h('strong', { class: 'dq-rule-name' }, icon(ruleOf(rule.kind).icon, 13), ruleOf(rule.kind).name),
        button({ icon: 'trash', title: 'Tirar esta regra', size: 'sm', variant: 'ghost', onClick: () => set(rules.filter((_, j) => j !== i)) })),
      body);
  });
  return h('div', { class: 'stack-sm' },
    h('span', { class: 'field-label' }, 'Que regra você quer conferir?'),
    cards,
    rules.length
      ? h('div', { class: 'stack-xs' }, h('span', { class: 'field-label' }, `Regras escolhidas (${rules.length})`), ...list,
        h('p', { class: 'field-help' }, 'Vazio passa nas regras de formato: use "Não vazio" para cobrar o preenchimento. Regras de número só aparecem para números.'))
      : h('p', { class: 'field-help' }, 'Clique num cartão para adicionar a regra. Cada uma vale para uma coluna.'));
}

const show = (v) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'number' ? fmt.number(v) : String(v));

/** Esquema "Como funciona": a amostra com as células reprovadas, e as contas de P e F. */
export function qualityExplain(cfg, rows, result, { mini }) {
  const rules = (cfg.rules || []).filter((r) => r.kind === 'formula' || r.column);
  if (!rules.length) {
    return { body: [h('p', { class: 'muted' }, 'Escolha uma regra para ver o esquema.')], caption: 'O que passa em todas as regras sai por P; o que falha em alguma sai por F, com o motivo.' };
  }
  const columns = [...new Set(rules.filter((r) => r.column).map((r) => r.column))].slice(0, 4);
  const sample = rows?.length ? rows : null;
  const shown = (sample || []).slice(0, 6);
  const failures = sampleFailures(shown, rules);
  const before = shown.length
    ? mini('Antes: a tabela que chega', columns.map((c) => ({ text: c })), shown.map((row, i) => columns.map((c) => {
      const broken = rules.map((r, k) => (r.column === c && failures[i][k] ? r : null)).filter(Boolean);
      return { text: show(row[c]), kind: broken.length ? 'bad' : null, link: broken.length ? `dq${i}` : null,
        title: broken.length ? `Reprovada: ${broken.map((r) => ruleOf(r.kind).name).join(', ')}` : null };
    })))
    : h('p', { class: 'muted' }, 'Execute o fluxo para ver a amostra dos seus dados aqui.');
  const extra = result?.extra || {};
  const real = typeof extra.dq_failed === 'number';
  const failedRows = failures.filter((f) => f.some(Boolean)).length;
  const counts = real
    ? (extra.dq_rules || []).map((r) => `${fmt.int(r.failed)} em ${r.rule}${r.column ? ` [${r.column}]` : ''}`)
    : rules.map((r, k) => `${failures.filter((f) => f[k]).length} em ${ruleOf(r.kind).name}`);
  const outputs = h('div', { class: 'dq-outputs' },
    h('div', { class: 'dq-out pass' }, h('strong', {}, 'P · passou em tudo'),
      h('b', {}, real ? `${fmt.int(extra.dq_passed)} linhas` : `${shown.length - failedRows} na amostra`)),
    h('div', { class: 'dq-out fail' }, h('strong', {}, 'F · falhou'),
      h('b', {}, real ? `${fmt.int(extra.dq_failed)} linhas` : `${failedRows} na amostra`),
      h('small', {}, counts.join(' · '))));
  const formulaNote = !real && rules.some((r) => r.kind === 'formula' || (r.kind === 'allowed' && r.values_from === 'table'))
    ? ' A fórmula livre e a lista da entrada L são conferidas ao executar.' : '';
  return {
    body: [before, h('div', { class: 'x-arrow' }, `↓ ${rules.length} regra(s)`), outputs],
    caption: `${real ? 'Contas da última execução.' : 'Contas na amostra.'} Passe o mouse numa célula vermelha para ver qual regra a reprovou.${formulaNote}`,
    sample: Boolean(sample),
  };
}
