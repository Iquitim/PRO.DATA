// Mapa de uso (spec 028, RF-2815): a fonte ligada a cada fluxo que a usa, com as caixas na ordem dos dados.
// Mesmas cores e caixas do Designer; passar o mouse num fluxo acende o caminho inteiro.

import { h } from './dom.js';
import { icon } from './icons.js';
import { store } from './store.js';
import { KINDS } from './data_sources.js';

const MAX_STEPS = 9; // além disso, o resto vira "+N"

function step(node, joined, onOpen) {
  const tool = store.tools[node.type];
  const cat = tool?.category || 'org';
  return h('span', { class: 'dv-step-wrap' },
    joined ? h('span', { class: 'dv-link', 'aria-hidden': 'true' }) : null,
    h('button', {
      type: 'button', class: 'dv-step', style: { '--cat': `var(--cat-${cat})` }, title: 'Abrir esta caixa no Designer',
      onclick: () => onOpen(node.id),
    },
    h('span', { class: 'dv-step-icon' }, icon(tool?.icon || 'square', 14)),
    h('span', { class: 'dv-step-text' }, h('b', {}, node.label || tool?.name || node.type), h('small', {}, tool?.name || node.type))));
}

function lane(entry, onOpen) {
  const chain = [...entry.readers, ...entry.downstream];
  const shown = chain.slice(0, MAX_STEPS);
  const open = (nodeId) => onOpen(entry.workflow_id, nodeId);
  const visuals = entry.downstream.filter((d) => d.type.startsWith('bi.')).length;
  const outputs = entry.downstream.filter((d) => d.type === 'io.output_data').length;
  const effect = [visuals ? `${visuals} visual(is) no dashboard` : '', outputs ? `${outputs} arquivo(s) gravado(s)` : '']
    .filter(Boolean).join(' e ');
  return h('section', { class: 'dv-lane' },
    h('header', { class: 'dv-lane-head' },
      icon('workflow', 15), h('strong', {}, entry.workflow),
      h('span', { class: 'muted' }, `${entry.readers.length} caixa(s) leem · ${entry.downstream.length} depois`),
      h('button', { type: 'button', class: 'btn btn-sm btn-ghost dv-lane-open', onclick: () => open(entry.readers[0]?.id) }, 'Abrir no Designer')),
    h('div', { class: 'dv-chain' }, shown.map((n, i) => step(n, i > 0, open)),
      chain.length > shown.length ? h('span', { class: 'dv-more' }, `+${chain.length - shown.length}`) : null),
    h('p', { class: 'dv-lane-effect' }, effect
      ? `Mudar esta fonte muda ${effect} deste fluxo.`
      : 'Mudar esta fonte muda as caixas acima na próxima execução.'));
}

/** `uses`: o que /api/usage devolve para a fonte. `onOpen(workflowId, nodeId)` abre a caixa no Designer. */
export function usageMap(source, uses, onOpen) {
  if (!uses.length) {
    return h('div', { class: 'dv-empty-map' }, icon('info', 18),
      h('div', {}, h('strong', {}, 'Nenhum fluxo da biblioteca usa esta fonte'),
        h('p', {}, 'Ela pode ser excluída sem afetar nada. Fluxos salvos em outras pastas não entram nesta conta.')));
  }
  const kind = KINDS[source.kind];
  const totals = [
    [uses.length, 'fluxo(s)'],
    [uses.reduce((n, u) => n + u.readers.length, 0), 'caixa(s) leem a fonte'],
    [uses.reduce((n, u) => n + u.downstream.length, 0), 'caixa(s) depois delas'],
    [uses.reduce((n, u) => n + u.downstream.filter((d) => d.type.startsWith('bi.')).length, 0), 'visual(is)'],
  ];
  return h('div', { class: 'stack-sm' },
    h('div', { class: 'dv-totals' }, totals.map(([n, label]) => h('span', { class: 'dv-total' }, h('b', {}, String(n)), label))),
    h('div', { class: 'dv-map', role: 'group', 'aria-label': 'Mapa de uso' },
      h('div', { class: 'dv-map-source', style: { '--kind': kind.color } },
        h('span', { class: 'dv-map-kind' }, kind.one), h('strong', {}, source.name), h('small', {}, source.meta)),
      h('span', { class: 'dv-map-trunk', 'aria-hidden': 'true' }),
      h('div', { class: 'dv-lanes' }, uses.map((u) => lane(u, onOpen)))),
    h('p', { class: 'field-help' }, icon('info', 12),
      ' Cada faixa é um fluxo da biblioteca, com as cores do Designer. Fluxos salvos em outras pastas não aparecem.'));
}
