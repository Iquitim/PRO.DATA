// Campos que listam os valores de uma coluna: escolher valores e renomear rótulos.

import { debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';

/**
 * Marca valores que existem numa coluna da entrada (ex.: grupos do Venn), até `max_items`.
 * A coluna vem do campo `field.source`; sem execução, cai para digitação livre.
 */
export function columnValues(field, value, set, ctx, id, values) {
  const selected = Array.isArray(value) ? [...value] : [];
  const max = field.max_items || Infinity;
  const column = values?.[field.source];
  if (!column) return h('p', { class: 'field-help' }, 'Escolha antes a coluna do grupo.');
  const wrap = h('div', { class: 'value-picker' }, h('p', { class: 'field-help' }, 'Carregando os valores…'));
  const toggle = (v) => set(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  const full = () => selected.length >= max;
  const chip = (v) => {
    const on = selected.includes(v.value);
    return h('button', {
      type: 'button', class: ['value-chip', on && 'on'], 'aria-pressed': String(on), disabled: !on && full(),
      title: !on && full() ? `Máximo de ${max}: desmarque um para trocar` : null,
      onclick: () => toggle(v.value),
    }, icon(on ? 'check' : 'plus', 12), h('span', { class: 'ellipsis' }, v.value), h('span', { class: 'muted' }, fmt.int(v.count)));
  };
  const draw = (data) => {
    const known = new Set(data.values.map((v) => v.value));
    // Coluna com muitos valores (spec 017): provavelmente um identificador. Mostra só os mais frequentes
    // e busca no servidor, para não despejar milhares de opções na tela.
    const many = data.distinct > MANY_VALUES;
    const list = h('div', { class: 'value-list', role: 'group', 'aria-label': field.title });
    const note = h('p', { class: 'field-help' });
    const fill = (rows, label) => { list.replaceChildren(...rows.map(chip)); note.textContent = label; };
    const top = () => fill(data.values.slice(0, many ? TOP_WHEN_MANY : 200),
      many ? `Mostrando os ${TOP_WHEN_MANY} mais frequentes. Busque para achar outros.` : '');
    top();
    const search = (needle) => {
      if (!needle) { top(); return; }
      if (!many && !data.truncated) {
        const found = data.values.filter((v) => v.value.toLowerCase().includes(needle.toLowerCase()));
        fill(found.slice(0, 200), found.length ? '' : 'Nenhum valor encontrado.');
        return;
      }
      ctx.values(column, null, needle)
        .then((res) => fill(res.values.slice(0, 50), res.matches > 50
          ? `${fmt.int(res.matches)} valores encontrados; mostrando 50. Refine a busca.`
          : res.matches ? '' : 'Nenhum valor encontrado.'))
        .catch(() => fill([], 'Não foi possível buscar agora.'));
    };
    const lost = selected.filter((v) => !known.has(v) && !many);
    wrap.replaceChildren(...[ // replaceChildren() nativo escreveria "null" para os itens ausentes
      h('div', { class: 'value-head' },
        h('span', {}, `${selected.length} de ${max === Infinity ? data.distinct : max} marcados`),
        h('span', { class: 'muted' }, `${fmt.int(data.distinct)} valores em [${column}]`)),
      many ? h('p', { class: 'field-warn' }, icon('alert', 13),
        ` [${column}] tem ${fmt.int(data.distinct)} valores diferentes: parece um identificador, não um grupo. `
        + 'O Venn compara 2 ou 3 grupos — prefira uma coluna com poucos valores (produto, segmento). Se for esta mesmo, busque o valor.') : null,
      selected.length ? h('div', { class: 'chips' }, selected.map((v) => h('span', { class: ['chip', lost.includes(v) && 'invalid'], title: lost.includes(v) ? 'Não existe mais nesta coluna' : null },
        lost.includes(v) ? `${v} (não encontrado)` : v,
        h('button', { type: 'button', class: 'chip-x', 'aria-label': `Remover ${v}`, onclick: () => toggle(v) }, icon('x', 12))))) : null,
      many || data.values.length > 12
        ? h('input', { id, class: 'input', type: 'search', placeholder: 'Buscar valor…', oninput: debounce((e) => search(e.target.value.trim()), 250) })
        : null,
      list,
      note,
    ].filter(Boolean));
  };
  const manual = () => wrap.replaceChildren(
    h('p', { class: 'field-help' }, 'Execute o fluxo para escolher os valores numa lista. Enquanto isso, digite:'),
    tags(field, value, set, ctx, id));
  (ctx.values ? ctx.values(column) : Promise.reject()).then(draw).catch(manual);
  return wrap;
}

const MANY_VALUES = 50;
const TOP_WHEN_MANY = 15;

/** Nomes exibidos: uma linha por série, categoria ou conjunto do visual (ctx.categories). Vazio = original. */
export function renameLabels(field, value, set, ctx) {
  const map = { ...(value || {}) };
  const cats = ctx.categories || [];
  if (!cats.length) return h('p', { class: 'field-help' }, 'Execute o fluxo para listar os nomes.');
  return h('div', { class: 'rename-labels' }, cats.slice(0, 60).map((cat) => h('label', { class: 'rename-row' },
    h('span', { class: 'ellipsis muted', title: cat }, cat),
    h('input', {
      class: 'input', value: map[cat] || '', placeholder: cat, 'aria-label': `Nome exibido para ${cat}`,
      oninput: (e) => {
        if (e.target.value.trim()) map[cat] = e.target.value; else delete map[cat];
        set({ ...map });
      },
    }))));
}
